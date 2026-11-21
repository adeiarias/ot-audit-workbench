"""Migraciones mínimas de columnas (sustituto ligero de Alembic mientras el esquema sea pequeño).

Antes de alterar una BD SQLite existente se hace una copia consistente junto al fichero (audit.db.bak-<fecha>).
"""
import sqlite3
from datetime import datetime

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# (tabla, columna, DDL)
COLUMNS = [
    ("campaigns", "llm_redaction", "ALTER TABLE campaigns ADD COLUMN llm_redaction BOOLEAN NOT NULL DEFAULT 1"),
    ("campaigns", "llm_profile_id", "ALTER TABLE campaigns ADD COLUMN llm_profile_id INTEGER REFERENCES llm_profiles(id) ON DELETE SET NULL"),
    ("chat_messages", "provider", "ALTER TABLE chat_messages ADD COLUMN provider VARCHAR(30) NOT NULL DEFAULT ''"),
]


def _backup(engine: Engine) -> None:
    if engine.dialect.name != "sqlite" or not engine.url.database:
        return
    src = engine.url.database
    dest = f"{src}.bak-{datetime.now():%Y%m%d-%H%M%S}"
    with sqlite3.connect(src) as a, sqlite3.connect(dest) as b:
        a.backup(b)  # copia consistente aunque haya WAL


def migrate(engine: Engine) -> list[str]:
    """Aplica las columnas que falten. Devuelve la lista de cambios aplicados."""
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    pending = [(t, c, ddl) for t, c, ddl in COLUMNS if t in tables and c not in {x["name"] for x in insp.get_columns(t)}]
    if not pending:
        return []
    _backup(engine)
    with engine.begin() as conn:
        for _, _, ddl in pending:
            conn.execute(text(ddl))
    return [f"{t}.{c}" for t, c, _ in pending]
