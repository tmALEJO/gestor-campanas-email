"""Toda la lógica de negocio. La página (app.py) y el script limpiar.py llaman a estas funciones."""
import csv
import io
import json
import re

from . import archivos as A
from . import correos as C
from .config import EXPORT_DIR, SECCION_EXTERNA, listar_excels
from .db import ahora

ESTADOS = ("disponible", "usado", "invalido", "baja")
# Un estado "más fuerte" nunca se rebaja automáticamente (solo a mano desde Buscar)
PRIORIDAD = {"disponible": 0, "usado": 1, "invalido": 2, "baja": 3}
LOTE_ANULABLE = ("generado", "completado")


def _chunks(lista, n=500):
    for i in range(0, len(lista), n):
        yield lista[i:i + n]


def _estados_actuales(con, emails):
    res = {}
    for parte in _chunks(list(emails)):
        q = f"SELECT email, estado, verificado FROM contactos WHERE email IN ({','.join('?' * len(parte))})"
        for r in con.execute(q, parte):
            res[r["email"]] = (r["estado"], r["verificado"])
    return res


def _guardar_meta(con, clave, valor):
    con.execute("INSERT INTO meta(clave, valor) VALUES(?, ?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
                (clave, json.dumps(valor, ensure_ascii=False)))


def _leer_meta(con, clave):
    r = con.execute("SELECT valor FROM meta WHERE clave=?", (clave,)).fetchone()
    return json.loads(r["valor"]) if r else None


def _slug(texto):
    t = C.sin_tildes(texto or "").lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40]


# =================================================================== importar Excel
def importar_excel(con):
    rutas = listar_excels()
    if not rutas:
        raise ValueError("No hay ningún .xlsx dentro de la carpeta data/. Copia ahí BDD_NARIÑOTEX.xlsx.")
    registros, invalidos, rep = A.procesar_excel(rutas)
    t = ahora()
    existentes = {r[0] for r in con.execute("SELECT email FROM contactos")}
    with con:
        # Si el correo ya existe se actualizan sus datos, PERO su estado se respeta
        con.executemany(
            """INSERT INTO contactos(email, seccion, pais, ciudad, empresa, contacto, dominio, proveedor,
                                     generico, estado, creado, actualizado)
               VALUES(?,?,?,?,?,?,?,?,?,'disponible',?,?)
               ON CONFLICT(email) DO UPDATE SET
                 seccion=excluded.seccion, pais=excluded.pais, ciudad=excluded.ciudad,
                 empresa=excluded.empresa, contacto=excluded.contacto, dominio=excluded.dominio,
                 proveedor=excluded.proveedor, generico=excluded.generico, actualizado=excluded.actualizado""",
            [(e, r["seccion"], r["pais"], r["ciudad"], r["empresa"], r["contacto"], r["dominio"],
              r["proveedor"], r["generico"], t, t) for e, r in registros.items()],
        )
        rep["nuevos_en_base"] = sum(1 for e in registros if e not in existentes)
        rep["ya_existian"] = len(registros) - rep["nuevos_en_base"]
        rep["fecha"] = t
        _guardar_meta(con, "ultima_importacion", rep)

    ruta_inv = EXPORT_DIR / "reporte_limpieza_invalidos.csv"
    with open(ruta_inv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["email", "motivo", "seccion"])
        w.writeheader()
        w.writerows(invalidos)
    rep["reporte_invalidos"] = str(ruta_inv.name)
    return rep


def verificar_mx(con, hilos=25):
    """Opcional: marca como inválidos los correos cuyo dominio no tiene servidor de correo."""
    try:
        import dns.resolver
        import dns.exception
    except ImportError as e:
        raise RuntimeError("Falta dnspython:  pip install dnspython") from e
    from concurrent.futures import ThreadPoolExecutor

    dominios = [r[0] for r in con.execute(
        "SELECT DISTINCT dominio FROM contactos WHERE estado='disponible' AND proveedor=?", (C.OTROS,))]

    def revisar(d):
        try:
            dns.resolver.resolve(d, "MX", lifetime=6)
            return d, 1
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            try:
                dns.resolver.resolve(d, "A", lifetime=6)
                return d, 1
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
                return d, 0
            except dns.exception.DNSException:
                return d, None
        except dns.exception.DNSException:
            return d, None

    with ThreadPoolExecutor(hilos) as ex:
        resultados = list(ex.map(revisar, dominios))
    sin_mx = [d for d, ok in resultados if ok == 0]
    t = ahora()
    with con:
        con.executemany("INSERT OR REPLACE INTO dominios VALUES(?,?,?)", [(d, ok, t) for d, ok in resultados if ok is not None])
        afectados = 0
        for parte in _chunks(sin_mx):
            cur = con.execute(
                f"UPDATE contactos SET estado='invalido', motivo='dominio sin servidor de correo (MX)', actualizado=? "
                f"WHERE estado='disponible' AND dominio IN ({','.join('?' * len(parte))})", [t, *parte])
            afectados += cur.rowcount
    return {"dominios_revisados": len(dominios), "sin_mx": len(sin_mx),
            "sin_respuesta": sum(1 for _, ok in resultados if ok is None), "correos_marcados": afectados}


# =================================================================== consultas
def _agrupar(con, campo, orden="total DESC"):
    q = f"""SELECT {campo} AS nombre,
                   SUM(estado='disponible') AS disponible, SUM(estado='usado') AS usado,
                   SUM(estado='invalido') AS invalido, SUM(estado='baja') AS baja,
                   SUM(verificado) AS verificado, COUNT(*) AS total
            FROM contactos GROUP BY {campo} ORDER BY {orden}"""
    return [dict(r) for r in con.execute(q)]


def resumen(con):
    estados = {e: 0 for e in ESTADOS}
    estados.update({r[0]: r[1] for r in con.execute("SELECT estado, COUNT(*) FROM contactos GROUP BY estado")})
    return {
        "total": sum(estados.values()),
        "estados": estados,
        "verificados": con.execute("SELECT COUNT(*) FROM contactos WHERE verificado=1").fetchone()[0],
        "genericos_disponibles": con.execute(
            "SELECT COUNT(*) FROM contactos WHERE generico=1 AND estado='disponible'").fetchone()[0],
        "por_seccion": _agrupar(con, "seccion"),
        "por_pais": _agrupar(con, "pais"),
        "por_proveedor": _agrupar(con, "proveedor"),
        "top_dominios": [dict(r) for r in con.execute(
            "SELECT dominio AS nombre, COUNT(*) AS disponible FROM contactos WHERE estado='disponible' "
            "GROUP BY dominio ORDER BY 2 DESC LIMIT 12")],
        "lotes": con.execute("SELECT COUNT(*) FROM lotes WHERE tipo IN ('generado','completado') AND anulado=0").fetchone()[0],
        "ultima_importacion": _leer_meta(con, "ultima_importacion"),
    }


def opciones(con):
    def lista(campo):
        return [dict(r) for r in con.execute(
            f"SELECT {campo} AS nombre, SUM(estado='disponible') AS disponible, COUNT(*) AS total "
            f"FROM contactos GROUP BY {campo} ORDER BY disponible DESC")]
    return {"secciones": lista("seccion"), "paises": lista("pais"), "proveedores": lista("proveedor")}


def _where(f):
    cond, params = ["estado='disponible'"], []
    for campo, clave in (("pais", "paises"), ("proveedor", "proveedores")):
        valores = [v for v in (f.get(clave) or []) if v]
        if valores:
            cond.append(f"{campo} IN ({','.join('?' * len(valores))})")
            params += valores
    if f.get("excluir_genericos"):
        cond.append("generico=0")
    if f.get("solo_verificados"):
        cond.append("verificado=1")
    return " AND ".join(cond), params


def contar(con, f):
    where, params = _where(f)
    por_seccion = {r[0]: r[1] for r in con.execute(
        f"SELECT seccion, COUNT(*) FROM contactos WHERE {where} GROUP BY seccion", params)}
    elegidas = [s["nombre"] for s in (f.get("secciones") or [])]
    total = sum(v for k, v in por_seccion.items() if not elegidas or k in elegidas)
    return {"total": total, "por_seccion": por_seccion}


# =================================================================== selección al azar
def repartir(total, pesos, disponibles, rellenar=True):
    """Reparte `total` entre secciones según `pesos` sin pasarse de lo disponible."""
    suma = sum(pesos.values())
    if suma <= 0:
        pesos = {k: 1 for k in pesos}
        suma = len(pesos)
    exactas = {k: total * p / suma for k, p in pesos.items()}
    cuotas = {k: int(v) for k, v in exactas.items()}
    resto = total - sum(cuotas.values())
    for k in sorted(exactas, key=lambda k: exactas[k] - cuotas[k], reverse=True)[:resto]:
        cuotas[k] += 1
    faltante = 0
    for k in cuotas:
        d = disponibles.get(k, 0)
        if cuotas[k] > d:
            faltante += cuotas[k] - d
            cuotas[k] = d
    if rellenar and faltante:
        orden = sorted(pesos, key=lambda k: pesos[k], reverse=True)
        while faltante:
            dio = False
            for k in orden:
                if faltante and cuotas[k] < disponibles.get(k, 0):
                    cuotas[k] += 1
                    faltante -= 1
                    dio = True
            if not dio:
                break
    return cuotas, faltante


def seleccionar(con, f, cantidad):
    """Devuelve (emails elegidos al azar, avisos, desglose por sección). No modifica nada."""
    where, params = _where(f)
    modo = f.get("modo") or "azar"
    secciones = [s for s in (f.get("secciones") or []) if s.get("nombre")]
    nombres = [s["nombre"] for s in secciones]
    avisos = []

    if modo == "cantidad" and secciones:
        cantidad = sum(max(0, int(s.get("valor") or 0)) for s in secciones)
    if cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor que 0.")

    if modo == "azar" or not secciones:
        q = f"SELECT email FROM contactos WHERE {where}"
        p = list(params)
        if nombres:
            q += f" AND seccion IN ({','.join('?' * len(nombres))})"
            p += nombres
        emails = [r[0] for r in con.execute(q + " ORDER BY RANDOM() LIMIT ?", p + [cantidad])]
    else:
        disp = {r[0]: r[1] for r in con.execute(
            f"SELECT seccion, COUNT(*) FROM contactos WHERE {where} GROUP BY seccion", params)}
        if modo == "porcentaje":
            pesos = {s["nombre"]: max(0.0, float(s.get("valor") or 0)) for s in secciones}
            cuotas, _ = repartir(cantidad, pesos, disp, bool(f.get("rellenar", True)))
        else:  # cantidad fija por sección
            cuotas = {}
            for s in secciones:
                pedido = max(0, int(s.get("valor") or 0))
                cuotas[s["nombre"]] = min(pedido, disp.get(s["nombre"], 0))
                if pedido > cuotas[s["nombre"]]:
                    avisos.append(f"{s['nombre']}: pediste {pedido} pero solo hay {cuotas[s['nombre']]} disponibles.")
        emails = []
        for nombre, c in cuotas.items():
            if c > 0:
                emails += [r[0] for r in con.execute(
                    f"SELECT email FROM contactos WHERE {where} AND seccion=? ORDER BY RANDOM() LIMIT ?",
                    params + [nombre, c])]

    if len(emails) < cantidad:
        avisos.append(f"Pediste {cantidad} pero con esos filtros solo había {len(emails)} disponibles.")
    desglose = {}
    for parte in _chunks(emails):
        for r in con.execute(
                f"SELECT seccion, COUNT(*) FROM contactos WHERE email IN ({','.join('?' * len(parte))}) GROUP BY seccion", parte):
            desglose[r[0]] = desglose.get(r[0], 0) + r[1]
    return emails, avisos, desglose


def _crear_lote(con, tipo, nombre, base, nuevos, filtros, nota=None):
    cur = con.execute(
        "INSERT INTO lotes(fecha, tipo, nombre, cantidad, nuevos, filtros, nota) VALUES(?,?,?,?,?,?,?)",
        (ahora(), tipo, nombre or "", len(base) + len(nuevos), len(nuevos),
         json.dumps(filtros, ensure_ascii=False) if filtros is not None else None, nota))
    lote_id = cur.lastrowid
    con.executemany("INSERT OR IGNORE INTO lote_items(lote_id, email, nuevo) VALUES(?,?,0)", [(lote_id, e) for e in base])
    con.executemany("INSERT OR IGNORE INTO lote_items(lote_id, email, nuevo) VALUES(?,?,1)", [(lote_id, e) for e in nuevos])
    return lote_id


def _marcar_usados(con, emails, lote_id):
    t = ahora()
    con.executemany("UPDATE contactos SET estado='usado', lote_id=?, actualizado=? WHERE email=? AND estado='disponible'",
                    [(lote_id, t, e) for e in emails])


def _guardar_copia(con, lote_id):
    contenido, _ = A.construir_salida(_filas_lote(con, lote_id), "csv", False)
    lote = con.execute("SELECT * FROM lotes WHERE id=?", (lote_id,)).fetchone()
    nombre = _nombre_archivo(lote, "csv")
    (EXPORT_DIR / nombre).write_bytes(contenido)
    return nombre


def generar(con, f, cantidad, nombre=""):
    con.execute("BEGIN IMMEDIATE")
    try:
        emails, avisos, desglose = seleccionar(con, f, cantidad)
        if not emails:
            raise ValueError("No hay correos disponibles con esos filtros.")
        lote_id = _crear_lote(con, "generado", nombre, [], emails, {**f, "cantidad": cantidad})
        _marcar_usados(con, emails, lote_id)
        con.commit()
    except Exception:
        con.rollback()
        raise
    copia = _guardar_copia(con, lote_id)
    return {"lote_id": lote_id, "total": len(emails), "nuevos": len(emails), "base": 0,
            "avisos": avisos, "desglose": desglose, "copia": copia}


def completar(con, archivos, cantidad, f, nombre=""):
    """Sube el archivo de BUENOS, los marca verificados y agrega `cantidad` nuevos al azar."""
    buenos, _, _ = A.emails_de_archivos(archivos)
    if not buenos:
        raise ValueError("No encontré correos en el archivo de buenos.")
    avisos = []
    con.execute("BEGIN IMMEDIATE")
    try:
        stats = _marcar(con, buenos, "verificado", "verificado como bueno")
        actuales = _estados_actuales(con, buenos)
        descartados = [e for e in buenos if actuales.get(e, ("usado",))[0] in ("invalido", "baja")]
        if descartados:
            avisos.append(f"{len(descartados)} correos del archivo están marcados como inválidos o baja y se quitaron.")
        base = [e for e in buenos if e not in set(descartados)]
        nuevos, av, desglose = seleccionar(con, f, cantidad) if cantidad > 0 else ([], [], {})
        avisos += av
        lote_id = _crear_lote(con, "completado", nombre, base, nuevos, {**f, "cantidad": cantidad},
                              nota=f"{len(base)} buenos subidos + {len(nuevos)} nuevos")
        _marcar_usados(con, nuevos, lote_id)
        con.commit()
    except Exception:
        con.rollback()
        raise
    copia = _guardar_copia(con, lote_id)
    return {"lote_id": lote_id, "total": len(base) + len(nuevos), "base": len(base), "nuevos": len(nuevos),
            "avisos": avisos, "desglose": desglose, "copia": copia,
            "buenos_no_estaban_en_base": stats["registrados"]}


# =================================================================== marcar estados
def _marcar(con, emails, estado, motivo=""):
    """Aplica un estado respetando la prioridad. No hace commit."""
    t = ahora()
    actuales = _estados_actuales(con, emails)
    st = {"recibidos": len(emails), "actualizados": 0, "ya_estaban": 0, "conservados": 0, "registrados": 0}
    for e in emails:
        actual = actuales.get(e)
        if actual is None:  # no estaba en la base: se registra para que nunca se vuelva a escoger
            inf = C.info(e)
            est = "usado" if estado == "verificado" else estado
            con.execute(
                """INSERT OR IGNORE INTO contactos(email, seccion, pais, dominio, proveedor, generico, estado, motivo,
                                                   verificado, creado, actualizado) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (e, SECCION_EXTERNA, "Sin país", inf["dominio"], inf["proveedor"], inf["generico"], est, motivo,
                 int(estado == "verificado"), t, t))
            st["registrados"] += 1
            continue
        est_actual, verif = actual
        if estado == "verificado":
            if est_actual in ("invalido", "baja"):
                st["conservados"] += 1
            elif verif and est_actual == "usado":
                st["ya_estaban"] += 1
            else:
                con.execute("UPDATE contactos SET verificado=1, estado='usado', actualizado=? WHERE email=?", (t, e))
                st["actualizados"] += 1
        elif est_actual == estado:
            st["ya_estaban"] += 1
        elif PRIORIDAD[estado] > PRIORIDAD[est_actual]:
            con.execute("UPDATE contactos SET estado=?, motivo=?, verificado=CASE WHEN ? IN ('invalido','baja') THEN 0 "
                        "ELSE verificado END, actualizado=? WHERE email=?", (estado, motivo, estado, t, e))
            st["actualizados"] += 1
        else:
            st["conservados"] += 1
    return st


def previsualizar_marcado(con, archivos, palabra=""):
    emails, filas, filas_ok = A.emails_de_archivos(archivos, palabra)
    actuales = _estados_actuales(con, emails)
    por_estado = {}
    for e in emails:
        k = actuales[e][0] if e in actuales else "no está en la base"
        por_estado[k] = por_estado.get(k, 0) + 1
    return {"filas_con_correo": filas, "filas_tomadas": filas_ok, "correos": len(emails),
            "por_estado_actual": por_estado, "muestra": emails[:15]}


def marcar_desde_archivos(con, archivos, estado, palabra="", motivo=""):
    if estado not in ("usado", "invalido", "baja", "verificado"):
        raise ValueError("Estado no válido.")
    emails, _, _ = A.emails_de_archivos(archivos, palabra)
    if not emails:
        raise ValueError("No encontré correos en los archivos (revisa el filtro de palabra).")
    motivo = motivo or {"usado": "subido como ya utilizado", "invalido": "reportado por verificador/rebote",
                        "baja": "baja / desuscrito", "verificado": "verificado como bueno"}[estado]
    with con:
        st = _marcar(con, emails, estado, motivo)
        nombres = ", ".join(n for n, _ in archivos)
        _crear_lote(con, f"marcado:{estado}", nombres[:120], emails, [], None, nota=motivo)
    return st


def importar_estado(con, archivos):
    """Lee un CSV exportado desde 'Exportar estado' (de tu compañero) y aplica los estados."""
    grupos = {"usado": [], "invalido": [], "baja": [], "verificado": []}
    for nombre, contenido in archivos:
        filas = A.leer_filas(nombre, contenido)
        if not filas:
            continue
        cab = [C.norm_clave(c) for c in filas[0]]
        try:
            ie, iest = cab.index("EMAIL"), cab.index("ESTADO")
        except ValueError as e:
            raise ValueError(f"'{nombre}' no tiene columnas EMAIL y ESTADO (usa el archivo de 'Exportar estado').") from e
        iv = cab.index("VERIFICADO") if "VERIFICADO" in cab else None
        for fila in filas[1:]:
            if len(fila) <= max(ie, iest):
                continue
            ems = C.extraer(fila[ie])
            est = fila[iest].strip().lower()
            if ems and est in grupos:
                grupos[est].append(ems[0])
            if ems and iv is not None and len(fila) > iv and fila[iv].strip() == "1":
                grupos["verificado"].append(ems[0])
    total = {}
    with con:
        for est in ("usado", "verificado", "invalido", "baja"):  # de menor a mayor prioridad
            if grupos[est]:
                total[est] = _marcar(con, list(dict.fromkeys(grupos[est])), est, "importado de otro equipo")
    return total


def cambiar_estado_manual(con, email, estado):
    if estado not in ESTADOS:
        raise ValueError("Estado no válido.")
    with con:
        cur = con.execute(
            "UPDATE contactos SET estado=?, motivo='cambio manual', actualizado=?, "
            "lote_id=CASE WHEN ?='disponible' THEN NULL ELSE lote_id END, "
            "verificado=CASE WHEN ? IN ('disponible','invalido','baja') THEN 0 ELSE verificado END WHERE email=?",
            (estado, ahora(), estado, estado, email.strip().lower()))
    if not cur.rowcount:
        raise ValueError("Ese correo no está en la base.")
    return {"ok": True}


def buscar(con, q, limite=100):
    q = (q or "").strip().lower()
    if len(q) < 3:
        return []
    return [dict(r) for r in con.execute(
        "SELECT email, seccion, pais, ciudad, empresa, proveedor, estado, motivo, verificado, lote_id, actualizado "
        "FROM contactos WHERE email LIKE ? OR lower(empresa) LIKE ? ORDER BY email LIMIT ?",
        (f"%{q}%", f"%{q}%", limite))]


# =================================================================== lotes
def lotes(con):
    filas = []
    for r in con.execute("SELECT * FROM lotes ORDER BY id DESC LIMIT 300"):
        d = dict(r)
        d["filtros"] = json.loads(d["filtros"]) if d["filtros"] else None
        filas.append(d)
    return filas


def anular_lote(con, lote_id):
    lote = con.execute("SELECT * FROM lotes WHERE id=?", (lote_id,)).fetchone()
    if not lote:
        raise ValueError("Lote no encontrado.")
    if lote["tipo"] not in LOTE_ANULABLE:
        raise ValueError("Solo se pueden anular lotes generados o completados.")
    if lote["anulado"]:
        raise ValueError("Ese lote ya estaba anulado.")
    with con:
        cur = con.execute(
            """UPDATE contactos SET estado='disponible', lote_id=NULL, actualizado=?
               WHERE lote_id=? AND estado='usado' AND verificado=0
                 AND email IN (SELECT email FROM lote_items WHERE lote_id=? AND nuevo=1)""",
            (ahora(), lote_id, lote_id))
        con.execute("UPDATE lotes SET anulado=1 WHERE id=?", (lote_id,))
    return {"liberados": cur.rowcount}


def _filas_lote(con, lote_id, solo_nuevos=False):
    q = """SELECT c.email, c.contacto, c.empresa, c.seccion, c.pais, c.ciudad
           FROM lote_items i JOIN contactos c ON c.email = i.email
           WHERE i.lote_id=? AND c.estado NOT IN ('invalido','baja')"""
    if solo_nuevos:
        q += " AND i.nuevo=1"
    return [dict(r) for r in con.execute(q + " ORDER BY i.nuevo, i.rowid", (lote_id,))]


def _nombre_archivo(lote, ext):
    fecha = (lote["fecha"] or "")[:10]
    nombre = _slug(lote["nombre"]) or lote["tipo"]
    return f"{fecha}_lote{lote['id']}_{nombre}_{lote['cantidad']}.{ext}"


def archivo_lote(con, lote_id, formato="csv", extras=False, solo_nuevos=False):
    lote = con.execute("SELECT * FROM lotes WHERE id=?", (lote_id,)).fetchone()
    if not lote:
        raise ValueError("Lote no encontrado.")
    formato = "xlsx" if formato == "xlsx" else "csv"
    contenido, mime = A.construir_salida(_filas_lote(con, lote_id, solo_nuevos), formato, extras)
    return contenido, mime, _nombre_archivo(lote, formato)


def exportar_estado(con, estado="todos"):
    q = "SELECT email, estado, verificado, motivo, seccion, pais, lote_id, actualizado FROM contactos"
    params = []
    if estado == "todos":
        q += " WHERE estado != 'disponible' OR verificado=1"
    elif estado in ESTADOS:
        q += " WHERE estado=?"
        params.append(estado)
    elif estado == "verificado":
        q += " WHERE verificado=1"
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["EMAIL", "ESTADO", "VERIFICADO", "MOTIVO", "SECCION", "PAIS", "LOTE", "ACTUALIZADO"])
    for r in con.execute(q + " ORDER BY estado, email", params):
        w.writerow(list(r))
    return buf.getvalue().encode("utf-8-sig")
