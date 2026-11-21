"""Contenido de protocolo (HTTP, MQTT, Modbus, S7, FTP) extraído de una captura."""
import pytest

from tests.pcap_factory import protocols_pcap
from tests.test_captures import CAMP, _upload, _wait_capture


@pytest.fixture()
def cid(client):
    return client.post("/api/campaigns", json=CAMP).json()["id"]


def events(client, cid, dst, port):
    r = client.get(f"/api/campaigns/{cid}/events", params={"src": "10.0.0.2", "dst": dst, "port": port})
    assert r.status_code == 200
    return r.json()


@pytest.fixture()
def analyzed(client, cid):
    assert _upload(client, cid, data=protocols_pcap(), name="protos.pcap").status_code == 201
    cap = _wait_capture(client, cid)
    assert cap["status"] == "analyzed", cap["error"]
    return cid


def by_summary(evs):
    return {e["summary"]: e for e in evs}


def test_http(client, analyzed):
    evs = by_summary(events(client, analyzed, "10.0.0.5", 80))
    basic = evs["GET /login"]
    assert basic["secret"] and basic["secret_kind"] == "HTTP Basic" and basic["kind"] == "auth"
    assert basic["detail"]["user"] == "admin" and basic["detail"]["password"] == "secret" and basic["detail"]["host"] == "plc.local"
    assert evs["POST /api/ctl"]["kind"] == "write" and not evs["POST /api/ctl"]["secret"]
    assert evs["HTTP 200"]["kind"] == "response" and evs["HTTP 200"]["direction"] == "s2c"


def test_mqtt(client, analyzed):
    evs = by_summary(events(client, analyzed, "10.0.0.6", 1883))
    conn = evs["CONNECT client=sensor1"]
    assert conn["secret"] and conn["detail"]["user"] == "mqttuser" and conn["detail"]["password"] == "mqttpass"
    pub = evs["PUBLISH plant/temp"]
    assert pub["count"] == 2 and pub["detail"]["sample"] in ("25.5", "26.1")  # mismo topic: se agrupa
    assert "SUBSCRIBE plant/#" in evs


def test_modbus(client, analyzed):
    evs = by_summary(events(client, analyzed, "10.0.0.7", 502))
    assert evs["FC3 Read Holding Registers @0 ×4"]["kind"] == "request"
    write = evs["FC16 Write Multiple Registers @10 ×2"]
    assert write["kind"] == "write" and write["detail"]["values"] == ["1", "2"]
    assert evs["FC3 Read Holding Registers → respuesta"]["detail"]["values"] == ["1", "2", "3", "4"]


def test_s7(client, analyzed):
    evs = by_summary(events(client, analyzed, "10.0.0.8", 102))
    assert evs["Read Var DB1.0.0"]["kind"] == "request"
    assert evs["Write Var DB1.0.0"]["kind"] == "write"
    assert evs["PLC stop"]["kind"] == "control"


def test_ftp(client, analyzed):
    evs = by_summary(events(client, analyzed, "10.0.0.9", 21))
    assert evs["USER admin"]["secret"] and evs["PASS hunter2"]["secret"] and evs["PASS hunter2"]["detail"]["password"] == "hunter2"
    assert evs["STOR firmware.bin"]["kind"] == "write"
    assert evs["230 Login successful."]["kind"] == "response"


def test_order_and_graph_counts(client, analyzed):
    evs = events(client, analyzed, "10.0.0.9", 21)
    assert [e["secret"] for e in evs][:2] == [True, True]  # credenciales primero
    edges = {(e["dst"], e["port"]): e for e in client.get(f"/api/campaigns/{analyzed}/graph").json()["edges"]}
    assert edges[("10.0.0.9", 21)]["secrets"] == 2 and edges[("10.0.0.6", 1883)]["secrets"] == 1
    assert edges[("10.0.0.7", 502)]["events"] >= 3 and edges[("10.0.0.7", 502)]["secrets"] == 0


def test_reanalyze_replaces_events_and_delete_cascades(client, analyzed):
    cap = client.get(f"/api/campaigns/{analyzed}/captures").json()[0]
    before = events(client, analyzed, "10.0.0.9", 21)
    client.post(f"/api/captures/{cap['id']}/reanalyze")
    _wait_capture(client, analyzed)
    assert events(client, analyzed, "10.0.0.9", 21) == before  # sin duplicar
    client.delete(f"/api/captures/{cap['id']}")
    assert events(client, analyzed, "10.0.0.9", 21) == []


# ---------------------------------------------------------------- hallazgos desde eventos

def event_id(client, cid, dst, port, summary):
    return by_summary(events(client, cid, dst, port))[summary]["id"]


def test_finding_from_cleartext_credentials(client, analyzed):
    eid = event_id(client, analyzed, "10.0.0.9", 21, "PASS hunter2")
    r = client.post(f"/api/events/{eid}/finding")
    assert r.status_code == 201, r.text
    f = r.json()
    assert f["name"] == "Credenciales transmitidas en claro (FTP)" and f["status"] == "draft" and f["phase"] == "discovery"
    assert f["identifier"] == "" and f["cvss_score"] is None  # los asigna el auditor
    assert "hunter2" not in f["poc"] and "h*****2" in f["poc"] and "usuario: admin" in f["poc"]  # contraseña enmascarada
    assert "USER admin" in f["poc"] and "10.0.0.2 → 10.0.0.9 tcp/21 (FTP)" in f["poc"] and "protos.pcap" in f["poc"]
    assert "SFTP" in f["recommendations"] and "comprometidas" in f["recommendations"]
    assets = {a["ip"]: a["id"] for a in client.get(f"/api/campaigns/{analyzed}/assets").json()}
    assert f["asset_ids"] == [assets["10.0.0.9"]]

    # USER y PASS son el mismo hallazgo; repetir es idempotente
    other = event_id(client, analyzed, "10.0.0.9", 21, "USER admin")
    again = client.post(f"/api/events/{other}/finding")
    assert again.status_code == 200 and again.json()["id"] == f["id"]
    assert len(client.get(f"/api/campaigns/{analyzed}/findings").json()) == 1
    linked = {e["summary"]: e["finding_id"] for e in events(client, analyzed, "10.0.0.9", 21)}
    assert linked["USER admin"] == f["id"] and linked["PASS hunter2"] == f["id"] and linked["STOR firmware.bin"] is None


def test_finding_from_control_and_write_events(client, analyzed):
    stop = client.post(f"/api/events/{event_id(client, analyzed, '10.0.0.8', 102, 'PLC stop')}/finding").json()
    assert "PLC stop" in stop["name"] and "no incorpora autenticación nativa" in stop["description"] and "S7comm" in stop["description"]
    assert "detener el controlador" in stop["impact"] and "IEC 62443" in stop["recommendations"] and "captura pasiva" in stop["description"]
    write = client.post(f"/api/events/{event_id(client, analyzed, '10.0.0.7', 502, 'FC16 Write Multiple Registers @10 ×2')}/finding").json()
    assert write["id"] != stop["id"] and "Modbus/TCP" in write["name"]
    ftp = client.post(f"/api/events/{event_id(client, analyzed, '10.0.0.9', 21, 'STOR firmware.bin')}/finding").json()
    assert "no incorpora autenticación" not in ftp["description"]  # solo Modbus/S7 carecen de autenticación nativa


def test_finding_from_event_rules(client, analyzed):
    assert client.post(f"/api/events/{event_id(client, analyzed, '10.0.0.5', 80, 'HTTP 200')}/finding").status_code == 422  # respuesta
    assert client.post("/api/events/99999/finding").status_code == 404


def test_finding_link_survives_reanalysis_and_frees_on_delete(client, analyzed):
    f = client.post(f"/api/events/{event_id(client, analyzed, '10.0.0.6', 1883, 'CONNECT client=sensor1')}/finding").json()
    assert "mqttpass" not in f["poc"] and "m******s" in f["poc"] and "TLS" in f["recommendations"]
    cap = client.get(f"/api/campaigns/{analyzed}/captures").json()[0]
    client.post(f"/api/captures/{cap['id']}/reanalyze")
    _wait_capture(client, analyzed)  # los eventos se regeneran con ids nuevos
    assert by_summary(events(client, analyzed, "10.0.0.6", 1883))["CONNECT client=sensor1"]["finding_id"] == f["id"]
    assert client.post(f"/api/events/{event_id(client, analyzed, '10.0.0.6', 1883, 'CONNECT client=sensor1')}/finding").json()["id"] == f["id"]
    client.delete(f"/api/findings/{f['id']}")
    assert by_summary(events(client, analyzed, "10.0.0.6", 1883))["CONNECT client=sensor1"]["finding_id"] is None
