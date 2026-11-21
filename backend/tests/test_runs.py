import asyncio
import json
import struct
import time

import pytest

from app import mcp_client
from tests.fixtures_nmap import NMAP_XML

CAMP = {"name": "Planta", "audit_type": "OT", "start_date": "2026-11-14", "scope": "10.0.0.0/24\n127.0.0.1"}


def _wait(client, cid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        runs = client.get(f"/api/campaigns/{cid}/runs").json()
        if runs and runs[0]["status"] != "running":
            return runs[0]
        time.sleep(0.1)
    raise AssertionError("run no terminó")


def test_scope_and_allowlist_enforced(client):
    cid = client.post("/api/campaigns", json=CAMP).json()["id"]
    r = client.post(f"/api/campaigns/{cid}/runs", json={"server": "nmap", "tool": "nmap_scan", "arguments": {"target": "8.8.8.8"}})
    assert r.status_code == 403
    r = client.post(f"/api/campaigns/{cid}/runs", json={"server": "nmap", "tool": "nmap_scan", "arguments": {}})
    assert r.status_code == 403
    r = client.post(f"/api/campaigns/{cid}/runs", json={"server": "nmap", "tool": "otra", "arguments": {"target": "10.0.0.1"}})
    assert r.status_code == 403
    assert client.get(f"/api/campaigns/{cid}/runs").json() == []


def test_nmap_run_creates_assets(client, monkeypatch):
    async def fake(server, tool, args):
        return NMAP_XML
    monkeypatch.setattr(mcp_client, "call_tool", fake)
    cid = client.post("/api/campaigns", json=CAMP).json()["id"]
    r = client.post(f"/api/campaigns/{cid}/runs", json={"server": "nmap", "tool": "nmap_scan", "arguments": {"target": "10.0.0.0/24"}})
    assert r.status_code == 201
    run = _wait(client, cid)
    assert run["status"] == "succeeded"
    assets = client.get(f"/api/campaigns/{cid}/assets").json()
    assert len(assets) == 1  # el host 'down' se ignora
    a = assets[0]
    assert a["ip"] == "10.0.0.5" and a["hostname"] == "plc1.local" and a["vendor"] == "Rockwell"
    assert [p["port"] for p in a["ports"]] == [80, 502]  # el puerto cerrado no aparece


def test_failed_run_is_recorded(client, monkeypatch):
    async def boom(server, tool, args):
        raise mcp_client.McpToolError("fallo simulado")
    monkeypatch.setattr(mcp_client, "call_tool", boom)
    cid = client.post("/api/campaigns", json=CAMP).json()["id"]
    client.post(f"/api/campaigns/{cid}/runs", json={"server": "nmap", "tool": "nmap_scan", "arguments": {"target": "10.0.0.1"}})
    run = _wait(client, cid)
    assert run["status"] == "failed" and "fallo simulado" in run["error"]


async def _fake_modbus(reader, writer):
    header = await reader.readexactly(7)
    tid, _, _, unit = struct.unpack(">HHHB", header)
    pdu = await reader.readexactly(5)
    fc, addr, count = struct.unpack(">BHH", pdu)
    if addr >= 100:  # excepción ILLEGAL_DATA_ADDRESS
        resp = bytes([fc | 0x80, 2])
    else:
        data = struct.pack(f">{count}H", *range(addr, addr + count))
        resp = bytes([fc, len(data)]) + data
    writer.write(struct.pack(">HHHB", tid, 0, len(resp) + 1, unit) + resp)
    await writer.drain()
    writer.close()


def test_modbus_end_to_end_through_mcp(client):
    """Servidor Modbus falso + servidor MCP real (subproceso) + orquestador + parser."""
    import threading

    started = threading.Event()
    box = {}

    def serve():
        loop = asyncio.new_event_loop()
        server = loop.run_until_complete(asyncio.start_server(_fake_modbus, "127.0.0.1", 0))
        box["port"], box["loop"], box["server"] = server.sockets[0].getsockname()[1], loop, server
        started.set()
        loop.run_forever()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    started.wait(5)
    try:
        cid = client.post("/api/campaigns", json=CAMP).json()["id"]
        args = {"host": "127.0.0.1", "address": 10, "count": 3, "port": box["port"]}
        client.post(f"/api/campaigns/{cid}/runs", json={"server": "modbus", "tool": "modbus_read", "arguments": args})
        run = _wait(client, cid)
        assert run["status"] == "succeeded", run["error"]
        out = json.loads(run["output"])
        assert out["ok"] and out["values"] == [10, 11, 12]
        asset = client.get(f"/api/campaigns/{cid}/assets").json()[0]
        assert asset["ip"] == "127.0.0.1" and asset["sources"] == ["modbus"]
        assert asset["ports"][0]["service"] == "modbus"

        # Excepción Modbus: sigue contando como servicio Modbus detectado
        client.post(f"/api/campaigns/{cid}/runs", json={"server": "modbus", "tool": "modbus_read", "arguments": {**args, "address": 200}})
        time.sleep(0.2)
        run = _wait(client, cid)
        assert json.loads(run["output"])["exception"] == "ILLEGAL_DATA_ADDRESS"
    finally:
        box["loop"].call_soon_threadsafe(box["loop"].stop)


@pytest.mark.skipif(__import__("shutil").which("nmap") is None, reason="nmap no instalado")
def test_nmap_real_ping_localhost(client):
    cid = client.post("/api/campaigns", json=CAMP).json()["id"]
    client.post(f"/api/campaigns/{cid}/runs", json={"server": "nmap", "tool": "nmap_scan", "arguments": {"target": "127.0.0.1", "profile": "ping"}})
    run = _wait(client, cid)
    assert run["status"] == "succeeded", run["error"]
    assert client.get(f"/api/campaigns/{cid}/assets").json()[0]["ip"] == "127.0.0.1"


def test_tools_listing(client):
    tools = client.get("/api/tools").json()
    assert {(t["server"], t["tool"]) for t in tools} == {("nmap", "nmap_scan"), ("modbus", "modbus_read")}
    assert all("properties" in t["input_schema"] for t in tools)


def test_real_tool_error_message_reaches_the_run(client):
    """Con servidores MCP reales: el motivo del fallo llega al usuario (no 'ExceptionGroup')."""
    cid = client.post("/api/campaigns", json=CAMP).json()["id"]
    client.post(f"/api/campaigns/{cid}/runs", json={"server": "modbus", "tool": "modbus_read", "arguments": {"host": "127.0.0.1", "port": 1}})
    run = _wait(client, cid)
    assert run["status"] == "failed"
    assert "No se pudo leer de 127.0.0.1:1" in run["error"], run["error"]
    assert "ExceptionGroup" not in run["error"]

    client.post(f"/api/campaigns/{cid}/runs", json={"server": "modbus", "tool": "modbus_read", "arguments": {"host": "127.0.0.1", "count": 500}})
    time.sleep(0.2)
    run = _wait(client, cid)
    assert "count debe estar entre 1 y 100" in run["error"], run["error"]
