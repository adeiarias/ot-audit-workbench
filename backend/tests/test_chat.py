import json
import re
import time

import pytest

from app import mcp_client
from app.db import SessionLocal
from app.llm import agent
from app.models import AgentCall, Asset, RedactionMap, ToolRun
from tests.fixtures_nmap import NMAP_XML

SCOPE = "10.0.0.0/24\nplc.corp"


@pytest.fixture()
def cid(client):
    return mk(client)


def mk(client, **kw):
    body = {"name": "Planta", "audit_type": "OT", "start_date": "2026-11-14", "scope": SCOPE, "llm_enabled": True, **kw}
    r = client.post("/api/campaigns", json=body)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    with SessionLocal() as db:
        db.add(Asset(campaign_id=cid, ip="10.0.0.5", hostname="plc.corp", mac="00:11:22:33:44:05", vendor="Siemens",
                     ports=[{"port": 502, "proto": "tcp", "service": "modbus"}], sources=["nmap"]))
        db.commit()
    return cid


def tok(real):
    """Seudónimo asignado a un valor real (se evalúa de forma perezosa, cuando el mensaje ya se envió)."""
    def f():
        with SessionLocal() as db:
            return db.query(RedactionMap).filter_by(real=real).one().token
    return f


def chat(client, cid):
    return client.get(f"/api/campaigns/{cid}/chat").json()


def send(client, cid, text):
    r = client.post(f"/api/campaigns/{cid}/chat", json={"message": text})
    assert r.status_code == 202, r.text
    return wait_idle(client, cid)


def wait_idle(client, cid, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        c = chat(client, cid)
        if not c["busy"]:
            return c
        time.sleep(0.05)
    raise AssertionError("el agente no terminó")


def wait_run_done(client, cid, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        c = chat(client, cid)
        if not c["busy"] and not any(x["status"] == "running" for m in c["messages"] for x in m["calls"]):
            return c
        time.sleep(0.05)
    raise AssertionError("la ejecución no terminó")


def sent_text(call) -> str:
    return json.dumps(call, ensure_ascii=False)


# ---------------------------------------------------------------- puertas de acceso

def test_gating(client, monkeypatch):
    off = client.post("/api/campaigns", json={"name": "x", "audit_type": "OT", "start_date": "2026-11-14", "scope": SCOPE}).json()["id"]
    assert client.post(f"/api/campaigns/{off}/chat", json={"message": "hola"}).status_code == 403  # LLM desactivado por defecto
    c = mk(client)
    from app.llm import client as llm_client
    monkeypatch.setattr(llm_client, "configured", lambda *a, **k: False)
    r = client.post(f"/api/campaigns/{c}/chat", json={"message": "hola"})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    assert client.post(f"/api/campaigns/{c}/chat", json={"message": ""}).status_code == 422
    assert client.get("/api/llm/status").json()["model"] == "claude-opus-5-5"


# ---------------------------------------------------------------- anonimización extremo a extremo

def test_nothing_real_leaves_and_answer_is_restored(client, cid, llm):
    llm.say(lambda: f"El host {tok('10.0.0.5')()} ({tok('plc.corp')()}) expone Modbus.")
    c = send(client, cid, "¿Qué hace 10.0.0.5 (plc.corp, mac 00:11:22:33:44:05)? password=hunter2")
    payload = sent_text(llm.calls[0])
    for secret in ("10.0.0.5", "10.0.0.0/24", "plc.corp", "00:11:22:33:44:05", "hunter2"):
        assert secret not in payload, secret
    assert re.search(r"IP-\d{4}", payload) and re.search(r"NET-\d{4}", payload) and re.search(r"HOST-\d{4}", payload)
    assert "Siemens" in payload  # lo no sensible se conserva
    assert llm.calls[0]["system"] == agent.SYSTEM_PROMPT
    names = {t["name"] for t in llm.calls[0]["tools"]}
    assert {"get_assets", "get_finding", "nmap_scan", "modbus_read"} <= names
    assert c["messages"][0] == {"id": c["messages"][0]["id"], "role": "user", "text": "¿Qué hace 10.0.0.5 (plc.corp, mac 00:11:22:33:44:05)? password=hunter2", "calls": []}
    assert c["messages"][1]["text"] == "El host 10.0.0.5 (plc.corp) expone Modbus."


def test_redaction_can_be_disabled_per_campaign(client, llm):
    cid = mk(client, llm_redaction=False)
    llm.say("ok")
    send(client, cid, "analiza 10.0.0.5")
    payload = sent_text(llm.calls[0]["messages"])  # (el prompt del sistema cita "IP-0001" como ejemplo)
    assert "10.0.0.5" in payload and not re.search(r"IP-\d{4}", payload)


def test_history_is_replayed_verbatim_append_only(client, cid, llm):
    llm.say("primera", thinking=True)
    llm.say("segunda")
    send(client, cid, "uno")
    send(client, cid, "dos")
    first, second = llm.calls
    assert second["messages"][: len(first["messages"])] == first["messages"]  # prefijo idéntico
    assistant = second["messages"][1]
    assert assistant["role"] == "assistant" and assistant["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig-abc"}
    assert len(second["messages"]) == 3
    assert "campaign_context" not in sent_text(second["messages"][2])  # la instantánea solo va en el primer mensaje


# ---------------------------------------------------------------- herramientas de lectura

def test_read_tool_results_are_redacted_and_sent_back(client, cid, llm):
    llm.use(("get_assets", {}))
    llm.say("Hay un activo.")
    c = send(client, cid, "lista activos")
    second = llm.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    block = second[2]["content"][0]
    assert block["type"] == "tool_result" and block["is_error"] is False and block["tool_use_id"].startswith("toolu_")
    assert "10.0.0.5" not in block["content"] and "plc.corp" not in block["content"] and "00:11:22:33:44:05" not in block["content"]
    assert "Siemens" in block["content"]
    call = c["messages"][1]["calls"][0]
    assert call["status"] == "done" and call["requires_approval"] is False
    assert "10.0.0.5" in call["result_preview"]  # la UI local sí ve los valores reales
    assert c["messages"][-1]["text"] == "Hay un activo."


def test_run_output_secrets_are_masked(client, cid, llm):
    with SessionLocal() as db:
        run = ToolRun(campaign_id=cid, server="nmap", tool="nmap_scan", arguments={}, output="snmp community: public\nlogin password=hunter2 en 10.0.0.5")
        db.add(run)
        db.commit()
        run_id = run.id
    llm.use(("get_run_output", {"run_id": run_id}))
    llm.say("visto")
    send(client, cid, "mira el run")
    content = llm.calls[1]["messages"][2]["content"][0]["content"]
    assert "hunter2" not in content and "public" not in content and "10.0.0.5" not in content and "[REDACTED]" in content


# ---------------------------------------------------------------- aprobación humana

def test_active_tool_requires_approval_then_runs_and_resumes(client, cid, llm, monkeypatch):
    executed = []

    async def fake_call(server, tool, args):
        executed.append((server, tool, dict(args)))
        return NMAP_XML
    monkeypatch.setattr(mcp_client, "call_tool", fake_call)

    llm.use(("nmap_scan", {"target": tok("10.0.0.5"), "profile": "ping"}), text="Propongo un ping.")
    llm.say("Tienes el puerto 502 abierto.")
    c = send(client, cid, "escanea el PLC")
    call = c["messages"][1]["calls"][0]
    assert call["status"] == "pending" and call["requires_approval"] is True
    assert call["input"] == {"target": "10.0.0.5", "profile": "ping"}  # la UI ve el valor REAL que se va a escanear
    assert executed == [] and len(llm.calls) == 1  # nada ejecutado, modelo no reanudado
    with SessionLocal() as db:
        assert db.query(ToolRun).count() == 0
    assert client.post(f"/api/campaigns/{cid}/chat", json={"message": "otra cosa"}).status_code == 409
    assert client.delete(f"/api/campaigns/{cid}/chat").status_code == 409

    assert client.post(f"/api/agent-calls/{call['id']}/approve").status_code == 200
    assert client.post(f"/api/agent-calls/{call['id']}/approve").status_code == 409  # no se aprueba dos veces
    c = wait_run_done(client, cid)

    assert executed == [("nmap", "nmap_scan", {"target": "10.0.0.5", "profile": "ping"})]  # el MCP recibió el valor real
    assert c["messages"][-1]["text"] == "Tienes el puerto 502 abierto." and c["messages"][1]["calls"][0]["status"] == "done"
    block = llm.calls[1]["messages"][2]["content"][0]
    assert block["type"] == "tool_result" and not block["is_error"]
    assert "10.0.0.5" not in sent_text(llm.calls[1]) and "plc1.local" not in sent_text(llm.calls[1])  # la salida llega seudonimizada
    with SessionLocal() as db:
        run = db.query(ToolRun).one()
        assert run.origin == "agent" and run.status.value == "succeeded"


def test_deny_never_executes(client, cid, llm, monkeypatch):
    async def boom(*a):
        raise AssertionError("no debe ejecutarse")
    monkeypatch.setattr(mcp_client, "call_tool", boom)
    llm.use(("nmap_scan", {"target": tok("10.0.0.5")}))
    llm.say("Entendido, no escaneo.")
    c = send(client, cid, "escanea")
    assert client.post(f"/api/agent-calls/{c['messages'][1]['calls'][0]['id']}/deny").status_code == 200
    c = wait_idle(client, cid)
    block = llm.calls[1]["messages"][2]["content"][0]
    assert block["is_error"] is True and "denegó" in block["content"]
    assert c["messages"][1]["calls"][0]["status"] == "denied" and c["messages"][-1]["text"] == "Entendido, no escaneo."
    with SessionLocal() as db:
        assert db.query(ToolRun).count() == 0


def test_out_of_scope_and_unknown_tools_are_refused_without_approval(client, cid, llm, monkeypatch):
    async def boom(*a):
        raise AssertionError("no debe ejecutarse")
    monkeypatch.setattr(mcp_client, "call_tool", boom)
    llm.use(("nmap_scan", {"target": "8.8.8.8"}), ("pcap_flows", {"path": "/etc/passwd"}), ("nmap_scan", {}))
    llm.say("De acuerdo.")
    c = send(client, cid, "escanea fuera")
    assert [x["status"] for x in c["messages"][1]["calls"]] == ["failed", "failed", "failed"]  # ninguna queda pendiente
    results = llm.calls[1]["messages"][2]["content"]
    assert len(results) == 3 and all(b["is_error"] for b in results)  # un único mensaje con los 3 resultados, en orden
    assert "fuera del alcance" in results[0]["content"] and "desconocida" in results[1]["content"]
    with SessionLocal() as db:
        assert db.query(ToolRun).count() == 0


def test_parallel_calls_wait_for_all_results(client, cid, llm, monkeypatch):
    async def fake_call(server, tool, args):
        return NMAP_XML
    monkeypatch.setattr(mcp_client, "call_tool", fake_call)
    llm.use(("get_assets", {}), ("nmap_scan", {"target": tok("10.0.0.5")}))
    llm.say("hecho")
    c = send(client, cid, "haz ambas")
    assert [x["status"] for x in c["messages"][1]["calls"]] == ["done", "pending"] and len(llm.calls) == 1
    client.post(f"/api/agent-calls/{c['messages'][1]['calls'][1]['id']}/approve")
    wait_run_done(client, cid)
    results = llm.calls[1]["messages"][2]["content"]
    asked = [b["id"] for b in llm.calls[1]["messages"][1]["content"] if b["type"] == "tool_use"]
    assert [b["tool_use_id"] for b in results] == asked  # mismos ids y mismo orden que las peticiones del modelo
    assert len(results) == 2 and len(llm.calls[1]["messages"]) == 3  # un solo mensaje user con ambos tool_result


def test_scope_is_rechecked_at_approval_time(client, cid, llm, monkeypatch):
    """Defensa en profundidad: aunque el alcance cambie por una vía que no invalida las acciones (aquí, directo en BD)."""
    async def boom(*a):
        raise AssertionError("no debe ejecutarse")
    monkeypatch.setattr(mcp_client, "call_tool", boom)
    llm.use(("nmap_scan", {"target": tok("10.0.0.5")}))
    llm.say("vale")
    c = send(client, cid, "escanea")
    from app.models import Campaign
    with SessionLocal() as db:
        db.get(Campaign, cid).scope = "192.168.0.0/24"
        db.commit()
    r = client.post(f"/api/agent-calls/{c['messages'][1]['calls'][0]['id']}/approve")
    assert r.status_code == 422
    c = wait_idle(client, cid)
    assert c["messages"][1]["calls"][0]["status"] == "failed" and llm.calls[1]["messages"][2]["content"][0]["is_error"]
    with SessionLocal() as db:
        assert db.query(ToolRun).count() == 0


def test_editing_scope_rejects_pending_actions_that_fall_outside(client, cid, llm, monkeypatch):
    async def boom(*a):
        raise AssertionError("no debe ejecutarse")
    monkeypatch.setattr(mcp_client, "call_tool", boom)
    llm.use(("nmap_scan", {"target": tok("10.0.0.5")}), ("modbus_read", {"host": tok("10.0.0.5")}))
    llm.say("entendido")
    c = send(client, cid, "haz ambas")
    assert [x["status"] for x in c["messages"][1]["calls"]] == ["pending", "pending"]
    # el auditor amplía el alcance con otra red pero quita la del PLC: ambas acciones quedan fuera
    assert client.patch(f"/api/campaigns/{cid}", json={"scope": "192.168.0.0/24\nplc.corp"}).status_code == 200
    calls = chat(client, cid)["messages"][1]["calls"]
    assert [x["status"] for x in calls] == ["failed", "failed"] and "dejó de estar dentro del alcance" in calls[0]["result_preview"]
    with SessionLocal() as db:
        assert db.query(ToolRun).count() == 0
    assert client.post(f"/api/agent-calls/{calls[0]['id']}/approve").status_code == 409  # ya no se puede aprobar
    # la conversación continúa: el siguiente mensaje primero salda los resultados fallidos
    send(client, cid, "sigamos")
    msgs = llm.calls[1]["messages"]
    assert [b["type"] for b in msgs[2]["content"]] == ["tool_result", "tool_result"] and all(b["is_error"] for b in msgs[2]["content"])
    assert msgs[3]["content"][0]["text"] == "sigamos"


# ---------------------------------------------------------------- robustez

def test_refusal_is_handled_and_conversation_continues(client, cid, llm):
    llm.refuse("cyber")
    llm.say("Mejor así.")
    c = send(client, cid, "dame un exploit")
    assert "rechazada" in c["messages"][1]["text"] and "cyber" in c["messages"][1]["text"] and not c["busy"]
    c = send(client, cid, "vale, dame un resumen")
    assert c["messages"][-1]["text"] == "Mejor así."
    roles = [m["role"] for m in llm.calls[1]["messages"]]
    assert roles == ["user", "assistant", "user"]


def test_api_error_is_reported_and_retry_works(client, cid, llm):
    llm.fail(RuntimeError("boom"))
    llm.say("ya funciona")
    c = send(client, cid, "hola")
    assert c["messages"][-1]["role"] == "error" and "boom" in c["messages"][-1]["text"]
    c = send(client, cid, "reintento")
    assert c["messages"][-1]["text"] == "ya funciona"
    assert [m["role"] for m in llm.calls[1]["messages"]] == ["user", "user"]  # el mensaje de error no se reenvía


def test_iteration_limit(client, cid, llm):
    for _ in range(agent.MAX_ITERATIONS + 2):
        llm.use(("get_assets", {}), thinking=False)
    c = send(client, cid, "bucle")
    assert len(llm.calls) == agent.MAX_ITERATIONS
    assert c["messages"][-1]["role"] == "error" and "límite" in c["messages"][-1]["text"]


def test_reset_chat_starts_fresh_with_new_snapshot(client, cid, llm):
    llm.say("a")
    llm.say("b")
    send(client, cid, "uno")
    assert client.delete(f"/api/campaigns/{cid}/chat").status_code == 204
    assert chat(client, cid)["messages"] == []
    send(client, cid, "dos")
    assert "campaign_context" in sent_text(llm.calls[1]["messages"][0])


def test_stale_running_call_is_settled_on_next_message(client, cid, llm, monkeypatch):
    llm.use(("nmap_scan", {"target": tok("10.0.0.5")}))
    llm.say("retomo")
    c = send(client, cid, "escanea")
    with SessionLocal() as db:  # simula: aprobada y ejecutándose cuando la app se reinició
        db.query(AgentCall).update({"status": "running"})
        db.commit()
    agent.fail_stale_calls()
    c = send(client, cid, "sigamos")
    msgs = llm.calls[1]["messages"]
    assert msgs[2]["content"][0]["type"] == "tool_result" and msgs[2]["content"][0]["is_error"]  # resultado pendiente saldado
    assert msgs[3]["content"][0]["text"] == "sigamos"
