"""MCPs de terceros: manifiesto deny-by-default, confinamiento de capturas, entorno mínimo y servidores rotos."""
import json
import sys
import time
from pathlib import Path

import pytest

from app import mcp_client
from app.db import CAPTURES_ROOT, SessionLocal
from app.llm import agent
from app.models import Capture, ToolRun
from app.routers import runs as runs_router
from tests.test_chat import chat, mk, send

REAL_LIST_TOOLS = mcp_client.list_tools  # antes de que la fixture `llm` lo sustituya
FAKE = str(Path(__file__).parent / "fake_mcp_server.py")

MANIFEST = f"""
servers:
  fake3p:
    command: [{sys.executable!r}, {FAKE!r}]
    tools:
      pcap_info: {{active: false, capture_arg: pcap_file, allowed_args: [pcap_file, limit]}}
      host_probe: {{active: true, target_arg: host, allowed_args: [host]}}
"""


@pytest.fixture()
def ext(tmp_path, monkeypatch):
    path = tmp_path / "manifest.yaml"
    path.write_text(MANIFEST)
    monkeypatch.setenv("AUDIT_SECRET_TEST", "s3cr3t-de-la-app")
    mcp_client.load_manifest(path)
    runs_router._tools_cache = None
    yield path
    mcp_client.load_manifest(tmp_path / "no-existe.yaml")  # vuelve a los servidores propios
    runs_router._tools_cache = None


@pytest.fixture()
def cid(client):
    return client.post("/api/campaigns", json={"name": "P", "audit_type": "OT", "start_date": "2026-11-14", "scope": "10.0.0.0/24"}).json()["id"]


def add_capture(cid, name="a.pcap"):
    directory = CAPTURES_ROOT / str(cid) / "pcaps"
    directory.mkdir(parents=True, exist_ok=True)
    f = directory / name
    f.write_bytes(b"\xd4\xc3\xb2\xa1" + bytes(20))
    with SessionLocal() as db:
        cap = Capture(campaign_id=cid, filename=name, path=str(f), sha256=name, size=24, status="analyzed")
        db.add(cap)
        db.commit()
        return cap.id, str(f)


def wait_run(client, cid, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(f"/api/campaigns/{cid}/runs").json()
        if r and r[0]["status"] != "running":
            return r[0]
        time.sleep(0.1)
    raise AssertionError("run sin terminar")


# ---------------------------------------------------------------- manifiesto

@pytest.mark.parametrize("body, msg", [
    ("servers: {x: {command: 'ls', tools: {}}}", "lista"),
    ("servers: {nmap: {command: [ls], tools: {}}}", "choca"),
    ("servers: {x: {command: [ls], tools: {t: {capture_arg: f, allowed_args: [f]}}}}", "active"),
    ("servers: {x: {command: [ls], tools: {t: {active: false, capture_arg: f}}}}", "allowed_args"),
    ("servers: {x: {command: [ls], tools: {t: {active: false, allowed_args: []}}}}", "target_arg"),
    ("servers: {x: {command: [ls], tools: {t: {active: false, capture_arg: f, target_arg: h, allowed_args: [f, h]}}}}", "excluyentes"),
    ("servers: {x: {command: [ls], tools: {t: {active: true, capture_arg: f, allowed_args: [f]}}}}", "activa"),
    ("servers: {x: {command: [ls], tools: {t: {active: true, target_arg: h, allowed_args: [x]}}}}", "debe incluir"),
])
def test_invalid_manifest_is_rejected_atomically(tmp_path, body, msg):
    before = (dict(mcp_client.SERVERS), dict(mcp_client.TOOL_POLICY))
    path = tmp_path / "m.yaml"
    path.write_text(body)
    with pytest.raises(mcp_client.ManifestError, match=msg):
        mcp_client.load_manifest(path)
    assert (dict(mcp_client.SERVERS), dict(mcp_client.TOOL_POLICY)) == before  # no se aplica a medias


def test_default_manifest_is_valid_and_deny_by_default():
    names = mcp_client.load_manifest()
    assert names == ["wireshark"]
    pol = mcp_client.TOOL_POLICY
    assert ("wireshark", "wireshark_quick_analysis") in pol and not pol[("wireshark", "wireshark_quick_analysis")].active
    for dangerous in ("wireshark_capture", "wireshark_merge_pcaps", "wireshark_filter_save", "wireshark_decrypt_wpa", "wireshark_index",
                      "wireshark_export_objects", "wireshark_text2pcap_import", "wireshark_geoip_enrich"):
        assert ("wireshark", dangerous) not in pol
    assert not pol[("wireshark", "wireshark_extract_credentials")].llm and pol[("wireshark", "wireshark_detect_port_scan")].llm
    assert all(p.allowed_args is not None for k, p in pol.items() if p.external)


# ---------------------------------------------------------------- listado y ejecución

def test_listing_hides_unlisted_tools_and_rewrites_schema(client, ext):
    tools = {t["tool"]: t for t in client.get("/api/tools").json()}
    assert "not_listed" not in tools and "nmap_scan" in tools  # deny-by-default; los propios siguen
    info = tools["pcap_info"]
    assert info["capture_arg"] == "pcap_file" and not info["active"] and info["external"]
    props = info["input_schema"]["properties"]
    assert set(props) == {"capture_id", "limit"} and "output_file" not in props and "pcap_file" not in props
    assert info["input_schema"]["required"] == ["capture_id"]
    assert set(tools["host_probe"]["input_schema"]["properties"]) == {"host"}  # sin `arguments` ni `sudo`


def test_capture_tool_gets_real_confined_path_and_clean_env(client, ext, cid):
    cap_id, path = add_capture(cid)
    r = client.post(f"/api/campaigns/{cid}/runs", json={"server": "fake3p", "tool": "pcap_info", "arguments": {"capture_id": cap_id, "limit": 5}})
    assert r.status_code == 201, r.text
    run = wait_run(client, cid)
    assert run["status"] == "succeeded", run["error"]
    out = json.loads(run["output"])
    assert out["file"] == path and out["exists"] and out["limit"] == 5
    assert out["secret_in_env"] is None  # el servidor externo NO hereda el entorno de la app
    assert run["arguments"] == {"capture_id": cap_id, "limit": 5}  # se guarda la referencia, no la ruta


@pytest.mark.parametrize("args, code", [
    ({"capture_id": 999}, 422),  # no existe
    ({"pcap_file": "/etc/passwd"}, 422),  # ruta cruda: no se admite
    ({"capture_id": 1, "pcap_file": "/etc/passwd"}, 422),
    ({"capture_id": 1, "output_file": "/tmp/x"}, 422),  # argumento no permitido
    ({"capture_id": True}, 422),
    ({"capture_id": "1"}, 422),
    ({}, 422),
])
def test_capture_tool_rejects_bad_arguments(client, ext, cid, args, code):
    add_capture(cid)
    r = client.post(f"/api/campaigns/{cid}/runs", json={"server": "fake3p", "tool": "pcap_info", "arguments": args})
    assert r.status_code == code and client.get(f"/api/campaigns/{cid}/runs").json() == []


def test_capture_from_another_campaign_is_refused(client, ext, cid):
    other = client.post("/api/campaigns", json={"name": "O", "audit_type": "OT", "start_date": "2026-11-14", "scope": "10.0.0.0/24"}).json()["id"]
    foreign, _ = add_capture(other)
    r = client.post(f"/api/campaigns/{cid}/runs", json={"server": "fake3p", "tool": "pcap_info", "arguments": {"capture_id": foreign}})
    assert r.status_code == 422 and "no existe en esta campaña" in r.text


def test_unlisted_and_unsafe_tools_are_denied(client, ext, cid):
    assert client.post(f"/api/campaigns/{cid}/runs", json={"server": "fake3p", "tool": "not_listed", "arguments": {}}).status_code == 403
    # herramienta activa de terceros: alcance en código y sin flags crudos
    ok = {"server": "fake3p", "tool": "host_probe"}
    assert client.post(f"/api/campaigns/{cid}/runs", json={**ok, "arguments": {"host": "8.8.8.8"}}).status_code == 403
    assert client.post(f"/api/campaigns/{cid}/runs", json={**ok, "arguments": {"host": "10.0.0.5", "arguments": "--script=evil", "sudo": True}}).status_code == 422
    assert client.post(f"/api/campaigns/{cid}/runs", json={**ok, "arguments": {"host": "10.0.0.5"}}).status_code == 201
    assert json.loads(wait_run(client, cid)["output"]) == {"host": "10.0.0.5", "arguments": "-sV", "sudo": False}


def test_broken_external_server_does_not_break_listing(client, tmp_path, cid):
    path = tmp_path / "m.yaml"
    path.write_text("servers:\n  roto: {command: ['/no/existe/mcp'], tools: {t: {active: false, capture_arg: f, allowed_args: [f]}}}\n"
                    f"  falla: {{command: [{sys.executable!r}, '-c', 'import sys; sys.exit(3)'], tools: {{t: {{active: false, capture_arg: f, allowed_args: [f]}}}}}}\n")
    mcp_client.load_manifest(path)
    runs_router._tools_cache = None
    try:
        tools = client.get("/api/tools").json()
        assert {t["tool"] for t in tools} >= {"nmap_scan", "modbus_read"} and not any(t["server"] in ("roto", "falla") for t in tools)
    finally:
        mcp_client.load_manifest(tmp_path / "no-existe.yaml")
        runs_router._tools_cache = None


def test_external_output_is_truncated(client, ext, cid, monkeypatch):
    monkeypatch.setattr(mcp_client, "MAX_OUTPUT", 50)
    cap_id, _ = add_capture(cid)
    client.post(f"/api/campaigns/{cid}/runs", json={"server": "fake3p", "tool": "pcap_info", "arguments": {"capture_id": cap_id}})
    run = wait_run(client, cid)
    assert run["status"] == "succeeded" and "salida truncada a 50 caracteres" in run["output"] and len(run["output"]) < 150


# ---------------------------------------------------------------- asistente

def test_agent_runs_passive_capture_tool_without_approval_and_hides_llm_false(client, ext, cid, llm, monkeypatch):
    cid = mk(client)
    cap_id, path = add_capture(cid)
    monkeypatch.setattr(mcp_client, "list_tools", REAL_LIST_TOOLS)
    monkeypatch.setattr(agent, "_mcp_cache", None)
    mcp_client.TOOL_POLICY[("fake3p", "host_probe")] = mcp_client.ToolPolicy(
        target_arg="host", active=True, allowed_args=frozenset({"host"}), external=True, llm=False)

    llm.use(("pcap_info", {"capture_id": cap_id}), ("pcap_info", {"capture_id": 12345}), ("pcap_info", {"pcap_file": "/etc/passwd"}), ("host_probe", {"host": "10.0.0.5"}), thinking=False)
    llm.say("Hecho.")
    send(client, cid, "analiza la captura")
    end = time.time() + 30
    while time.time() < end and (llm.queue or chat(client, cid)["busy"]):  # el run corre en segundo plano y reanuda el turno al acabar
        time.sleep(0.1)
    assert not llm.queue and len(llm.calls) == 2
    names = {t["name"] for t in llm.calls[0]["tools"]}
    assert "pcap_info" in names and "get_captures" in names and "host_probe" not in names  # llm:false no se ofrece al modelo
    with SessionLocal() as db:
        from app.models import AgentCall
        rows = db.query(AgentCall).filter_by(campaign_id=cid).order_by(AgentCall.id).all()
        assert [r.status for r in rows] == ["done", "failed", "failed", "failed"]  # sin pending: la pasiva no pide aprobación
        assert json.loads(rows[0].result_text)["file"] == path
        assert "no existe en esta campaña" in rows[1].result_text and "no se admite" in rows[2].result_text.lower()
        assert "desconocida" in rows[3].result_text
        run = db.query(ToolRun).filter_by(campaign_id=cid).one()
        assert run.origin == "agent" and run.arguments == {"capture_id": cap_id}
