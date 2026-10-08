"""Lectura del Excel base, lectura de archivos subidos y escritura de archivos para Brevo."""
import csv
import io
import re
from pathlib import Path

from openpyxl import Workbook, load_workbook

from . import correos as C
from .config import HOJAS_IGNORADAS

# Palabras clave para reconocer columnas (encabezado normalizado contiene...)
COLUMNAS = {
    "email": ("CORREO", "EMAIL", "E-MAIL", "MAIL"),
    "pais": ("PAIS",),
    "ciudad": ("CIUDAD", "MUNICIPIO", "PROVINCIA"),
    "empresa": ("EMPRESA", "RAZON SOCIAL", "NEGOCIO", "ESTABLECIMIENTO"),
    "contacto": ("CONTACTO", "REPRESENTANTE", "PROPIETARIO"),
    "sector": ("SECTOR",),
}
ALIAS_PAIS = {"COL": "COLOMBIA", "CO": "COLOMBIA", "ECU": "ECUADOR", "EC": "ECUADOR", "PE": "PERU"}


def limpiar_nombre_hoja(nombre: str) -> str:
    """Quita emojis/iconos del inicio del nombre de la hoja."""
    limpio = re.sub(r"^[^\w]+", "", str(nombre)).strip()
    return re.sub(r"\s+", " ", limpio) or str(nombre).strip()


def norm_pais(valor) -> str:
    t = C.norm_clave(valor)
    if t in ("", "NAN", "NONE", "-", "N/A", "NA", "0"):
        return "Sin país"
    t = ALIAS_PAIS.get(t, t)
    return t.title()


def _texto(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


def _detectar_encabezado(filas):
    """Busca en las primeras 15 filas la que tenga una columna de correo."""
    for i, fila in enumerate(filas[:15]):
        claves = [C.norm_clave(v) for v in fila]
        if any(any(k in c for k in COLUMNAS["email"]) for c in claves):
            mapa = {}
            for campo, palabras in COLUMNAS.items():
                for j, c in enumerate(claves):
                    if c and any(p in c for p in palabras) and j not in mapa.values():
                        # "Nombre Contacto" no debe confundirse con empresa y viceversa
                        if campo == "empresa" and "CONTACTO" in c:
                            continue
                        mapa[campo] = j
                        break
            return i, mapa
    return None, None


def procesar_excel(rutas):
    """
    Lee todas las hojas (menos Resumen) de los Excel dados.
    Devuelve (registros: dict email -> datos, invalidos: list, reporte: dict)
    """
    registros, invalidos = {}, []
    rep = {"archivos": [], "hojas": [], "hojas_omitidas": [], "filas": 0, "celdas_vacias": 0,
           "correos_encontrados": 0, "validos_unicos": 0, "invalidos": 0,
           "duplicados": 0, "corregidos": 0}

    for ruta in rutas:
        rep["archivos"].append(Path(ruta).name)
        wb = load_workbook(ruta, read_only=True, data_only=True)
        for ws in wb.worksheets:
            seccion = limpiar_nombre_hoja(ws.title)
            if C.norm_clave(seccion) in HOJAS_IGNORADAS:
                continue
            filas = [list(r) for r in ws.iter_rows(values_only=True)]
            idx, mapa = _detectar_encabezado(filas)
            if idx is None:
                rep["hojas_omitidas"].append(seccion)
                continue
            n_hoja = 0
            for fila in filas[idx + 1:]:
                def col(campo):
                    j = mapa.get(campo)
                    return _texto(fila[j]) if j is not None and j < len(fila) else ""
                crudo = col("email")
                if not any(v not in (None, "") for v in fila):
                    continue
                rep["filas"] += 1
                if not crudo:
                    rep["celdas_vacias"] += 1
                    continue
                encontrados = C.extraer(crudo)
                if not encontrados:
                    invalidos.append({"email": crudo, "motivo": "no parece un correo", "seccion": seccion})
                    continue
                for e in encontrados:
                    rep["correos_encontrados"] += 1
                    e, corregido = C.corregir_dominio(e)
                    ok, motivo = C.validar(e)
                    if not ok:
                        invalidos.append({"email": e, "motivo": motivo, "seccion": seccion})
                        continue
                    rep["corregidos"] += corregido
                    if e in registros:
                        rep["duplicados"] += 1
                        continue
                    n_hoja += 1
                    registros[e] = {
                        "seccion": seccion, "pais": norm_pais(col("pais")), "ciudad": col("ciudad"),
                        "empresa": col("empresa"), "contacto": col("contacto"), **C.info(e),
                    }
            rep["hojas"].append({"seccion": seccion, "validos": n_hoja})
        wb.close()

    rep["validos_unicos"] = len(registros)
    rep["invalidos"] = len(invalidos)
    return registros, invalidos, rep


# ---------------------------------------------------------------- archivos subidos
def _decodificar(contenido: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return contenido.decode(enc)
        except UnicodeDecodeError:
            continue
    return contenido.decode("utf-8", errors="ignore")


def leer_filas(nombre: str, contenido: bytes):
    """Devuelve una lista de filas (lista de textos) de un .csv/.txt/.xlsx subido."""
    ext = Path(nombre).suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        wb = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
        filas = [[_texto(v) for v in r] for ws in wb.worksheets for r in ws.iter_rows(values_only=True)]
        wb.close()
        return filas
    if ext == ".xls":
        raise ValueError(f"'{nombre}' es .xls antiguo: ábrelo en Excel y guárdalo como .xlsx o .csv")
    texto = _decodificar(contenido)
    if ext == ".csv":
        muestra = texto[:5000]
        try:
            dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
            delim = dialecto.delimiter
        except csv.Error:
            primera = muestra.splitlines()[0] if muestra else ""
            delim = max(",;\t|", key=primera.count)
        return [r for r in csv.reader(io.StringIO(texto), delimiter=delim)]
    return [[linea] for linea in texto.splitlines()]


def emails_de_archivos(archivos, palabra: str = ""):
    """
    archivos: lista de (nombre, bytes).
    palabra: si se indica, solo se toman las filas que contengan esa palabra completa
             (útil cuando el verificador devuelve todos los correos con una columna de estado).
    """
    patron = None
    if palabra and palabra.strip():
        patron = re.compile(r"(?<![a-z])" + re.escape(C.sin_tildes(palabra.strip().lower())) + r"(?![a-z])")
    vistos, emails = set(), []
    filas_total = filas_ok = 0
    for nombre, contenido in archivos:
        for fila in leer_filas(nombre, contenido):
            texto = " | ".join(fila)
            encontrados = C.extraer(texto)
            if not encontrados:
                continue
            filas_total += 1
            if patron:
                resto = C.sin_tildes(C.EXTRAER_RE.sub(" ", C.preparar_texto(texto)))
                if not patron.search(resto):
                    continue
            filas_ok += 1
            for e in encontrados:
                if e not in vistos:
                    vistos.add(e)
                    emails.append(e)
    return emails, filas_total, filas_ok


# ---------------------------------------------------------------- salida para Brevo
def construir_salida(filas, formato: str, extras: bool):
    """filas: lista de dicts con email, contacto, empresa, seccion, pais, ciudad."""
    cab = ["EMAIL"] + (["NOMBRE", "EMPRESA", "SECCION", "PAIS", "CIUDAD"] if extras else [])
    datos = [[f["email"]] + ([f["contacto"] or "", f["empresa"] or "", f["seccion"] or "",
                              f["pais"] or "", f["ciudad"] or ""] if extras else []) for f in filas]
    if formato == "xlsx":
        wb = Workbook()
        ws = wb.active
        ws.title = "Brevo"
        ws.append(cab)
        for d in datos:
            ws.append(d)
        ws.column_dimensions["A"].width = 40
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cab)
    w.writerows(datos)
    # UTF-8 sin BOM: es lo que Brevo lee sin problemas
    return buf.getvalue().encode("utf-8"), "text/csv"
