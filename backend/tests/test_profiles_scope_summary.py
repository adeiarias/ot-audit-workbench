import json
import os
import stat

import pytest

from app import db as app_db
from app import mcp_client
from app.db import SessionLocal
from app.llm import agent, client
from app.models import Asset, Campaign, LLMProfile, ToolRun
from app.scope import diff_scope, parse_scope, validate_scope
from tests.conftest import MCP_TOOLS
from tests.test_chat import mk, wait_idle
from tests.test_llm_providers import clean_env, resp, server  # noqa: F401  (fixtures)

SECRET = "sk-test-0123456789abcdef"


def profile(client_, **kw):
    body = {"name": "DS", "provider": "deepseek", "api_key": SECRET, **kw}
    r = client_.post("/api/llm/profiles", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- alcance

def test_parse_scope_lines_kinds_and_warnings():
    rules, issues = parse_scope("# cabecera\n10.0.0.5\n\n10.0.0.0/24  # LAN\nplc.corp\n0.0.0.0/0\n2001:db8::/32\nesto no vale!\n10.0.0.256")
    assert [(r.line, r.kind, r.value) for r in rules] == [(2, "ip", "10.0.0.5"), (4, "cidr", "10.0.0.0/24"), (5, "hostname", "plc.corp"), (6, "cidr", "0.0.0.0/0"), (7, "cidr", "2001:db8::/32")]
    assert [(i.line, i.text) for i in issues] == [(8, "esto no vale!"), (9, "10.0.0.256")]
    assert [r.warning != "" for r in rules] == [False, False, False, True, True]  # /0 e IPv6 /32 son rangos enormes
    assert "mil millones" in rules[3].warning
    with pytest.raises(ValueError, match=r"línea 8.*línea 9"):
        validate_scope("10.0.0.5\n# c\n\n\n\n\n\nesto no vale!\n10.0.0.256")
    assert diff_scope("10.0.0.0/24\nplc.corp", "10.0.0.0/24\n192.168.0.1") == (["192.168.0.1"], ["plc.corp"])


def test_scope_parse_endpoint(client):
    r = client.post("/api/scope/parse", json={"scope": "10.0.0.5\n10.0.0.0/8\nplc.corp\nmal!"}).json()
    assert r["counts"] == {"ip": 1, "cidr": 1, "hostname": 1} and r["warnings"] == 1
    assert r["errors"] == [{"line": 4, "text": "mal!", "error": "No es una IP, un CIDR ni un hostname válido"}]
    assert client.post("/api/scope/parse", json={"scope": ""}).json()["rules"] == []


def test_edit_scope_history_and_validation(client):
    cid = mk(client)
    h = client.get(f"/api/campaigns/{cid}/scope-history").json()
    assert len(h) == 1 and h[0]["initial"] and h[0]["added"] == ["10.0.0.0/24", "plc.corp"]  # el alcance inicial queda registrado
    assert client.patch(f"/api/campaigns/{cid}", json={"scope": "10.0.0.0/24\nplc.corp"}).status_code == 200
    assert len(client.get(f"/api/campaigns/{cid}/scope-history").json()) == 1  # mismo alcance: sin entrada nueva
    assert client.patch(f"/api/campaigns/{cid}", json={"scope": "192.168.1.0/24\nplc.corp"}).status_code == 200
    h = client.get(f"/api/campaigns/{cid}/scope-history").json()
    assert len(h) == 2 and h[0]["added"] == ["192.168.1.0/24"] and h[0]["removed"] == ["10.0.0.0/24"] and not h[0]["initial"]
    assert client.get(f"/api/campaigns/{cid}").json()["scope"] == "192.168.1.0/24\nplc.corp"
    r = client.patch(f"/api/campaigns/{cid}", json={"scope": "10.0.0.5\nbasura!!"})
    assert r.status_code == 422 and "línea 2" in json.dumps(r.json(), ensure_ascii=False)
    assert client.get(f"/api/campaigns/{cid}").json()["scope"] == "192.168.1.0/24\nplc.corp"  # nada cambió
    assert client.patch(f"/api/campaigns/{cid}", json={"scope": ""}).status_code == 200  # vaciar es válido (bloquea todo)
    assert client.patch(f"/api/campaigns/{cid}", json={"name": None, "end_date": None}).status_code == 200  # null en obligatorio: se ignora
    assert client.get(f"/api/campaigns/{cid}").json()["name"] == "Planta"
    assert client.get("/api/campaigns/999/scope-history").status_code == 404


def test_assets_report_in_scope_against_current_scope(client):
    cid = mk(client)
    assert [a["in_scope"] for a in client.get(f"/api/campaigns/{cid}/assets").json()] == [True]
    client.patch(f"/api/campaigns/{cid}", json={"scope": "192.168.0.0/24"})
    assert [a["in_scope"] for a in client.get(f"/api/campaigns/{cid}/assets").json()] == [False]  # sigue ahí, marcado fuera de alcance


# ---------------------------------------------------------------- perfiles

def test_profile_crud_masks_keys_and_default_is_unique(client):
    p = profile(client, model="deepseek-flash")
    assert "api_key" not in p and p["has_key"] and p["key_hint"] == "…cdef" and p["external"] and p["problem"] is None and p["label"] == "DeepSeek (api.deepseek.com)"
    q = profile(client, name="Local", provider="litellm", model="mi-alias", api_key=None, is_default=True)
    assert q["has_key"] is False and q["is_default"] and not q["external"] and q["key_hint"] == ""
    listing = client.get("/api/llm/profiles").json()
    assert SECRET not in json.dumps(listing) and [x["name"] for x in listing["profiles"]] == ["DS", "Local"]
    assert listing["env"]["in_use_by_default"] is False  # hay un perfil predeterminado
    client.patch(f"/api/llm/profiles/{p['id']}", json={"is_default": True})
    assert {x["name"]: x["is_default"] for x in client.get("/api/llm/profiles").json()["profiles"]} == {"DS": True, "Local": False}  # solo uno

    assert client.post("/api/llm/profiles", json={"name": "DS", "provider": "deepseek"}).status_code == 409
    assert client.post("/api/llm/profiles", json={"name": "x", "provider": "grok"}).status_code == 422
    assert client.post("/api/llm/profiles", json={"name": "x", "provider": "litellm", "base_url": "ftp://a"}).status_code == 422
    assert client.post("/api/llm/profiles", json={"name": "", "provider": "litellm"}).status_code == 422
    assert client.patch("/api/llm/profiles/999", json={}).status_code == 404

    # la clave: omitida = se conserva; nueva = se reemplaza; clear_api_key = se borra
    assert client.patch(f"/api/llm/profiles/{p['id']}", json={"model": "otro"}).json()["key_hint"] == "…cdef"
    assert client.patch(f"/api/llm/profiles/{p['id']}", json={"api_key": "sk-nueva-clave-9999"}).json()["key_hint"] == "…9999"
    assert client.patch(f"/api/llm/profiles/{p['id']}", json={"api_key": "   "}).json()["key_hint"] == "…9999"  # vacío en blanco: no pisa la clave
    assert client.patch(f"/api/llm/profiles/{p['id']}", json={"clear_api_key": True}).json()["has_key"] is False
    assert client.patch(f"/api/llm/profiles/{p['id']}", json={"name": "Local"}).status_code == 409


def test_campaign_profile_selection_and_cascade(client):
    cid = mk(client)
    a, b = profile(client), profile(client, name="Local", provider="litellm", model="m", api_key=None)
    assert client.patch(f"/api/campaigns/{cid}", json={"llm_profile_id": b["id"]}).json()["llm_profile_id"] == b["id"]
    assert [x["campaigns_using"] for x in client.get("/api/llm/profiles").json()["profiles"]] == [0, 1]
    assert client.patch(f"/api/campaigns/{cid}", json={"llm_profile_id": 999}).status_code == 422
    chat = client.get(f"/api/campaigns/{cid}/chat").json()
    assert (chat["profile_name"], chat["provider"], chat["external"], chat["source"]) == ("Local", "litellm", False, "profile")
    assert client.delete(f"/api/llm/profiles/{b['id']}").status_code == 204
    assert client.get(f"/api/campaigns/{cid}").json()["llm_profile_id"] is None  # ON DELETE SET NULL
    assert client.patch(f"/api/campaigns/{cid}", json={"llm_profile_id": a["id"]}).status_code == 200
    assert client.patch(f"/api/campaigns/{cid}", json={"llm_profile_id": None}).json()["llm_profile_id"] is None  # null = volver al predeterminado


def test_resolution_order_chosen_then_default_then_env(client, monkeypatch):
    monkeypatch.setenv("AUDIT_LLM_PROVIDER", "litellm")
    monkeypatch.setenv("AUDIT_LLM_MODEL", "del-entorno")
    cid = mk(client)
    with SessionLocal() as db:
        c = db.get(Campaign, cid)
        s = client_resolve(db, c)
        assert (s.source, s.model) == ("env", "del-entorno")
    default = profile(client, name="Pred", provider="litellm", model="pred", api_key=None, is_default=True)
    other = profile(client, name="Otro", provider="litellm", model="otro", api_key=None)
    with SessionLocal() as db:
        c = db.get(Campaign, cid)
        assert client_resolve(db, c).model == "pred"
        c.llm_profile_id = other["id"]
        db.commit()
        assert client_resolve(db, c).model == "otro"


def client_resolve(db, campaign):
    return client_module.resolve(db, campaign)


client_module = client  # el módulo app.llm.client (el nombre `client` de las fixtures lo oculta dentro de los tests)


def test_profile_key_falls_back_to_env_when_empty(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-del-entorno")
    p = LLMProfile(id=1, name="x", provider="deepseek", api_key="", model="", base_url="")
    assert client_module.from_profile(p).api_key == "sk-del-entorno"
    p.api_key = "sk-propia"
    assert client_module.from_profile(p).api_key == "sk-propia"  # la del perfil manda


# ---------------------------------------------------------------- chat con perfiles distintos por campaña

@pytest.fixture()
def tools_stub(client, monkeypatch):
    async def fake_list_tools():
        return MCP_TOOLS
    monkeypatch.setattr(mcp_client, "list_tools", fake_list_tools)
    monkeypatch.setattr(agent, "_mcp_cache", None)
    agent._busy.clear()


def test_two_campaigns_use_their_own_profile_and_key(client, tools_stub, server, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ENTORNO-no-debe-usarse")
    ds = profile(client, name="DS", provider="deepseek", api_key="sk-perfil-deepseek")
    local = profile(client, name="Local", provider="litellm", model="mi-alias", api_key=None, base_url="http://localhost:4000")
    a, b = mk(client), mk(client)
    client.patch(f"/api/campaigns/{a}", json={"llm_profile_id": ds["id"]})
    client.patch(f"/api/campaigns/{b}", json={"llm_profile_id": local["id"]})
    srv = server((200, resp({"content": "desde deepseek"})), (200, resp({"content": "desde local"})))
    client.post(f"/api/campaigns/{a}/chat", json={"message": "uno"})
    wait_idle(client, a)
    client.post(f"/api/campaigns/{b}/chat", json={"message": "dos"})
    wait_idle(client, b)
    r1, r2 = srv.seen
    assert str(r1.url) == "https://api.deepseek.com/chat/completions" and r1.headers["authorization"] == "Bearer sk-perfil-deepseek"
    assert str(r2.url) == "http://localhost:4000/chat/completions" and "authorization" not in r2.headers  # la clave de una campaña no viaja a la otra
    assert json.loads(r2.content)["model"] == "mi-alias"


def test_switching_a_campaign_to_another_provider_requires_new_conversation(client, tools_stub, server):
    ds = profile(client)
    local = profile(client, name="Local", provider="litellm", model="m", api_key=None)
    cid = mk(client)
    client.patch(f"/api/campaigns/{cid}", json={"llm_profile_id": ds["id"]})
    server((200, resp({"content": "hola"})))
    client.post(f"/api/campaigns/{cid}/chat", json={"message": "uno"})
    wait_idle(client, cid)
    client.patch(f"/api/campaigns/{cid}", json={"llm_profile_id": local["id"]})
    r = client.post(f"/api/campaigns/{cid}/chat", json={"message": "dos"})
    assert r.status_code == 409 and "Nueva conversación" in r.json()["detail"]
    view = client.get(f"/api/campaigns/{cid}/chat").json()  # la interfaz puede avisar antes de que el usuario escriba
    assert view["conversation_provider"] == "deepseek" and view["provider"] == "litellm"
    client.delete(f"/api/campaigns/{cid}/chat")
    assert client.get(f"/api/campaigns/{cid}/chat").json()["conversation_provider"] is None


# ---------------------------------------------------------------- prueba de conexión

def test_connection_test_ok_and_failures(client, server):
    p = profile(client, model="deepseek-flash")
    srv = server((200, resp({"content": "OK"})))
    r = client.post("/api/llm/test", json={"profile_id": p["id"]}).json()
    assert r["ok"] and r["reply"] == "OK" and r["model"] == "deepseek-flash" and isinstance(r["ms"], int)
    body = json.loads(srv.seen[0].content)
    assert [m["content"] for m in body["messages"]][1] == "ping" and "tools" not in body  # solo un ping: ningún dato de campañas

    server((401, {"error": f"clave {SECRET} inválida"}))
    r = client.post("/api/llm/test", json={"profile_id": p["id"]}).json()
    assert r["ok"] is False and "credenciales" in r["error"] and SECRET not in r["error"]  # la clave nunca se devuelve
    q = profile(client, name="SinClave", api_key=None)
    r = client.post("/api/llm/test", json={"profile_id": q["id"]}).json()
    assert r["ok"] is False and "clave de DeepSeek" in r["error"]  # no se intenta ni la llamada
    assert client.post("/api/llm/test", json={"profile_id": 999}).status_code == 404
    assert client.post("/api/llm/test", json={}).json()["ok"] is False  # entorno sin configurar
    assert "deepseek" in client.get("/api/llm/presets").json() and client.get("/api/llm/presets").json()["litellm"]["base_url"] == "http://localhost:4000"


def test_database_files_are_private(tmp_path, monkeypatch):
    f = tmp_path / "audit.db"
    f.write_text("x")
    wal, bak = tmp_path / "audit.db-wal", tmp_path / "audit.db.bak-20260101-000000"
    for x in (wal, bak):
        x.write_text("y")
    for x in (f, wal, bak):
        os.chmod(x, 0o644)
    monkeypatch.setattr(app_db, "DATABASE_URL", f"sqlite:///{f}")
    app_db.harden_permissions()
    assert all(stat.S_IMODE(os.stat(x).st_mode) == 0o600 for x in (f, wal, bak))  # las copias de seguridad también llevan las claves


# ---------------------------------------------------------------- resumen

def test_summary(client):
    from tests.test_report import add_evidence, add_finding, seed
    cid = client.post("/api/campaigns", json={"name": "Vending OT", "audit_type": "OT", "start_date": "2026-11-10", "scope": "10.0.0.0/24\nplc.corp"}).json()["id"]
    seed(client, cid)  # F-001 High (exploitation, confirmed) · F-002 Medium (post, draft) · F-003 falso positivo
    with SessionLocal() as db:
        db.add(Asset(campaign_id=cid, ip="8.8.8.8", ports=[], sources=["tshark"]))  # fuera de alcance
        for i, (proto, pk) in enumerate((("Modbus/TCP", 6), ("HTTP", 2), ("Modbus/TCP", 4))):
            from datetime import datetime, timezone
            from app.models import Capture, Flow
            if i == 0:
                cap = Capture(campaign_id=cid, filename="a.pcap", path="x", sha256="a" * 64, size=1, status="analyzed")
                db.add(cap)
                db.flush()
            now = datetime.now(timezone.utc)
            db.add(Flow(campaign_id=cid, capture_id=cap.id, src_ip="10.0.0.2", dst_ip="10.0.0.5", transport="tcp", port=500 + i, protocol=proto, packets=pk, bytes=1, first_seen=now, last_seen=now))
        for n in range(8):
            db.add(ToolRun(campaign_id=cid, server="nmap", tool="nmap_scan", arguments={"n": n}, status="succeeded" if n % 2 else "failed"))
        db.commit()
    s = client.get(f"/api/campaigns/{cid}/summary").json()
    assert s["counts"] == {"assets": 2, "assets_out_of_scope": 1, "flows": 3, "captures": 1, "evidence": 1, "runs": 8, "findings": 3}
    assert s["findings_by_rating"]["High"] == 1 and s["findings_by_rating"]["Medium"] == 1 and sum(s["findings_by_rating"].values()) == 2  # el falso positivo no cuenta
    assert s["findings_by_status"] == {"draft": 1, "confirmed": 1, "false_positive": 1} and s["findings_by_phase"]["discovery"] == 0
    assert s["protocols"] == [{"protocol": "Modbus/TCP", "packets": 10, "flows": 2}, {"protocol": "HTTP", "packets": 2, "flows": 1}]
    assert s["runs_by_status"] == {"succeeded": 4, "failed": 4}
    assert [r["id"] for r in s["recent_runs"]] == sorted([r["id"] for r in s["recent_runs"]], reverse=True) and len(s["recent_runs"]) == 6
    assert [r["kind"] for r in s["scope"]["rules"]] == ["cidr", "hostname"] and s["scope"]["changes"] == 1
    assert s["report_warnings"] > 0
    assert client.get("/api/campaigns/999/summary").status_code == 404
