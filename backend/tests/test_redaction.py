import sqlite3
from datetime import date

import pytest
from sqlalchemy import create_engine, text

from app import migrations
from app.db import SessionLocal
from app.llm.redaction import Redactor
from app.models import Asset, Campaign, AuditType


@pytest.fixture()
def cid(client):
    with SessionLocal() as db:
        c = Campaign(name="x", audit_type=AuditType.OT, start_date=date.today(), scope="10.0.0.0/24\nplc.corp")
        db.add(c)
        db.flush()
        db.add(Asset(campaign_id=c.id, ip="10.0.0.5", hostname="hmi-01", ports=[], sources=[]))
        db.commit()
        return c.id


@pytest.fixture()
def red(cid):
    opened = []

    def make(enabled=True):
        db = SessionLocal()
        opened.append(db)
        return Redactor(db, cid, enabled), db
    yield make
    for db in opened:
        db.close()


def test_roundtrip_and_stable_tokens_across_instances(red):
    text_ = "Scan 10.0.0.5 en 10.0.0.0/24, mac 00:11:22:33:44:05, plc.corp, hmi-01 y srv.lan; fe80::1:2 y 10.0.0.5."
    r1, db1 = red()
    out = r1.redact(text_)
    db1.commit()
    for real in ("10.0.0.5", "10.0.0.0/24", "00:11:22:33:44:05", "plc.corp", "hmi-01", "srv.lan", "fe80::1:2"):
        assert real not in out
    assert r1.restore(out) == text_
    r2, _ = red()  # otra instancia: mismo mapa persistido → mismos seudónimos
    assert r2.redact(text_) == out and r2.restore(out) == text_


def test_secrets_are_irreversibly_masked(red):
    r, _ = red()
    raw = ("password=hunter2 token: abc123def api_key=\"k e y\" community: public\n"
           "Authorization: Bearer abcdefghijkl.mnop\nAKIAABCDEFGHIJKLMNOP\n"
           "-----BEGIN RSA PRIVATE KEY-----\nMIIB\nxyz\n-----END RSA PRIVATE KEY-----\n"
           "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4")
    out = r.redact(raw)
    for leaked in ("hunter2", "abc123def", "k e y", "public", "abcdefghijkl", "AKIAABCDEFGHIJKLMNOP", "MIIB", "eyJhbGci"):
        assert leaked not in out, leaked
    assert out.count("[REDACTED") >= 7 and "password=[REDACTED]" in out


def test_versions_and_invalid_ips_untouched_and_glued_tokens_restore(red):
    r, _ = red()
    assert r.redact("OpenSSH v1.2.3.4 y 999.1.1.1 y 300.2.3.4/33") == "OpenSSH v1.2.3.4 y 999.1.1.1 y 300.2.3.4/33"
    assert r.redact("hora 12:30:45 y mac 00:11:22:33:44:05 y ::1 y 2001:db8::ff") .startswith("hora 12:30:45 y mac MAC-")
    assert "::1" not in r.redact("loopback ::1") and "2001:db8" not in r.redact("red 2001:db8::ff")
    assert r.restore("IP-0099 no existe") == "IP-0099 no existe"  # token desconocido: intacto
    tok = r.redact("10.0.0.5")
    assert r.restore(f"({tok}),{tok}.") == "(10.0.0.5),10.0.0.5."


def test_disabled_is_passthrough(red):
    r, _ = red(enabled=False)
    s = "10.0.0.5 password=hunter2"
    assert r.redact(s) == s


def test_migration_adds_column_and_backs_up(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE campaigns (id INTEGER PRIMARY KEY, name TEXT)")
        c.execute("INSERT INTO campaigns VALUES (1, 'previa')")
    eng = create_engine(f"sqlite:///{path}")
    assert migrations.migrate(eng) == ["campaigns.llm_redaction", "campaigns.llm_profile_id"]
    with eng.connect() as conn:
        assert conn.execute(text("SELECT name, llm_redaction FROM campaigns")).one() == ("previa", 1)  # conserva datos; redacción activa por defecto
    backups = list(tmp_path.glob("old.db.bak-*"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as b:
        assert "llm_redaction" not in [r[1] for r in b.execute("PRAGMA table_info(campaigns)")]  # la copia es la previa
    assert migrations.migrate(eng) == [] and len(list(tmp_path.glob("old.db.bak-*"))) == 1  # idempotente, sin copias extra


def test_sdk_blocks_dump_to_replayable_dicts():
    """Los bloques del SDK real se convierten a dicts válidos para reenviar (sin None, thinking con firma)."""
    from anthropic.types.beta import BetaTextBlock, BetaThinkingBlock, BetaToolUseBlock

    blocks = [
        BetaThinkingBlock(type="thinking", thinking="", signature="sigX"),
        BetaTextBlock(type="text", text="hola", citations=None),
        BetaToolUseBlock(type="tool_use", id="toolu_1", name="get_assets", input={}),
    ]
    out = [b.model_dump(mode="json", exclude_none=True) for b in blocks]
    assert out[0] == {"type": "thinking", "thinking": "", "signature": "sigX"}
    assert out[1] == {"type": "text", "text": "hola"}
    assert out[2]["type"] == "tool_use" and out[2]["input"] == {} and None not in out[2].values()


def test_migration_adds_findings_source_key(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE findings (id INTEGER PRIMARY KEY, name TEXT)")
        c.execute("INSERT INTO findings VALUES (1, 'previo')")
    eng = create_engine(f"sqlite:///{path}")
    assert migrations.migrate(eng) == ["findings.source_key"]
    with eng.connect() as conn:
        assert conn.execute(text("SELECT name, source_key FROM findings")).one() == ("previo", "")  # conserva los hallazgos; sin origen automático
