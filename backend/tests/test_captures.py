import signal
import time
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from app import mcp_client
from tests.pcap_factory import demo_pcap

CAMP = {"name": "Planta", "audit_type": "OT", "start_date": "2026-11-14", "scope": "10.0.0.0/24"}


def _upload(client, cid, data=None, name="demo.pcap"):
    return client.post(f"/api/campaigns/{cid}/captures", files={"file": (name, data if data is not None else demo_pcap())})


def _wait_capture(client, cid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        caps = client.get(f"/api/campaigns/{cid}/captures").json()
        if caps and caps[0]["status"] != "analyzing":
            return caps[0]
        time.sleep(0.1)
    raise AssertionError("análisis no terminó")


@pytest.fixture()
def cid(client):
    return client.post("/api/campaigns", json=CAMP).json()["id"]


def test_upload_analyze_and_graph(client, cid):
    r = _upload(client, cid)
    assert r.status_code == 201, r.text
    cap = _wait_capture(client, cid)
    assert cap["status"] == "analyzed", cap["error"]
    assert cap["packets"] == 12 and cap["non_ip_packets"] == 2

    g = client.get(f"/api/campaigns/{cid}/graph").json()
    nodes = {n["ip"]: n for n in g["nodes"]}
    assert set(nodes) == {"10.0.0.2", "10.0.0.5", "8.8.8.8", "224.0.0.251"}
    assert nodes["10.0.0.5"]["is_asset"] and nodes["10.0.0.5"]["mac"] == "00:11:22:33:44:05"  # MAC por ARP
    assert nodes["10.0.0.2"]["is_asset"] and nodes["10.0.0.2"]["mac"] == ""  # sin ARP: no se infiere de eth.src
    assert not nodes["8.8.8.8"]["in_scope"] and not nodes["8.8.8.8"]["is_asset"]  # fuera de alcance: no es activo
    assert nodes["224.0.0.251"]["kind"] == "multicast" and not nodes["224.0.0.251"]["is_asset"]

    edges = {(e["src"], e["dst"], e["port"]): e for e in g["edges"]}
    modbus = edges[("10.0.0.2", "10.0.0.5", 502)]
    assert modbus["protocol"] == "Modbus/TCP" and modbus["packets"] == 6 and modbus["transport"] == "tcp"
    assert edges[("10.0.0.2", "8.8.8.8", 53)]["protocol"] == "DNS"

    assets = {a["ip"] for a in client.get(f"/api/campaigns/{cid}/assets").json()}
    assert assets == {"10.0.0.2", "10.0.0.5"}


def test_duplicate_and_invalid_uploads(client, cid):
    assert _upload(client, cid).status_code == 201
    assert _upload(client, cid).status_code == 409
    assert _upload(client, cid, data=b"esto no es un pcap", name="x.pcap").status_code == 422
    assert len(client.get(f"/api/campaigns/{cid}/captures").json()) == 1
    leftovers = list((mcp_client.CAPTURES_ROOT / str(cid) / "pcaps").glob(".upload-*"))
    assert leftovers == []  # no quedan temporales


def test_reanalyze_does_not_duplicate_flows(client, cid):
    capture_id = _upload(client, cid).json()["id"]
    _wait_capture(client, cid)
    before = client.get(f"/api/campaigns/{cid}/graph").json()["edges"]
    assert client.post(f"/api/captures/{capture_id}/reanalyze").status_code == 200
    time.sleep(0.2)
    _wait_capture(client, cid)
    assert client.get(f"/api/campaigns/{cid}/graph").json()["edges"] == before


def test_delete_capture_keeps_assets_removes_flows_and_file(client, cid):
    r = _upload(client, cid).json()
    _wait_capture(client, cid)
    path = next((mcp_client.CAPTURES_ROOT / str(cid) / "pcaps").glob("*.pcap"))
    assert client.delete(f"/api/captures/{r['id']}").status_code == 204
    assert not path.exists()
    assert client.get(f"/api/campaigns/{cid}/graph").json()["edges"] == []
    assert len(client.get(f"/api/campaigns/{cid}/assets").json()) == 2


def test_delete_campaign_removes_files(client, cid):
    _upload(client, cid)
    _wait_capture(client, cid)
    directory = mcp_client.CAPTURES_ROOT / str(cid)
    assert directory.exists()
    client.delete(f"/api/campaigns/{cid}")
    assert not directory.exists()


def test_internal_tool_not_exposed_or_runnable(client, cid):
    assert all(t["tool"] != "pcap_flows" for t in client.get("/api/tools").json())
    r = client.post(f"/api/campaigns/{cid}/runs", json={"server": "tshark", "tool": "pcap_flows", "arguments": {"path": "/etc/passwd"}})
    assert r.status_code == 403


def test_tshark_server_refuses_paths_outside_captures_root():
    import asyncio

    for bad in ("/etc/passwd", str(mcp_client.CAPTURES_ROOT / ".." / "audit.db"), "../../etc/hosts"):
        with pytest.raises(mcp_client.McpToolError, match="fuera del directorio|No es un fichero"):
            asyncio.run(mcp_client.call_tool("tshark", "pcap_flows", {"path": bad}))


def test_failed_analysis_marks_capture_failed(client, cid, monkeypatch):
    async def boom(server, tool, args):
        raise mcp_client.McpToolError("tshark roto")
    monkeypatch.setattr(mcp_client, "call_tool", boom)
    _upload(client, cid)
    cap = _wait_capture(client, cid)
    assert cap["status"] == "failed" and "tshark roto" in cap["error"]


def test_websocket_pushes_change_after_analysis(client, cid):
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(AssertionError("sin evento en 30 s")))
    signal.alarm(30)
    try:
        with client.websocket_connect(f"/api/campaigns/{cid}/ws", headers={"origin": "http://127.0.0.1:5173"}) as ws:
            _upload(client, cid)
            assert ws.receive_json()["type"] == "changed"
    finally:
        signal.alarm(0)


def test_origin_and_host_guards(client, cid):
    evil = {"origin": "http://evil.example"}
    assert client.post("/api/campaigns", json=CAMP, headers=evil).status_code == 403
    assert _upload(client, cid, data=b"x").status_code == 422  # sin Origin: llega a la validación
    assert client.post("/api/campaigns", json=CAMP, headers={"origin": "http://127.0.0.1:5173"}).status_code == 201
    assert client.get("/api/campaigns", headers={"host": "evil.example"}).status_code == 400  # DNS rebinding
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/campaigns/{cid}/ws", headers=evil):
            pass
