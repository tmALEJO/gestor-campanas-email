"""Rutas y ajustes generales del proyecto."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"            # aquí va el Excel (o varios) y la base SQLite
DB_PATH = DATA_DIR / "correos.db"
BACKUP_DIR = DATA_DIR / "backups"
EXPORT_DIR = BASE_DIR / "exports"       # copia de cada archivo generado + reportes
STATIC_DIR = BASE_DIR / "static"

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
