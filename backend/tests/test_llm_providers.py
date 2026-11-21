import asyncio
import json
import sqlite3

import httpx
import pytest
from sqlalchemy import create_engine, text

from app import mcp_client, migrations
from app.db import SessionLocal
from app.llm import agent, client
from app.llm import openai_compat as oc
from app.models import ChatMessage
from tests.conftest import MCP_TOOLS
from tests.test_chat import chat, mk, wait_idle

ENV = ["AUDIT_LLM_PROVIDER", "AUDIT_LLM_MODEL", "AUDIT_LLM_BASE_URL", "AUDIT_LLM_API_KEY", "AUDIT_LLM_EFFORT", "AUDIT_LLM_MAX_TOKENS", "AUDIT_LLM_TOOLS",
       "AUDIT_LLM_PASS_REASONING", "AUDIT_LLM_EXTRA_BODY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "DEEPSEEK_API_KEY", "LITELLM_API_KEY",
       "LITELLM_MASTER_KEY", "OPENAI_API_KEY"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for v in ENV:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)  # sin ~/.config/anthropic del equipo real


def env(monkeypatch, **kw):
    for k, v in kw.items():
        monkeypatch.setenv(k, v)
    return client.settings()


# ---------------------------------------------------------------- configuración

def test_settings_defaults_and_problems(monkeypatch):
    s = client.settings()
    assert (s.provider, s.model, s.external) == ("anthropic", "claude-opus-5-5", True) and "ANTHROPIC_API_KEY" in client.problem()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    assert client.problem() is None and client.configured()

    s = env(monkeypatch, AUDIT_LLM_PROVIDER="deepseek", ANTHROPIC_API_KEY="")
    assert (s.model, s.base_url, s.pass_reasoning, s.external) == ("deepseek-flash", "https://api.deepseek.com", True, True)
    assert s.label == "DeepSeek (api.deepseek.com)" and "DEEPSEEK_API_KEY" in client.problem()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
    assert client.problem() is None and client.settings().api_key == "sk-ds"

    s = env(monkeypatch, AUDIT_LLM_PROVIDER="litellm")
    assert s.base_url == "http://localhost:4000" and not s.external and not s.pass_reasoning and "AUDIT_LLM_MODEL" in client.problem()
    monkeypatch.setenv("AUDIT_LLM_MODEL", "mi-alias")
    assert client.problem() is None  # la clave es opcional en LiteLLM sin virtual keys

    s = env(monkeypatch, AUDIT_LLM_PROVIDER="openai", AUDIT_LLM_MODEL="llama3", AUDIT_LLM_BASE_URL="")
    assert "AUDIT_LLM_BASE_URL" in client.problem()
    for url, external in (("http://192.168.1.50:8080/v1", False), ("http://127.0.0.1:11434/v1", False), ("http://litellm:4000", False),
                          ("http://gw.corp.local:4000", False), ("https://api.openai.com/v1", True), ("http://8.8.8.8:80", True)):
        monkeypatch.setenv("AUDIT_LLM_BASE_URL", url)
        assert client.settings().external is external, url
        assert client.problem() is None
    monkeypatch.setenv("AUDIT_LLM_BASE_URL", "ftp://x/y")
    assert "URL http(s)" in client.problem()
    monkeypatch.setenv("AUDIT_LLM_PROVIDER", "grok")
    assert "no es válido" in client.problem() and not client.configured()


def test_optional_knobs(monkeypatch):
    s = env(monkeypatch, AUDIT_LLM_PROVIDER="litellm", AUDIT_LLM_TOOLS="0", AUDIT_LLM_PASS_REASONING="1", AUDIT_LLM_MAX_TOKENS="zzz",
            AUDIT_LLM_EXTRA_BODY="{rota", AUDIT_LLM_EFFORT="max")
    assert (s.tools, s.pass_reasoning, s.max_tokens, s.extra_body, s.effort) == (False, True, 8192, {}, "max")
    s = env(monkeypatch, AUDIT_LLM_EXTRA_BODY='{"thinking": {"type": "disabled"}}', AUDIT_LLM_PASS_REASONING="0", AUDIT_LLM_PROVIDER="deepseek")
    assert s.extra_body == {"thinking": {"type": "disabled"}} and s.pass_reasoning is False


# ---------------------------------------------------------------- conversión

CONVO = [
    {"role": "user", "content": [{"type": "text", "text": "hola"}]},
    {"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "s"}, {"type": "reasoning", "text": "pienso"}, {"type": "text", "text": "voy"},
                                      {"type": "tool_use", "id": "c1", "name": "get_assets", "input": {}}, {"type": "tool_use", "id": "c2", "name": "nmap_scan", "input": {"target": "IP-0001"}}]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "[]", "is_error": False}, {"type": "tool_result", "tool_use_id": "c2", "content": "fuera", "is_error": True}]},
    {"role": "assistant", "content": [{"type": "tool_use", "id": "c3", "name": "get_assets", "input": {}}]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c3", "content": "[]"}, {"type": "text", "text": "sigue"}]},
]


def test_to_openai_messages():
    out = oc.to_openai_messages("SYS", CONVO, pass_reasoning=False)
    assert out == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "voy", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "get_assets", "arguments": "{}"}},
            {"id": "c2", "type": "function", "function": {"name": "nmap_scan", "arguments": '{"target": "IP-0001"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "[]"},
        {"role": "tool", "tool_call_id": "c2", "content": "ERROR: fuera"},  # OpenAI no tiene is_error
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c3", "type": "function", "function": {"name": "get_assets", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c3", "content": "[]"},
        {"role": "user", "content": "sigue"},
    ]  # el bloque thinking de Claude nunca se envía
    with_r = oc.to_openai_messages("SYS", CONVO, pass_reasoning=True)
    assert with_r[2]["reasoning_content"] == "pienso" and with_r[5]["reasoning_content"] == ""  # todos los turnos assistant llevan el campo
    assert json.dumps(CONVO) == json.dumps(CONVO)  # (la conversión no muta la entrada, comprobado abajo)
    before = json.dumps(CONVO)
    oc.to_openai_messages("S", CONVO, True)
    assert json.dumps(CONVO) == before


def test_tools_conversion():
    schema = {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}
    t = oc.to_openai_tools([{"name": "nmap_scan", "description": "nmap", "input_schema": schema}])
    assert t == [{"type": "function", "function": {"name": "nmap_scan", "description": "nmap", "parameters": schema}}]


def resp(message, finish="stop", usage=None):
    return {"choices": [{"message": message, "finish_reason": finish}], "usage": usage or {}}


def test_from_openai_response():
    r = oc.from_openai_response(resp({"content": "hola", "reasoning_content": "piensa"}), keep_reasoning=True)
    assert r.content == [{"type": "reasoning", "text": "piensa"}, {"type": "text", "text": "hola"}] and r.stop_reason == "end_turn"
    assert oc.from_openai_response(resp({"content": "hola", "reasoning_content": "piensa"}), False).content == [{"type": "text", "text": "hola"}]
    calls = {"content": None, "tool_calls": [{"id": "x1", "type": "function", "function": {"name": "get_assets", "arguments": '{"a": 1}'}},
                                              {"function": {"name": "get_flows", "arguments": ""}},  # sin id y sin argumentos
                                              {"id": "x3", "function": {"name": "get_finding", "arguments": "{no json"}},
                                              {"id": "x4", "function": {"name": "get_finding", "arguments": "[1,2]"}}]}
    r = oc.from_openai_response(resp(calls, finish="stop"), False)  # algunos backends dicen "stop" aunque haya tool_calls
    assert r.stop_reason == "tool_use"
    uses = r.content
    assert uses[0] == {"type": "tool_use", "id": "x1", "name": "get_assets", "input": {"a": 1}}
    assert uses[1]["id"].startswith("call_") and uses[1]["input"] == {}
    assert uses[2]["input"] == {oc.INVALID_ARGS: "{no json"} and uses[3]["input"] == {oc.INVALID_ARGS: "[1,2]"}
    assert oc.from_openai_response(resp({"content": "x"}, "length"), False).stop_reason == "max_tokens"
    r = oc.from_openai_response(resp({"content": ""}, "content_filter"), False)
    assert (r.stop_reason, r.refusal_category) == ("refusal", "content_filter")
    with pytest.raises(oc.LLMError):
        oc.from_openai_response({"error": "x"}, False)


# ---------------------------------------------------------------- HTTP

class Server:
    def __init__(self, *responses):
        self.queue, self.seen = list(responses), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body) if not isinstance(body, str) else httpx.Response(status, text=body)

    def body(self, i=-1):
        return json.loads(self.seen[i].content)


@pytest.fixture()
def server(monkeypatch):
    holder = {}

    def make(*responses):
        srv = Server(*responses)
        monkeypatch.setattr(oc, "_transport", httpx.MockTransport(srv))
        sleeps = []

        async def fake_sleep(n):
            sleeps.append(n)
        monkeypatch.setattr(oc, "_sleep", fake_sleep)
        srv.sleeps = sleeps
        holder["srv"] = srv
        return srv
    return make


def call(monkeypatch=None, tools=None, messages=None):
    return asyncio.run(client.create_message("SYS", messages or [{"role": "user", "content": [{"type": "text", "text": "hola"}]}], tools or []))


def test_request_shape_deepseek(monkeypatch, server):
    env(monkeypatch, AUDIT_LLM_PROVIDER="deepseek", DEEPSEEK_API_KEY="sk-ds-secret", AUDIT_LLM_EXTRA_BODY='{"thinking": {"type": "enabled"}}')
    srv = server((200, resp({"content": "ok", "reasoning_content": "r"})))
    r = call(tools=agent._api_tools(MCP_TOOLS))  # las herramientas tal como las ve el modelo (lectura + MCP)
    req = srv.seen[0]
    assert str(req.url) == "https://api.deepseek.com/chat/completions" and req.headers["authorization"] == "Bearer sk-ds-secret"
    b = srv.body()
    assert b["model"] == "deepseek-flash" and b["max_tokens"] == 8192 and b["reasoning_effort"] == "high" and b["thinking"] == {"type": "enabled"}
    assert b["tool_choice"] == "auto" and {t["function"]["name"] for t in b["tools"]} >= {"get_assets", "nmap_scan", "modbus_read"}
    assert b["messages"][0] == {"role": "system", "content": "SYS"}
    assert r.content == [{"type": "reasoning", "text": "r"}, {"type": "text", "text": "ok"}]


def test_request_shape_litellm_no_key_no_tools(monkeypatch, server):
    env(monkeypatch, AUDIT_LLM_PROVIDER="litellm", AUDIT_LLM_MODEL="mi-alias", AUDIT_LLM_BASE_URL="http://litellm:4000/")
    srv = server((200, resp({"content": "ok"})))
    call()
    assert str(srv.seen[0].url) == "http://litellm:4000/chat/completions" and "authorization" not in srv.seen[0].headers
    b = srv.body()
    assert "tools" not in b and "tool_choice" not in b and "reasoning_effort" not in b and b["model"] == "mi-alias"
    monkeypatch.setenv("AUDIT_LLM_TOOLS", "0")  # con AUDIT_LLM_TOOLS=0 no se envían herramientas aunque el agente las pida
    srv = server((200, resp({"content": "ok"})))
    call(tools=agent._api_tools(MCP_TOOLS))
    assert "tools" not in srv.body()


def test_http_errors_and_retries(monkeypatch, server):
    env(monkeypatch, AUDIT_LLM_PROVIDER="deepseek", DEEPSEEK_API_KEY="sk-ds-secret")
    srv = server((401, {"error": {"message": "bad key sk-ds-secret"}}))
    with pytest.raises(oc.LLMError, match="credenciales") as e:
        call()
    assert len(srv.seen) == 1  # 401 no se reintenta
    srv = server((429, "slow down"), (503, "overloaded"), (200, resp({"content": "por fin"})))
    assert call().content == [{"type": "text", "text": "por fin"}] and len(srv.seen) == 3 and srv.sleeps == [1, 3]
    srv = server((503, "a"), (503, "b"), (503, "c"))
    with pytest.raises(oc.LLMError, match="HTTP 503"):
        call()
    assert len(srv.seen) == 3
    srv = server((400, {"error": {"message": "tools not supported"}}))
    with pytest.raises(oc.LLMError, match="AUDIT_LLM_TOOLS=0"):
        call()
    assert len(srv.seen) == 1
    srv = server((404, "no model"))
    with pytest.raises(oc.LLMError, match="AUDIT_LLM_BASE_URL"):
        call()
    srv = server(httpx.ConnectError("boom"), httpx.ConnectError("boom"), httpx.ConnectError("boom"))
    with pytest.raises(oc.LLMError, match="no se pudo conectar con api.deepseek.com"):
        call()
    srv = server((200, "esto no es json"))
    with pytest.raises(oc.LLMError, match="no es JSON"):
        call()


# ---------------------------------------------------------------- chat de extremo a extremo con DeepSeek simulado

@pytest.fixture()
def deepseek_chat(client, monkeypatch, server):
    async def fake_list_tools():
        return MCP_TOOLS
    monkeypatch.setattr(mcp_client, "list_tools", fake_list_tools)
    monkeypatch.setattr(agent, "_mcp_cache", None)
    agent._busy.clear()
    env(monkeypatch, AUDIT_LLM_PROVIDER="deepseek", DEEPSEEK_API_KEY="sk-ds")
    return server


def tool_call(name, args, id_="call_1"):
    return {"content": "Consulto los datos.", "reasoning_content": "razono 1", "tool_calls": [{"id": id_, "type": "function", "function": {"name": name, "arguments": args}}]}


def test_chat_end_to_end_with_deepseek(client, deepseek_chat):
    cid = mk(client)
    srv = deepseek_chat((200, resp(tool_call("get_assets", "{}"), "tool_calls")), (200, resp({"content": "Hay un activo.", "reasoning_content": "razono 2"})),
                        (200, resp({"content": "Segunda respuesta.", "reasoning_content": "razono 3"})))
    r = client.post(f"/api/campaigns/{cid}/chat", json={"message": "¿qué hay en 10.0.0.5 (plc.corp)?"})
    assert r.status_code == 202
    c = wait_idle(client, cid)
    assert c["messages"][-1]["text"] == "Hay un activo." and c["provider"] == "deepseek" and c["external"] is True and c["model"] == "deepseek-flash"
    assert c["messages"][1]["calls"][0]["status"] == "done"

    first, second = srv.body(0), srv.body(1)
    assert "10.0.0.5" not in json.dumps(first) and "plc.corp" not in json.dumps(first)  # la anonimización aplica igual con este proveedor
    assert {t["function"]["name"] for t in first["tools"]} >= {"get_assets", "nmap_scan"}
    roles = [m["role"] for m in second["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert second["messages"][2]["reasoning_content"] == "razono 1" and second["messages"][2]["tool_calls"][0]["id"] == "call_1"  # exigido por DeepSeek con herramientas
    tool_msg = second["messages"][3]
    assert tool_msg["tool_call_id"] == "call_1" and "10.0.0.5" not in tool_msg["content"] and "Siemens" in tool_msg["content"]

    assert client.post(f"/api/campaigns/{cid}/chat", json={"message": "otra"}).status_code == 202
    wait_idle(client, cid)
    third = srv.body(2)
    assistants = [m for m in third["messages"] if m["role"] == "assistant"]
    assert [a["reasoning_content"] for a in assistants] == ["razono 1", "razono 2"]  # el razonamiento de TODOS los turnos previos viaja de vuelta
    with SessionLocal() as db:
        assert {m.provider for m in db.query(ChatMessage).filter_by(role="assistant")} == {"deepseek"}


def test_invalid_tool_arguments_become_an_error_result(client, deepseek_chat):
    cid = mk(client)
    srv = deepseek_chat((200, resp(tool_call("get_finding", "{no es json"), "tool_calls")), (200, resp({"content": "Reintento."})))
    client.post(f"/api/campaigns/{cid}/chat", json={"message": "mira"})
    c = wait_idle(client, cid)
    assert c["messages"][1]["calls"][0]["status"] == "failed"
    assert "JSON válido" in srv.body(1)["messages"][-1]["content"] and srv.body(1)["messages"][-1]["content"].startswith("ERROR: ")


def test_conversation_cannot_mix_providers(client, deepseek_chat, monkeypatch):
    cid = mk(client)
    deepseek_chat((200, resp({"content": "hola"})))
    client.post(f"/api/campaigns/{cid}/chat", json={"message": "uno"})
    wait_idle(client, cid)
    env(monkeypatch, AUDIT_LLM_PROVIDER="litellm", AUDIT_LLM_MODEL="x")  # el usuario cambia de proveedor y reinicia
    r = client.post(f"/api/campaigns/{cid}/chat", json={"message": "dos"})
    assert r.status_code == 409 and "deepseek" in r.json()["detail"] and "Nueva conversación" in r.json()["detail"]
    assert client.delete(f"/api/campaigns/{cid}/chat").status_code == 204
    srv = deepseek_chat((200, resp({"content": "desde litellm"})))
    assert client.post(f"/api/campaigns/{cid}/chat", json={"message": "tres"}).status_code == 202
    assert wait_idle(client, cid)["messages"][-1]["text"] == "desde litellm"
    assert "authorization" not in srv.seen[0].headers and str(srv.seen[0].url) == "http://localhost:4000/chat/completions"


def test_provider_error_is_shown_in_chat(client, deepseek_chat):
    cid = mk(client)
    deepseek_chat((401, {"error": "nope"}))
    client.post(f"/api/campaigns/{cid}/chat", json={"message": "hola"})
    last = wait_idle(client, cid)["messages"][-1]
    assert last["role"] == "error" and "deepseek" in last["text"] and "credenciales" in last["text"] and "sk-ds" not in last["text"]


def test_status_and_report_draft_with_openai_compatible(client, deepseek_chat, monkeypatch):
    env(monkeypatch, AUDIT_LLM_PROVIDER="litellm", AUDIT_LLM_MODEL="local-llama", AUDIT_LLM_BASE_URL="http://localhost:4000")
    st = client.get("/api/llm/status").json()
    assert (st["provider"], st["model"], st["external"], st["configured"], st["problem"]) == ("litellm", "local-llama", False, True, None)
    cid = client.post("/api/campaigns", json={"name": "Vending OT", "audit_type": "OT", "start_date": "2026-11-10", "scope": "10.0.0.0/24\nplc.corp", "llm_enabled": True}).json()["id"]
    from tests.test_report import seed
    seed(client, cid)
    client.put(f"/api/campaigns/{cid}/report", json={"test_type": "grey", "dut_name": "VM"})
    srv = deepseek_chat((200, resp({"content": "El estado actual presenta riesgo alto."})))
    r = client.post(f"/api/campaigns/{cid}/report/draft", json={"section": "conclusions"})
    assert r.status_code == 200 and r.json()["text"] == "El estado actual presenta riesgo alto."
    b = srv.body()
    assert "tools" not in b and b["messages"][0]["role"] == "system" and "Conclusiones" in b["messages"][0]["content"]
    assert "10.0.0.5" not in json.dumps(b)
    assert client.get(f"/api/campaigns/{cid}/report").json()["llm"]["provider_label"] == "LiteLLM (localhost:4000)"


def test_migration_adds_chat_provider_column(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, role TEXT)")
        c.execute("INSERT INTO chat_messages VALUES (1, 'assistant')")
    eng = create_engine(f"sqlite:///{path}")
    assert migrations.migrate(eng) == ["chat_messages.provider"]
    with eng.connect() as conn:
        assert conn.execute(text("SELECT provider FROM chat_messages")).scalar() == ""  # '' = anthropic (anterior)
