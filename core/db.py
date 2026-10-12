"""Base de datos SQLite (data/correos.db). Es la fuente de verdad de los estados."""
import shutil
import sqlite3
from datetime import datetime

from .config import BACKUP_DIR, BACKUPS_A_GUARDAR, DB_PATH

ESQUEMA = """
CREATE TABLE IF NOT EXISTS contactos (
    email       TEXT PRIMARY KEY,
    seccion     TEXT,
    pais        TEXT,
    ciudad      TEXT,
    empresa     TEXT,
    contacto    TEXT,
    dominio     TEXT,
    proveedor   TEXT,
    generico    INTEGER DEFAULT 0,
    estado      TEXT NOT NULL DEFAULT 'disponible',  -- disponible | usado | invalido | baja
    motivo      TEXT,
    verificado  INTEGER DEFAULT 0,                    -- 1 = el verificador dijo que es bueno
    lote_id     INTEGER,                              -- último lote que lo tomó
    creado      TEXT,
    actualizado TEXT
);
CREATE INDEX IF NOT EXISTS ix_estado    ON contactos(estado);
CREATE INDEX IF NOT EXISTS ix_seccion   ON contactos(seccion);
CREATE INDEX IF NOT EXISTS ix_pais      ON contactos(pais);
CREATE INDEX IF NOT EXISTS ix_proveedor ON contactos(proveedor);
CREATE INDEX IF NOT EXISTS ix_dominio   ON contactos(dominio);

CREATE TABLE IF NOT EXISTS lotes (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha    TEXT,
    tipo     TEXT,      -- generado | completado | marcado:<estado> | importado
    nombre   TEXT,
    cantidad INTEGER,
    nuevos   INTEGER,
    filtros  TEXT,
    anulado  INTEGER DEFAULT 0,
    nota     TEXT
);
CREATE TABLE IF NOT EXISTS lote_items (
    lote_id INTEGER,
    email   TEXT,
    nuevo   INTEGER DEFAULT 1,  -- 0 = venía en el archivo que subiste, 1 = lo agregó el sistema
    PRIMARY KEY (lote_id, email)
);
CREATE TABLE IF NOT EXISTS dominios (dominio TEXT PRIMARY KEY, tiene_mx INTEGER, revisado TEXT);
CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT);

-- Verificación con ClearBounce -------------------------------------------------
-- Un borrador es una selección de correos que AÚN no se marcó como usada.
CREATE TABLE IF NOT EXISTS borradores (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha     TEXT,
    tipo      TEXT,      -- generado | completado
    nombre    TEXT,
    cantidad  INTEGER,   -- cuántos pidió el usuario (sin contar los buenos subidos en 2b)
    filtros   TEXT,
    estado    TEXT,      -- borrador | verificando | listo | generado | descartado
    lote_id   INTEGER,   -- lote creado al confirmar
    avisos    TEXT,
    error     TEXT
);
CREATE TABLE IF NOT EXISTS borrador_items (
    borrador_id INTEGER,
    email       TEXT,
    base        INTEGER DEFAULT 0,  -- 1 = venía en el archivo de buenos (2b): no se verifica
    ronda       INTEGER DEFAULT 1,  -- 2, 3… = agregado con "Reponer"
    cb_estado   TEXT,               -- deliverable | undeliverable | risky | unknown | NULL (sin verificar)
    cb_motivo   TEXT,
    cb_puntaje  INTEGER,
    cache       INTEGER DEFAULT 0,  -- 1 = resultado reutilizado de una verificación anterior (no gastó crédito)
    PRIMARY KEY (borrador_id, email)
);
CREATE TABLE IF NOT EXISTS cb_jobs (
    job_id      TEXT PRIMARY KEY,
    borrador_id INTEGER,
    total       INTEGER,
    estimado    INTEGER,
    creado      TEXT,
    estado      TEXT,               -- pending | processing | completed | failed
    progreso    INTEGER DEFAULT 0,
    aplicado    INTEGER DEFAULT 0   -- 1 = resultados ya guardados en la base
);
"""

# Columnas nuevas en tablas que ya existían (bases creadas con la versión anterior)
COLUMNAS_NUEVAS = {
    "contactos": [("cb_estado", "TEXT"), ("cb_motivo", "TEXT"), ("cb_puntaje", "INTEGER"), ("cb_fecha", "TEXT")],
}


def ahora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    _migrar(con)
    return con


def _migrar(con):
    for tabla, columnas in COLUMNAS_NUEVAS.items():
        existentes = {r[1] for r in con.execute(f"PRAGMA table_info({tabla})")}
        for nombre, tipo in columnas:
            if nombre not in existentes:
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}")
    con.execute("CREATE INDEX IF NOT EXISTS ix_cb_estado ON contactos(cb_estado)")
    con.commit()


def respaldar(motivo: str = "auto"):
    """Copia la base a data/backups/ y deja solo las últimas N copias."""
    if not DB_PATH.exists():
        return None
    destino = BACKUP_DIR / f"correos_{datetime.now():%Y%m%d_%H%M%S}_{motivo}.db"
    shutil.copy2(DB_PATH, destino)
    copias = sorted(BACKUP_DIR.glob("correos_*.db"))
    for viejo in copias[:-BACKUPS_A_GUARDAR]:
        viejo.unlink(missing_ok=True)
    return destino
