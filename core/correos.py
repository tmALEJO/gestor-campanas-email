"""Normalización y validación de correos (sin tocar la red)."""
import re
import unicodedata

# Busca correos dentro de cualquier texto (celdas con varios correos, archivos del verificador, etc.)
EXTRAER_RE = re.compile(
    r"(?<![\w.%+\-])([a-z0-9._%+\-]+@(?:[a-z0-9\-]+\.)+[a-z]{2,24})(?![a-z0-9\-])"
)

# Formato aceptado (práctico, no el RFC completo que nadie usa en la vida real)
FORMATO_RE = re.compile(
    r"^(?!.*\.\.)[a-z0-9](?:[a-z0-9._%+\-]{0,62}[a-z0-9_\-])?"
    r"@(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$"
)

# Errores de digitación frecuentes en el dominio
TYPOS = {
    "gmial.com": "gmail.com", "gmai.com": "gmail.com", "gmail.co": "gmail.com",
    "gmail.con": "gmail.com", "gmail.cm": "gmail.com", "gmail.om": "gmail.com",
    "gamil.com": "gmail.com", "gmal.com": "gmail.com", "gnail.com": "gmail.com",
    "gmaill.com": "gmail.com", "gmail.comm": "gmail.com", "gmail.cmo": "gmail.com",
    "gmeil.com": "gmail.com", "gimail.com": "gmail.com",
    "hotmial.com": "hotmail.com", "hotmal.com": "hotmail.com", "hotmai.com": "hotmail.com",
    "hotmail.co": "hotmail.com", "hotmail.con": "hotmail.com", "hotmil.com": "hotmail.com",
    "hotamil.com": "hotmail.com", "homail.com": "hotmail.com", "hotmail.cm": "hotmail.com",
    "hotmaill.com": "hotmail.com", "hormail.com": "hotmail.com", "htmail.com": "hotmail.com",
    "yaho.com": "yahoo.com", "yahoo.con": "yahoo.com", "yahoo.cm": "yahoo.com",
    "yhoo.com": "yahoo.com", "yahooo.com": "yahoo.com", "yahho.com": "yahoo.com",
    "outlok.com": "outlook.com", "outlook.co": "outlook.com", "outlook.con": "outlook.com",
    "otlook.com": "outlook.com", "outllok.com": "outlook.com",
}

BASURA_LOCAL = {
    "no", "na", "n.a", "nn", "ninguno", "ninguna", "notiene", "notengo", "sincorreo",
    "noaplica", "noregistra", "correo", "email", "mail", "test", "prueba", "xxx", "xx",
    "x", "abc", "asd", "asdf", "qwerty", "noreply", "no-reply", "donotreply",
    "do-not-reply", "nombre", "usuario", "sinmail", "nomail",
}
BASURA_CONTIENE = ("notiene", "sincorreo", "noregistra", "noaplica", "notengo", "noreply", "no-reply")
BASURA_DOMINIOS = {
    "correo.com", "email.com", "ejemplo.com", "example.com", "test.com", "notiene.com",
    "sincorreo.com", "xxx.com", "dominio.com", "mail.com.co", "prueba.com", "noaplica.com",
}
DESECHABLES = {
    "mailinator.com", "yopmail.com", "tempmail.com", "10minutemail.com", "guerrillamail.com",
    "trashmail.com", "sharklasers.com", "getnada.com", "dispostable.com", "temp-mail.org",
    "maildrop.cc", "throwawaymail.com", "fakeinbox.com", "emailondeck.com",
}
GENERICOS = {
    "info", "informacion", "contacto", "contact", "ventas", "venta", "admin", "administracion",
    "administrativo", "gerencia", "gerente", "facturacion", "factura", "facturas",
    "facturaelectronica", "contabilidad", "recepcion", "soporte", "servicio", "servicioalcliente",
    "comercial", "compras", "rrhh", "talentohumano", "marketing", "mercadeo", "pedidos", "hola",
    "tesoreria", "cartera", "notificaciones", "office", "oficina", "sistemas", "juridica",
}

PROVEEDORES_EXACTOS = {
    "gmail.com": "Gmail", "googlemail.com": "Gmail",
    "msn.com": "Live/MSN", "icloud.com": "iCloud", "me.com": "iCloud", "mac.com": "iCloud",
    "aol.com": "AOL", "protonmail.com": "Proton", "proton.me": "Proton",
    "ymail.com": "Yahoo", "rocketmail.com": "Yahoo",
}
PROVEEDORES_PREFIJO = {"yahoo": "Yahoo", "hotmail": "Hotmail", "outlook": "Outlook", "live": "Live/MSN"}
OTROS = "Corporativo / otros"


def sin_tildes(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def norm_clave(texto) -> str:
    """Para comparar encabezados / nombres: sin tildes, mayúsculas, espacios simples."""
    if texto is None:
        return ""
    return re.sub(r"\s+", " ", sin_tildes(str(texto))).strip().upper()


def preparar_texto(valor) -> str:
    if valor is None:
        return ""
    s = unicodedata.normalize("NFKC", str(valor)).lower()
    s = s.replace("mailto:", " ").replace("​", "").replace("\xa0", " ")
    s = re.sub(r"\s*@\s*", "@", s)                                   # "juan @ gmail.com"
    s = re.sub(r"@([a-z0-9\-]+),(com|net|org|co|es|ec)\b", r"@\1.\2", s)  # "@gmail,com"
    return s


def extraer(valor) -> list:
    """Devuelve los correos encontrados en un texto, sin repetir y en orden."""
    vistos, salida = set(), []
    for m in EXTRAER_RE.finditer(preparar_texto(valor)):
        e = m.group(1).strip(".")
        if e not in vistos:
            vistos.add(e)
            salida.append(e)
    return salida


def corregir_dominio(email: str):
    local, _, dominio = email.rpartition("@")
    if dominio in TYPOS:
        return f"{local}@{TYPOS[dominio]}", True
    return email, False


def proveedor(dominio: str) -> str:
    if dominio in PROVEEDORES_EXACTOS:
        return PROVEEDORES_EXACTOS[dominio]
    raiz = dominio.split(".")[0]
    return PROVEEDORES_PREFIJO.get(raiz, OTROS)


def es_generico(local: str) -> bool:
    base = re.sub(r"[._\-0-9]+$", "", local)
    return base in GENERICOS or local.startswith(("facturacion", "facturaelectronica", "contabilidad"))


def _reglas_proveedor(local: str, dominio: str, prov: str):
    """Reglas reales de creación de cuentas de cada proveedor. Devuelve motivo o None."""
    if prov == "Gmail":
        base = local.split("+")[0]
        if not re.fullmatch(r"[a-z0-9.]+", base):
            return "gmail: solo letras, números y puntos"
        if not 6 <= len(base.replace(".", "")) <= 30:
            return "gmail: el usuario debe tener 6 a 30 caracteres"
    elif prov == "Yahoo":
        if not re.fullmatch(r"[a-z][a-z0-9_.]{3,31}", local):
            return "yahoo: 4-32 caracteres, empieza por letra"
        if local.count(".") > 1 or local.endswith((".", "_")):
            return "yahoo: formato no permitido"
    elif prov in ("Hotmail", "Outlook", "Live/MSN"):
        if not re.fullmatch(r"[a-z][a-z0-9._\-]{0,63}", local) or local.endswith("."):
            return "microsoft: debe empezar por letra"
    return None


def validar(email: str):
    """Devuelve (valido: bool, motivo: str|None)."""
    if not FORMATO_RE.match(email):
        return False, "formato inválido"
    local, _, dominio = email.rpartition("@")
    if local in BASURA_LOCAL or any(p in local for p in BASURA_CONTIENE) or re.fullmatch(r"(.)\1{2,}", local):
        return False, "correo de relleno"
    if dominio in BASURA_DOMINIOS:
        return False, "dominio de relleno"
    if dominio in DESECHABLES:
        return False, "correo desechable/temporal"
    motivo = _reglas_proveedor(local, dominio, proveedor(dominio))
    if motivo:
        return False, motivo
    return True, None


def info(email: str) -> dict:
    local, _, dominio = email.rpartition("@")
    return {"dominio": dominio, "proveedor": proveedor(dominio), "generico": int(es_generico(local))}
