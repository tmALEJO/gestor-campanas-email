"""
Cliente mínimo de la API de ClearBounce (https://docs.clearbounce.net).

Solo usa la librería estándar (urllib): no hay que instalar nada nuevo.
La API key se lee del archivo .env y NUNCA se envía a la página web.

Endpoints usados:
    GET  /credits                 saldo de créditos
    POST /bulk/upload             {"emails": [...]}  (máx. 10.000)  -> jobId
    GET  /bulk/status/<jobId>     progreso
    GET  /bulk/results/<jobId>    resultados (cuando status = completed)
"""
import json
import urllib.error
import urllib.request

from .config import clearbounce as ajustes

MAX_POR_JOB = 10_000          # límite de ClearBounce por subida
MAX_JOBS_SIMULTANEOS = 5      # límite de ClearBounce

# Estados de ClearBounce -> grupo en la página
GRUPO = {"deliverable": "bueno", "undeliverable": "malo", "risky": "dudoso", "unknown": "dudoso"}

MENSAJES = {
    401: "ClearBounce rechazó la API key. Revisa CLEARBOUNCE_API_KEY en el archivo .env (sin espacios ni comillas de más).",
    402: "No tienes créditos suficientes en ClearBounce. Recarga en clearbounce.net/pricing o pide menos correos.",
    403: "Esta API key no tiene permiso para esa acción. Las claves de prueba (cb_test_) NO sirven para verificar "
         "listas: usa tu clave cb_live_.",
    404: "ClearBounce no encontró esa verificación (los trabajos se borran a los 7 días).",
    429: "ClearBounce pide esperar: demasiadas consultas seguidas. Se reintenta solo.",
}


class ErrorClearBounce(RuntimeError):
    def __init__(self, mensaje, status=None, codigo=None):
        super().__init__(mensaje)
        self.status = status
        self.codigo = codigo


def configurada():
    return bool(ajustes()["api_key"])


def modo():
    k = ajustes()["api_key"]
    if not k:
        return None
    return "prueba" if k.startswith("cb_test_") else "real"


def _peticion(metodo, ruta, cuerpo=None):
    cfg = ajustes()
    if not cfg["api_key"]:
        raise ErrorClearBounce("ClearBounce no está configurado: falta CLEARBOUNCE_API_KEY en el archivo .env.")
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    req = urllib.request.Request(cfg["base_url"] + ruta, data=datos, method=metodo, headers={
        "X-API-Key": cfg["api_key"],
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "GestorCampanasEmail/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
            texto = r.read().decode("utf-8", "replace")
            return json.loads(texto) if texto else {}
    except urllib.error.HTTPError as e:
        texto = e.read().decode("utf-8", "replace")
        try:
            info = json.loads(texto)
        except ValueError:
            info = {}
        err = info.get("error") if isinstance(info.get("error"), dict) else {}
        codigo = info.get("code") or err.get("code")
        detalle = info.get("message") or err.get("message") or texto[:200]
        msg = MENSAJES.get(e.code) or f"ClearBounce respondió {e.code}: {detalle}"
        raise ErrorClearBounce(msg, e.code, codigo) from None
    except urllib.error.URLError as e:
        raise ErrorClearBounce(f"No pude conectar con ClearBounce ({e.reason}). Revisa tu internet.") from None
    except TimeoutError:
        raise ErrorClearBounce("ClearBounce tardó demasiado en responder. Intenta de nuevo.") from None


def _buscar_numero(obj, profundidad=0):
    """La respuesta de /credits no está documentada en detalle: busco el saldo en los nombres más probables."""
    if profundidad > 3 or not isinstance(obj, dict):
        return None
    for clave in ("creditsRemaining", "credits", "balance", "remaining", "availableCredits", "available",
                  "creditBalance", "credit", "total"):
        v = obj.get(clave)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str) and v.strip().replace(".", "", 1).isdigit():
            return int(float(v))
        if isinstance(v, dict):
            n = _buscar_numero(v, profundidad + 1)
            if n is not None:
                return n
    for v in obj.values():
        if isinstance(v, dict):
            n = _buscar_numero(v, profundidad + 1)
            if n is not None:
                return n
    return None


def creditos():
    """Devuelve (créditos | None, respuesta_cruda)."""
    r = _peticion("GET", "/credits")
    return _buscar_numero(r), r


def subir(emails):
    if not emails:
        raise ErrorClearBounce("No hay correos para verificar.")
    if len(emails) > MAX_POR_JOB:
        raise ErrorClearBounce(f"Máximo {MAX_POR_JOB} correos por subida.")
    r = _peticion("POST", "/bulk/upload", {"emails": list(emails)})
    job = r.get("jobId") or (r.get("data") or {}).get("jobId")
    if not job:
        raise ErrorClearBounce(f"ClearBounce no devolvió un jobId: {str(r)[:200]}")
    return {"job_id": job, "total": r.get("totalEmails", len(emails)),
            "estimado": r.get("estimatedTimeSeconds"), "duplicados": r.get("duplicateCount", 0)}


def estado(job_id):
    r = _peticion("GET", f"/bulk/status/{job_id}")
    return r.get("job") or r.get("data") or r


def resultados(job_id):
    r = _peticion("GET", f"/bulk/results/{job_id}")
    lista = r.get("results")
    if lista is None and isinstance(r.get("data"), dict):
        lista = r["data"].get("results")
    if lista is None and isinstance(r.get("data"), list):
        lista = r["data"]
    return lista or []
