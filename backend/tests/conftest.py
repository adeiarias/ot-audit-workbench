import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["AUDIT_DATA_DIR"] = _tmp
os.environ["AUDIT_ALLOWED_HOSTS"] = "127.0.0.1,localhost,testserver"
os.environ["AUDIT_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import shutil  # noqa: E402

from app.db import CAPTURES_ROOT, Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    shutil.rmtree(CAPTURES_ROOT, ignore_errors=True)  # los ids de campaña se reinician en cada test
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------- LLM falso (sin red, sin clave)
import copy  # noqa: E402

from app import mcp_client  # noqa: E402
from app.llm import agent as _agent  # noqa: E402
from app.llm import client as _llm_client  # noqa: E402

MCP_TOOLS = [
    {"server": "nmap", "tool": "nmap_scan", "description": "nmap", "target_arg": "target", "active": True, "internal": False,
     "input_schema": {"type": "object", "properties": {"target": {"type": "string"}, "profile": {"type": "string"}}, "required": ["target"]}},
    {"server": "modbus", "tool": "modbus_read", "description": "modbus", "target_arg": "host", "active": True, "internal": False,
     "input_schema": {"type": "object", "properties": {"host": {"type": "string"}}, "required": ["host"]}},
]


def _resolve(obj):
    if callable(obj):
        return obj()
    if isinstance(obj, list):
        return [_resolve(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _resolve(v) for k, v in obj.items()}
    return obj


class FakeLLM:
    def __init__(self):
        self.queue, self.calls = [], []

    def say(self, text, thinking=False):
        content = ([{"type": "thinking", "thinking": "", "signature": "sig-abc"}] if thinking else []) + [{"type": "text", "text": text}]
        self.queue.append(_llm_client.LLMResponse(content=content, stop_reason="end_turn"))

    def use(self, *tools, text="Voy a consultarlo.", thinking=True):
        content = ([{"type": "thinking", "thinking": "", "signature": "sig-xyz"}] if thinking else []) + [{"type": "text", "text": text}]
        for i, (name, args) in enumerate(tools):
            content.append({"type": "tool_use", "id": f"toolu_{len(self.calls)}_{len(self.queue)}_{i}", "name": name, "input": args})
        self.queue.append(_llm_client.LLMResponse(content=content, stop_reason="tool_use"))

    def refuse(self, category="cyber"):
        self.queue.append(_llm_client.LLMResponse(content=[], stop_reason="refusal", refusal_category=category))

    def fail(self, exc):
        self.queue.append(exc)

    async def create_message(self, system, messages, tools, settings=None):
        self.calls.append(copy.deepcopy({"system": system, "messages": messages, "tools": tools}))
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        item.content = _resolve(item.content)  # permite valores perezosos (callables) que dependen del mapa de seudónimos
        return item


@pytest.fixture()
def llm(client, monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(_llm_client, "create_message", fake.create_message)
    monkeypatch.setattr(_llm_client, "configured", lambda *a, **k: True)

    async def fake_list_tools():
        return MCP_TOOLS
    monkeypatch.setattr(mcp_client, "list_tools", fake_list_tools)
    monkeypatch.setattr(_agent, "_mcp_cache", None)
    _agent._busy.clear()
    return fake
