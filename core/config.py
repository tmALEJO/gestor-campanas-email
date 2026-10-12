"""Rutas y ajustes generales del proyecto."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"            # aquí va el Excel (o varios) y la base SQLite
DB_PATH = DATA_DIR / "correos.db"
BACKUP_DIR = DATA_DIR / "backups"
EXPORT_DIR = BASE_DIR / "exports"       # copia de cada archivo generado + reportes
STATIC_DIR = BASE_DIR / "static"
ENV_PATH = BASE_DIR / ".env"            # aquí va la API key de ClearBounce (NUNCA a GitHub)

HOST = "127.0.0.1"                      # solo tu PC: los datos son personales
PUERTO = 5050
BACKUPS_A_GUARDAR = 20

# Hojas del Excel que NO son secciones (se comparan sin tildes y en mayúsculas)
HOJAS_IGNORADAS = {"RESUMEN"}

SECCION_EXTERNA = "Externo (importado)"

for _d in (DATA_DIR, BACKUP_DIR, EXPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def listar_excels():
    """Todos los .xlsx dentro de data/ (ignora temporales de Excel '~$...')."""
    return sorted(p for p in DATA_DIR.glob("*.xlsx") if not p.name.startswith("~$"))


# ------------------------------------------------------------------ .env / ClearBounce
def _leer_env():
    """Lee el archivo .env (CLAVE=valor por línea). Se relee en cada uso:
    si cambias la API key no hace falta reiniciar el programa."""
    valores = {}
    if ENV_PATH.exists():
        for linea in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            valores[clave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def _entero(valor, defecto):
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return defecto


def clearbounce():
    """Ajustes de ClearBounce. Si existe el archivo .env, solo vale lo que diga ese archivo (Flask a veces
    copia el .env al entorno al arrancar y esa copia quedaría vieja). Si no existe, se usan variables del sistema."""
    env = _leer_env() if ENV_PATH.exists() else {k: v for k, v in os.environ.items() if k.startswith(("CLEARBOUNCE_", "CB_"))}
    return {
        "api_key": env.get("CLEARBOUNCE_API_KEY", "").strip(),
        "base_url": env.get("CLEARBOUNCE_BASE_URL", "https://api.clearbounce.net/api/v1").rstrip("/"),
        # Días que se confía en un resultado anterior: ese correo no se vuelve a pagar
        "dias_cache": _entero(env.get("CB_DIAS_CACHE"), 30),
        "timeout": _entero(env.get("CB_TIMEOUT"), 30),
    }
