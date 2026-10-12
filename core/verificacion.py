"""
Verificación de correos con ClearBounce antes de entregar un lote.

Flujo:
  1. crear_borrador()        elige los correos (como siempre) pero NO marca nada todavía.
  2. iniciar_verificacion()  sube a ClearBounce los que no tengan un resultado reciente.
  3. progreso()              la página lo consulta cada pocos segundos; cuando ClearBounce termina,
                             guarda los resultados y marca los MALOS como inválidos automáticamente.
  4. reponer()               (opcional) agrega correos nuevos para cubrir los malos y se verifican igual.
  5. confirmar()             crea el lote con los buenos y los marca como usados (como el botón de antes).

Un borrador sin confirmar no cambia el estado de ningún correo (salvo los malos que ClearBounce
rechazó, que sí quedan inválidos porque ya se pagó por saberlo).
"""
import csv
import io
import json
from datetime import datetime, timedelta

from . import archivos as A
from . import clearbounce as cb
from . import db
from .config import clearbounce as ajustes_cb
from .db import ahora
from .servicio import (_chunks, _crear_lote, _estados_actuales, _guardar_copia, _guardar_meta, _leer_meta,
                       _marcar, _marcar_usados, seleccionar)

ABIERTOS = ("borrador", "verificando", "listo")
POLITICAS = ("fuera", "catchall", "incluir", "invalidar")
MOTIVO_CATCHALL = "low_deliverability"
LIMITE_LISTA = 1000  # cuántos malos/dudosos se muestran en la página (el CSV trae todos)


# =================================================================== créditos
def estado_clearbounce(con, refrescar=True):
    """Créditos y configuración. Si la consulta falla devuelve el último saldo conocido."""
    info = {"configurado": cb.configurada(), "modo": cb.modo(), "creditos": None, "actualizado": None, "error": None}
    ultimo = _leer_meta(con, "cb_creditos") or {}
    info["creditos"], info["actualizado"] = ultimo.get("creditos"), ultimo.get("fecha")
    if not info["configurado"] or not refrescar:
        return info
    try:
        n, _ = cb.creditos()
        if n is not None:
            info["creditos"], info["actualizado"] = n, ahora()
            with con:
                _guardar_meta(con, "cb_creditos", {"creditos": n, "fecha": info["actualizado"]})
        else:
            info["error"] = "ClearBounce respondió, pero no reconocí el saldo (usa /api/clearbounce/diagnostico)."
    except cb.ErrorClearBounce as e:
        info["error"] = str(e)
    return info


def diagnostico():
    """Respuesta cruda de /credits para revisar el formato (la API key no se muestra)."""
    cfg = ajustes_cb()
    clave = cfg["api_key"]
    datos = {"base_url": cfg["base_url"], "api_key": (clave[:12] + "…" + clave[-4:]) if len(clave) > 16 else
             ("(vacía)" if not clave else "(muy corta)"), "modo": cb.modo()}
    try:
        n, crudo = cb.creditos()
        datos.update(creditos_detectados=n, respuesta=crudo)
    except cb.ErrorClearBounce as e:
        datos.update(error=str(e), status=e.status)
    return datos


# =================================================================== borradores
def _borrador(con, bid):
    b = con.execute("SELECT * FROM borradores WHERE id=?", (bid,)).fetchone()
    if not b:
        raise ValueError("Ese borrador no existe.")
    return b


def _cerrar_abiertos(con):
    en_curso = con.execute("SELECT id FROM borradores WHERE estado='verificando'").fetchone()
    if en_curso:
        raise ValueError(f"Hay una verificación en curso (borrador #{en_curso['id']}). "
                         "Espera a que termine o confírmala antes de generar otro.")
    con.execute("UPDATE borradores SET estado='descartado' WHERE estado IN ('borrador','listo')")


def _agregar_items(con, bid, emails, base=0, ronda=1):
    """Inserta correos al borrador reutilizando resultados recientes de ClearBounce (no se pagan dos veces)."""
    dias = ajustes_cb()["dias_cache"]
    limite = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
    cache = {}
    if not base and dias > 0:
        for parte in _chunks(list(emails)):
            q = (f"SELECT email, cb_estado, cb_motivo, cb_puntaje FROM contactos WHERE cb_estado IS NOT NULL "
                 f"AND cb_fecha >= ? AND email IN ({','.join('?' * len(parte))})")
            for r in con.execute(q, [limite, *parte]):
                cache[r["email"]] = (r["cb_estado"], r["cb_motivo"], r["cb_puntaje"])
    filas = []
    for e in emails:
        c = cache.get(e)
        filas.append((bid, e, base, ronda, c[0] if c else None, c[1] if c else None, c[2] if c else None, 1 if c else 0))
    con.executemany("INSERT OR IGNORE INTO borrador_items(borrador_id, email, base, ronda, cb_estado, cb_motivo, "
                    "cb_puntaje, cache) VALUES(?,?,?,?,?,?,?,?)", filas)


def _sumar_avisos(con, bid, nuevos):
    b = _borrador(con, bid)
    avisos = json.loads(b["avisos"] or "[]") + list(nuevos)
    con.execute("UPDATE borradores SET avisos=? WHERE id=?", (json.dumps(avisos[-12:], ensure_ascii=False), bid))


def crear_borrador(con, f, cantidad, nombre=""):
    """Paso 1 de "Generar": elige los correos y muestra estadísticas. No marca nada."""
    con.execute("BEGIN IMMEDIATE")
    try:
        _cerrar_abiertos(con)
        emails, avisos, _ = seleccionar(con, f, cantidad)
        if not emails:
            raise ValueError("No hay correos disponibles con esos filtros.")
        cur = con.execute("INSERT INTO borradores(fecha, tipo, nombre, cantidad, filtros, estado, avisos) "
                          "VALUES(?,?,?,?,?,?,?)", (ahora(), "generado", nombre or "", len(emails),
                                                    json.dumps({**f, "cantidad": cantidad}, ensure_ascii=False),
                                                    "borrador", json.dumps(avisos, ensure_ascii=False)))
        bid = cur.lastrowid
        _agregar_items(con, bid, emails)
        con.commit()
    except Exception:
        con.rollback()
        raise
    return resumen_borrador(con, bid)


def crear_borrador_completar(con, archivos, cantidad, f, nombre=""):
    """2b con verificación: los buenos del archivo se respetan y solo los NUEVOS se verifican."""
    buenos, _, _ = A.emails_de_archivos(archivos)
    if not buenos:
        raise ValueError("No encontré correos en el archivo de buenos.")
    con.execute("BEGIN IMMEDIATE")
    try:
        _cerrar_abiertos(con)
        actuales = _estados_actuales(con, buenos)
        descartados = {e for e in buenos if actuales.get(e, ("usado",))[0] in ("invalido", "baja")}
        base = [e for e in buenos if e not in descartados]
        avisos = [f"{len(descartados)} correos del archivo están marcados como inválidos o baja y se quitaron."] \
            if descartados else []
        cur = con.execute("INSERT INTO borradores(fecha, tipo, nombre, cantidad, filtros, estado, avisos) "
                          "VALUES(?,?,?,?,?,?,?)", (ahora(), "completado", nombre or "", 0,
                                                    json.dumps({**f, "cantidad": cantidad}, ensure_ascii=False),
                                                    "borrador", "[]"))
        bid = cur.lastrowid
        _agregar_items(con, bid, base, base=1)
        nuevos = []
        if cantidad > 0:
            nuevos, av, _ = seleccionar(con, f, cantidad, excluir_borrador=bid)
            avisos += av
            _agregar_items(con, bid, nuevos)
        con.execute("UPDATE borradores SET cantidad=?, avisos=? WHERE id=?",
                    (len(nuevos), json.dumps(avisos, ensure_ascii=False), bid))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return resumen_borrador(con, bid)


def pendiente(con):
    b = con.execute("SELECT id FROM borradores WHERE estado IN ('borrador','verificando','listo') "
                    "ORDER BY id DESC LIMIT 1").fetchone()
    return resumen_borrador(con, b["id"]) if b else None


def descartar(con, bid):
    b = _borrador(con, bid)
    if b["estado"] == "verificando":
        raise ValueError("Está verificando: espera a que termine (los créditos ya se usaron y los resultados se guardan).")
    if b["estado"] == "generado":
        raise ValueError("Ese borrador ya se convirtió en lote. Para deshacerlo usa 'Anular' en el Historial.")
    with con:
        con.execute("UPDATE borradores SET estado='descartado' WHERE id=?", (bid,))
    return {"ok": True}


# =================================================================== resumen
def _grupo(item):
    if item["base"]:
        return "base"
    if not item["cb_estado"]:
        return "sin_verificar"
    return cb.GRUPO.get(item["cb_estado"], "dudoso")


def _pedidos(f):
    """Cuántos correos nuevos pidió el usuario (en "cantidad fija" es la suma de las secciones)."""
    if f.get("modo") == "cantidad" and f.get("secciones"):
        return sum(max(0, int(s.get("valor") or 0)) for s in f["secciones"])
    return int(f.get("cantidad") or 0)


def resumen_borrador(con, bid):
    b = _borrador(con, bid)
    items = [dict(r) for r in con.execute(
        "SELECT i.*, c.seccion FROM borrador_items i LEFT JOIN contactos c ON c.email=i.email "
        "WHERE i.borrador_id=? ORDER BY i.ronda, i.rowid", (bid,))]
    grupos = {"base": 0, "bueno": 0, "malo": 0, "dudoso": 0, "sin_verificar": 0}
    malos, dudosos, motivos_dudosos, desglose = [], [], {}, {}
    catchall = cache = 0
    for it in items:
        g = _grupo(it)
        grupos[g] += 1
        cache += it["cache"] or 0
        if not it["base"]:
            desglose[it["seccion"] or "—"] = desglose.get(it["seccion"] or "—", 0) + 1
        if g in ("malo", "dudoso"):
            fila = {"email": it["email"], "estado": it["cb_estado"], "motivo": it["cb_motivo"] or "",
                    "puntaje": it["cb_puntaje"]}
            (malos if g == "malo" else dudosos).append(fila)
        if g == "dudoso":
            clave = it["cb_motivo"] or it["cb_estado"]
            motivos_dudosos[clave] = motivos_dudosos.get(clave, 0) + 1
            catchall += it["cb_motivo"] == MOTIVO_CATCHALL
    jobs = [dict(r) for r in con.execute("SELECT * FROM cb_jobs WHERE borrador_id=? ORDER BY creado", (bid,))]
    return {
        "id": b["id"], "tipo": b["tipo"], "nombre": b["nombre"], "estado": b["estado"], "fecha": b["fecha"],
        "pedidos": _pedidos(json.loads(b["filtros"] or "{}")) or b["cantidad"],
        "lote_id": b["lote_id"], "error": b["error"], "avisos": json.loads(b["avisos"] or "[]"),
        "total": len(items), "grupos": grupos, "nuevos": len(items) - grupos["base"],
        "a_verificar": grupos["sin_verificar"], "reutilizados": cache,
        "dudosos_catchall": catchall, "motivos_dudosos": motivos_dudosos,
        "desglose": desglose,
        "malos": malos[:LIMITE_LISTA], "dudosos": dudosos[:LIMITE_LISTA],
        "rondas": max((it["ronda"] for it in items), default=1),
        "verificado_alguna_vez": bool(jobs) or cache > 0,
        "jobs": len(jobs),
        "creditos": (_leer_meta(con, "cb_creditos") or {}).get("creditos"),
    }


# =================================================================== verificar
def iniciar_verificacion(con, bid):
    b = _borrador(con, bid)
    if b["estado"] not in ("borrador", "listo"):
        raise ValueError("Este borrador no se puede verificar ahora (ya está verificando o ya se generó).")
    emails = [r[0] for r in con.execute(
        "SELECT email FROM borrador_items WHERE borrador_id=? AND base=0 AND cb_estado IS NULL ORDER BY rowid", (bid,))]
    if not emails:
        raise ValueError("No hay correos pendientes de verificar en este borrador.")
    if cb.modo() == "prueba":
        raise ValueError("Tu API key es de prueba (cb_test_). ClearBounce no permite verificar listas con ella: "
                         "pon tu clave cb_live_ en el archivo .env.")
    trozos = [emails[i:i + cb.MAX_POR_JOB] for i in range(0, len(emails), cb.MAX_POR_JOB)]
    if len(trozos) > cb.MAX_JOBS_SIMULTANEOS:
        raise ValueError(f"Máximo {cb.MAX_POR_JOB * cb.MAX_JOBS_SIMULTANEOS:,} correos por verificación.".replace(",", "."))

    estado = estado_clearbounce(con)
    if estado["creditos"] is not None and estado["creditos"] < len(emails):
        raise ValueError(f"Necesitas {len(emails)} créditos y en ClearBounce tienes {estado['creditos']}. "
                         f"Pide menos correos o recarga créditos.")

    creados = 0
    try:
        for trozo in trozos:
            j = cb.subir(trozo)
            with con:
                con.execute("INSERT INTO cb_jobs(job_id, borrador_id, total, estimado, creado, estado) "
                            "VALUES(?,?,?,?,?,'pending')", (j["job_id"], bid, j["total"], j["estimado"], ahora()))
                con.execute("UPDATE borradores SET estado='verificando', error=NULL WHERE id=?", (bid,))
            creados += 1
    except cb.ErrorClearBounce as e:
        if not creados:
            raise ValueError(str(e)) from None
        with con:
            con.execute("UPDATE borradores SET error=? WHERE id=?",
                        (f"Solo se subió una parte: {e}. Al terminar, pulsa Verificar de nuevo para el resto.", bid))
    return progreso(con, bid, consultar=False)


def _aplicar(con, bid, job_id, resultados):
    """Guarda los resultados de un job y marca los malos como inválidos. Idempotente."""
    db.respaldar("antes-clearbounce")
    t = ahora()
    con.execute("BEGIN IMMEDIATE")
    try:
        job = con.execute("SELECT aplicado FROM cb_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not job or job["aplicado"]:
            con.rollback()
            return
        malos = {}
        for r in resultados:
            email = str(r.get("email") or "").strip().lower()
            if not email:
                continue
            estado = r.get("status") or "unknown"
            motivo = r.get("reason") or r.get("subStatus") or ""
            puntaje = r.get("score")
            con.execute("UPDATE borrador_items SET cb_estado=?, cb_motivo=?, cb_puntaje=?, cache=0 "
                        "WHERE borrador_id=? AND email=? AND base=0", (estado, motivo, puntaje, bid, email))
            con.execute("UPDATE contactos SET cb_estado=?, cb_motivo=?, cb_puntaje=?, cb_fecha=? WHERE email=?",
                        (estado, motivo, puntaje, t, email))
            if estado == "undeliverable":
                malos.setdefault(motivo or "rechazado", []).append(email)
        total_malos = []
        for motivo, emails in malos.items():
            _marcar(con, emails, "invalido", f"ClearBounce: {motivo}")
            total_malos += emails
        if total_malos:
            _crear_lote(con, "marcado:invalido", f"ClearBounce · borrador #{bid}", total_malos, [], None,
                        nota="malos detectados por ClearBounce")
        con.execute("UPDATE cb_jobs SET aplicado=1, estado='completed', progreso=100 WHERE job_id=?", (job_id,))
        con.commit()
    except Exception:
        con.rollback()
        raise


def progreso(con, bid, consultar=True):
    """La página llama aquí cada ~4 s mientras verifica."""
    b = _borrador(con, bid)
    vivo = {"deliverable": 0, "undeliverable": 0, "risky": 0, "unknown": 0}
    procesados_vivo = 0
    if b["estado"] == "verificando" and consultar:
        for job in con.execute("SELECT * FROM cb_jobs WHERE borrador_id=? AND aplicado=0", (bid,)).fetchall():
            try:
                st = cb.estado(job["job_id"])
            except cb.ErrorClearBounce as e:
                if e.status in (429, 500, 502, 503, 504) or e.status is None:
                    continue  # se reintenta en la próxima consulta
                if e.status == 404:
                    with con:
                        con.execute("UPDATE cb_jobs SET aplicado=1, estado='failed' WHERE job_id=?", (job["job_id"],))
                        con.execute("UPDATE borradores SET error=? WHERE id=?", (str(e), bid))
                    continue
                raise ValueError(str(e)) from None
            estado = st.get("status", "processing")
            if estado == "completed":
                try:
                    _aplicar(con, bid, job["job_id"], cb.resultados(job["job_id"]))
                except cb.ErrorClearBounce as e:
                    if e.status not in (400, 429, 500, 502, 503, 504) and e.status is not None:
                        raise ValueError(str(e)) from None
            elif estado == "failed":
                with con:
                    con.execute("UPDATE cb_jobs SET aplicado=1, estado='failed' WHERE job_id=?", (job["job_id"],))
                    con.execute("UPDATE borradores SET error=? WHERE id=?",
                                ("ClearBounce no pudo terminar una parte. Los correos sin resultado siguen "
                                 "'sin verificar': puedes pulsar Verificar otra vez.", bid))
            else:
                with con:
                    con.execute("UPDATE cb_jobs SET estado=?, progreso=? WHERE job_id=?",
                                (estado, int(st.get("progress") or 0), job["job_id"]))
                procesados_vivo += int(st.get("processedEmails") or 0)
                vivo["deliverable"] += int(st.get("deliverableCount") or 0)
                vivo["undeliverable"] += int(st.get("undeliverableCount") or 0)
                vivo["risky"] += int(st.get("riskyCount") or 0)
                vivo["unknown"] += int(st.get("unknownCount") or 0)
        quedan = con.execute("SELECT COUNT(*) FROM cb_jobs WHERE borrador_id=? AND aplicado=0", (bid,)).fetchone()[0]
        if not quedan:
            with con:
                con.execute("UPDATE borradores SET estado='listo' WHERE id=? AND estado='verificando'", (bid,))
            estado_clearbounce(con)  # refresca el saldo de créditos

    res = resumen_borrador(con, bid)
    jobs = [dict(r) for r in con.execute("SELECT * FROM cb_jobs WHERE borrador_id=?", (bid,))]
    abiertos = [j for j in jobs if not j["aplicado"]]
    total = sum(j["total"] or 0 for j in abiertos)
    inicio = min((j["creado"] for j in abiertos), default=None)
    seg = int((datetime.now() - datetime.strptime(inicio, "%Y-%m-%d %H:%M:%S")).total_seconds()) if inicio else 0
    res["verificacion"] = {
        "en_curso": res["estado"] == "verificando",
        "total": total, "procesados": procesados_vivo,
        "porcentaje": int(100 * procesados_vivo / total) if total else (100 if not abiertos else 0),
        "en_vivo": vivo, "segundos": seg,
        "estimado": sum(j["estimado"] or 0 for j in abiertos) or None,
    }
    return res


# =================================================================== reponer
def reponer(con, bid, cantidad):
    """Agrega `cantidad` correos nuevos (mismos filtros, sin repetir) para cubrir los malos."""
    b = _borrador(con, bid)
    if b["estado"] not in ("borrador", "listo"):
        raise ValueError("Solo se puede reponer cuando la verificación terminó.")
    if cantidad <= 0:
        raise ValueError("La cantidad a reponer debe ser mayor que 0.")
    f = json.loads(b["filtros"] or "{}")
    if f.get("modo") == "cantidad":  # en "cantidad fija" la cantidad la da cada sección: aquí se usan como pesos
        f["modo"] = "porcentaje"
    con.execute("BEGIN IMMEDIATE")
    try:
        emails, avisos, _ = seleccionar(con, f, cantidad, excluir_borrador=bid)
        if not emails:
            raise ValueError("Ya no quedan correos disponibles con esos filtros para reponer.")
        ronda = con.execute("SELECT COALESCE(MAX(ronda),1)+1 FROM borrador_items WHERE borrador_id=?",
                            (bid,)).fetchone()[0]
        _agregar_items(con, bid, emails, ronda=ronda)
        con.execute("UPDATE borradores SET cantidad=cantidad+? WHERE id=?", (len(emails), bid))
        avisos.insert(0, f"Reposición: se agregaron {len(emails)} correos nuevos.")
        _sumar_avisos(con, bid, avisos)
        con.commit()
    except Exception:
        con.rollback()
        raise
    return resumen_borrador(con, bid)


# =================================================================== confirmar
def confirmar(con, bid, politica="fuera"):
    """Crea el lote final: base + buenos + sin verificar + (dudosos según la política). Marca como usados."""
    if politica not in POLITICAS:
        raise ValueError("Opción de dudosos no válida.")
    b = _borrador(con, bid)
    if b["estado"] == "verificando":
        raise ValueError("Espera a que termine la verificación.")
    if b["estado"] not in ("borrador", "listo"):
        raise ValueError("Este borrador ya se generó o se descartó.")
    f = json.loads(b["filtros"] or "{}")
    avisos = []
    con.execute("BEGIN IMMEDIATE")
    try:
        items = [dict(r) for r in con.execute("SELECT * FROM borrador_items WHERE borrador_id=? ORDER BY ronda, rowid",
                                              (bid,))]
        base = [it["email"] for it in items if it["base"]]
        incluir, invalidar = [], {}
        for it in items:
            if it["base"]:
                continue
            g = _grupo(it)
            if g in ("bueno", "sin_verificar"):
                incluir.append(it["email"])
            elif g == "dudoso":
                if politica == "incluir" or (politica == "catchall" and it["cb_motivo"] == MOTIVO_CATCHALL):
                    incluir.append(it["email"])
                elif politica == "invalidar":
                    invalidar.setdefault(it["cb_motivo"] or it["cb_estado"], []).append(it["email"])

        for motivo, emails in invalidar.items():
            _marcar(con, emails, "invalido", f"ClearBounce dudoso: {motivo}")

        stats_base = {"registrados": 0}
        if base:
            stats_base = _marcar(con, base, "verificado", "verificado como bueno")
            actuales = _estados_actuales(con, base)
            quitar = {e for e in base if actuales.get(e, ("usado",))[0] in ("invalido", "baja")}
            base = [e for e in base if e not in quitar]

        actuales = _estados_actuales(con, incluir)
        ocupados = [e for e in incluir if actuales.get(e, ("x",))[0] != "disponible"]
        if ocupados:
            avisos.append(f"{len(ocupados)} correos ya no estaban disponibles (se usaron en otro lado) y se quitaron.")
        nuevos = [e for e in incluir if e not in set(ocupados)]
        if not base and not nuevos:
            raise ValueError("No queda ningún correo para el archivo.")

        res = resumen_borrador(con, bid)
        g = res["grupos"]
        partes = []
        if res["verificado_alguna_vez"]:
            partes.append(f"ClearBounce: {g['bueno']} buenos, {g['malo']} malos, {g['dudoso']} dudosos ({politica})")
        if g["sin_verificar"]:
            partes.append(f"{g['sin_verificar']} sin verificar")
        if base:
            partes.insert(0, f"{len(base)} buenos subidos + {len(nuevos)} nuevos")
        lote_id = _crear_lote(con, b["tipo"], b["nombre"], base, nuevos,
                              {**f, "clearbounce": res["verificado_alguna_vez"], "dudosos": politica},
                              nota=" · ".join(partes) or None)
        _marcar_usados(con, nuevos, lote_id)
        buenos_cb = [it["email"] for it in items if not it["base"] and it["cb_estado"] == "deliverable"]
        for parte in _chunks([e for e in buenos_cb if e in set(nuevos)]):
            con.execute(f"UPDATE contactos SET verificado=1 WHERE email IN ({','.join('?' * len(parte))})", parte)
        con.execute("UPDATE borradores SET estado='generado', lote_id=? WHERE id=?", (lote_id, bid))
        con.commit()
    except Exception:
        con.rollback()
        raise
    copia = _guardar_copia(con, lote_id)
    desglose = {}
    for parte in _chunks(nuevos):
        for r in con.execute(f"SELECT seccion, COUNT(*) FROM contactos WHERE email IN "
                             f"({','.join('?' * len(parte))}) GROUP BY seccion", parte):
            desglose[r[0]] = desglose.get(r[0], 0) + r[1]
    return {"lote_id": lote_id, "borrador_id": bid, "total": len(base) + len(nuevos), "base": len(base),
            "nuevos": len(nuevos), "avisos": avisos, "desglose": desglose, "copia": copia,
            "buenos_no_estaban_en_base": stats_base.get("registrados", 0),
            "clearbounce": res["verificado_alguna_vez"]}


# =================================================================== reporte
def reporte_csv(con, bid):
    b = _borrador(con, bid)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["EMAIL", "RESULTADO", "ESTADO_CLEARBOUNCE", "MOTIVO", "PUNTAJE", "ORIGEN", "RONDA", "SECCION"])
    nombres = {"bueno": "BUENO", "malo": "MALO", "dudoso": "DUDOSO", "sin_verificar": "SIN VERIFICAR",
               "base": "BUENO (archivo subido)"}
    for r in con.execute("SELECT i.*, c.seccion FROM borrador_items i LEFT JOIN contactos c ON c.email=i.email "
                         "WHERE i.borrador_id=? ORDER BY i.rowid", (bid,)):
        it = dict(r)
        w.writerow([it["email"], nombres[_grupo(it)], it["cb_estado"] or "", it["cb_motivo"] or "",
                    "" if it["cb_puntaje"] is None else it["cb_puntaje"],
                    "archivo subido" if it["base"] else ("verificación anterior" if it["cache"] else "base"),
                    it["ronda"], it["seccion"] or ""])
    return buf.getvalue().encode("utf-8-sig"), f"verificacion_borrador{b['id']}.csv"
