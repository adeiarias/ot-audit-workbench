import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(os.environ.get("AUDIT_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CAPTURES_ROOT = DATA_DIR / "campaigns"  # data/campaigns/<id>/pcaps/...
DATABASE_URL = os.environ.get("AUDIT_DATABASE_URL", f"sqlite:///{DATA_DIR / 'audit.db'}")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def harden_permissions() -> None:
    """La BD guarda las claves de API de los perfiles de LLM en texto plano: solo lectura/escritura para tu usuario (0600)."""
    if not DATABASE_URL.startswith("sqlite:///"):
        return
    base = Path(DATABASE_URL.removeprefix("sqlite:///"))
    for f in [base, base.with_name(base.name + "-wal"), base.with_name(base.name + "-shm"), *base.parent.glob(base.name + ".bak-*")]:
        try:
            if f.exists():
                os.chmod(f, 0o600)
        except OSError:
            pass
