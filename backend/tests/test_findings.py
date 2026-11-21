import pytest

from app import mcp_client
from app.db import SessionLocal
from app.models import Asset
from app.routers import evidence as evidence_router

CAMP = {"name": "Planta", "audit_type": "OT", "start_date": "2026-11-14", "scope": "10.0.0.0/24"}
V31 = "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H"
V40 = "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + bytes(20)


def png(n: int) -> bytes:
    return PNG + bytes([n]) * 8  # distinto hash por n


@pytest.fixture()
def cid(client):
    return client.post("/api/campaigns", json=CAMP).json()["id"]


def mk(client, cid, **kw):
    r = client.post(f"/api/campaigns/{cid}/findings", json={"name": "Kiosk bypass", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def add_asset(cid, ip="10.0.0.5"):
    with SessionLocal() as db:
        a = Asset(campaign_id=cid, ip=ip, ports=[], sources=[])
        db.add(a)
        db.commit()
        return a.id


@pytest.mark.parametrize("score,rating", [(None, ""), (0, "None"), (0.1, "Low"), (3.9, "Low"), (4.0, "Medium"), (6.9, "Medium"),
                                          (7.0, "High"), (7.6, "High"), (8.9, "High"), (9.0, "Critical"), (10, "Critical")])
def test_rating_derived_from_score(client, cid, score, rating):
    assert mk(client, cid, cvss_score=score)["rating"] == rating


def test_cvss_validation(client, cid):
    mk(client, cid, cvss_vector=V31, cvss_score=7.6)
    mk(client, cid, cvss_vector=V40, cvss_score=9.3)
    mk(client, cid, cvss_vector="")  # borrador sin CVSS
    for bad in ("AV:N/AC:L", "CVSS:2.0/AV:N/AC:L/PR:N", "CVSS:3.1/", "cualquier cosa"):
        r = client.post(f"/api/campaigns/{cid}/findings", json={"name": "x", "cvss_vector": bad})
        assert r.status_code == 422, bad
    assert client.post(f"/api/campaigns/{cid}/findings", json={"name": "x", "cvss_score": 10.5}).status_code == 422
    assert client.post(f"/api/campaigns/{cid}/findings", json={"name": ""}).status_code == 422


def test_crud_and_null_handling(client, cid):
    f = mk(client, cid, identifier="F-001", phase="exploitation", cvss_score=7.6, poc="paso 1")
    assert f["phase"] == "exploitation" and f["status"] == "draft"
    r = client.patch(f"/api/findings/{f['id']}", json={"name": None, "impact": "RCE", "cvss_score": None})
    assert r.status_code == 200
    f2 = r.json()
    assert f2["name"] == "Kiosk bypass"  # null en campo obligatorio: se ignora
    assert f2["impact"] == "RCE" and f2["cvss_score"] is None and f2["rating"] == ""
    assert client.get(f"/api/findings/{f['id']}").json()["poc"] == "paso 1"
    assert len(client.get(f"/api/campaigns/{cid}/findings").json()) == 1
    assert client.delete(f"/api/findings/{f['id']}").status_code == 204
    assert client.get(f"/api/findings/{f['id']}").status_code == 404


def test_identifier_unique_per_campaign(client, cid):
    f = mk(client, cid, identifier="F-001")
    r = client.post(f"/api/campaigns/{cid}/findings", json={"name": "otro", "identifier": "F-001"})
    assert r.status_code == 409
    mk(client, cid)
    mk(client, cid)  # vacíos repetidos: permitido
    g = mk(client, cid, identifier="F-002")
    assert client.patch(f"/api/findings/{g['id']}", json={"identifier": "F-001"}).status_code == 409
    assert client.patch(f"/api/findings/{f['id']}", json={"identifier": "F-001"}).status_code == 200  # el propio
    other = client.post("/api/campaigns", json=CAMP).json()["id"]
    mk(client, other, identifier="F-001")  # otra campaña: permitido


def test_assets_linking(client, cid):
    a1, a2 = add_asset(cid, "10.0.0.5"), add_asset(cid, "10.0.0.6")
    f = mk(client, cid, asset_ids=[a1, a2], affected_other="Vending Machine")
    assert f["asset_ids"] == sorted([a1, a2]) and f["affected_other"] == "Vending Machine"
    assert client.patch(f"/api/findings/{f['id']}", json={"asset_ids": [a2]}).json()["asset_ids"] == [a2]
    assert client.patch(f"/api/findings/{f['id']}", json={"name": "nuevo"}).json()["asset_ids"] == [a2]  # no tocar = se conserva
    assert client.patch(f"/api/findings/{f['id']}", json={"asset_ids": []}).json()["asset_ids"] == []
    other = client.post("/api/campaigns", json=CAMP).json()["id"]
    foreign = add_asset(other, "10.0.0.9")
    r = client.post(f"/api/campaigns/{cid}/findings", json={"name": "x", "asset_ids": [foreign]})
    assert r.status_code == 422
    assert client.post(f"/api/campaigns/{cid}/findings", json={"name": "x", "asset_ids": [9999]}).status_code == 422


def test_dependencies(client, cid):
    a, b = mk(client, cid, identifier="A"), mk(client, cid, identifier="B")
    assert client.patch(f"/api/findings/{b['id']}", json={"depends_on_id": a["id"]}).status_code == 200
    assert client.patch(f"/api/findings/{a['id']}", json={"depends_on_id": a["id"]}).status_code == 422  # sí mismo
    assert client.patch(f"/api/findings/{a['id']}", json={"depends_on_id": b["id"]}).status_code == 422  # ciclo
    assert client.patch(f"/api/findings/{b['id']}", json={"depends_on_id": 9999}).status_code == 422
    other = client.post("/api/campaigns", json=CAMP).json()["id"]
    foreign = mk(client, other)
    assert client.patch(f"/api/findings/{b['id']}", json={"depends_on_id": foreign["id"]}).status_code == 422
    # borrar el dependido deja la referencia a null
    client.delete(f"/api/findings/{a['id']}")
    assert client.get(f"/api/findings/{b['id']}").json()["depends_on_id"] is None
    assert client.patch(f"/api/findings/{b['id']}", json={"depends_on_id": None}).status_code == 200


def up(client, cid, data, name="s.png", **form):
    return client.post(f"/api/campaigns/{cid}/evidence", files={"file": (name, data)}, data=form)


def test_evidence_upload_validation(client, cid, monkeypatch):
    r = up(client, cid, png(1), caption="pantalla de login")
    assert r.status_code == 201, r.text
    ev = r.json()
    assert ev["mime"] == "image/png" and ev["caption"] == "pantalla de login" and ev["finding_id"] is None and ev["position"] == 0
    assert up(client, cid, png(1)).status_code == 409  # mismo hash
    assert up(client, cid, b"GIF89a" + bytes(30), name="a.gif").status_code == 201
    assert up(client, cid, b"\xff\xd8\xff\xe0" + bytes(30), name="a.jpg").status_code == 201
    assert up(client, cid, b"RIFF\x00\x00\x00\x00WEBP" + bytes(20), name="a.webp").status_code == 201
    assert up(client, cid, b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', name="x.svg").status_code == 422
    assert up(client, cid, b"%PDF-1.4 ...", name="x.png").status_code == 422  # la extensión no manda: manda el contenido
    assert up(client, cid, png(9), finding_id="9999").status_code == 422
    monkeypatch.setattr(evidence_router, "MAX_EVIDENCE_BYTES", 10)
    assert up(client, cid, png(7)).status_code == 413
    leftovers = list((mcp_client.CAPTURES_ROOT / str(cid) / "evidence").glob(".upload-*"))
    assert leftovers == []
    assert len(client.get(f"/api/campaigns/{cid}/evidence").json()) == 4


def test_evidence_numbering_and_linking(client, cid):
    f, g = mk(client, cid, identifier="F1"), mk(client, cid, identifier="F2")
    e1 = up(client, cid, png(1), finding_id=str(f["id"])).json()
    e2 = up(client, cid, png(2), finding_id=str(f["id"])).json()
    e3 = up(client, cid, png(3)).json()
    assert (e1["position"], e2["position"], e3["position"]) == (1, 2, 0)
    e3 = client.patch(f"/api/evidence/{e3['id']}", json={"finding_id": f["id"], "caption": "script de Frida"}).json()
    assert e3["position"] == 3 and e3["caption"] == "script de Frida"
    moved = client.patch(f"/api/evidence/{e1['id']}", json={"finding_id": g["id"]}).json()
    assert moved["finding_id"] == g["id"] and moved["position"] == 1  # numeración propia en el otro hallazgo
    unlinked = client.patch(f"/api/evidence/{e2['id']}", json={"finding_id": None}).json()
    assert unlinked["finding_id"] is None and unlinked["position"] == 0
    assert client.patch(f"/api/evidence/{e2['id']}", json={"caption": "solo caption"}).json()["finding_id"] is None  # no tocar = se conserva
    other = client.post("/api/campaigns", json=CAMP).json()["id"]
    foreign = mk(client, other)
    assert client.patch(f"/api/evidence/{e2['id']}", json={"finding_id": foreign["id"]}).status_code == 422


def test_deleting_finding_keeps_evidence(client, cid):
    f = mk(client, cid)
    ev = up(client, cid, png(1), finding_id=str(f["id"])).json()
    client.delete(f"/api/findings/{f['id']}")
    ev2 = [e for e in client.get(f"/api/campaigns/{cid}/evidence").json() if e["id"] == ev["id"]][0]
    assert ev2["finding_id"] is None


def test_evidence_file_serving_and_delete(client, cid):
    data = png(5)
    ev = up(client, cid, data).json()
    r = client.get(f"/api/evidence/{ev['id']}/file")
    assert r.status_code == 200 and r.content == data
    assert r.headers["content-type"] == "image/png" and r.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in r.headers["content-security-policy"]
    path = mcp_client.CAPTURES_ROOT / str(cid) / "evidence" / f"{ev['id']}.png"
    assert path.exists()
    assert client.delete(f"/api/evidence/{ev['id']}").status_code == 204
    assert not path.exists() and client.get(f"/api/evidence/{ev['id']}/file").status_code == 404


def test_delete_campaign_removes_everything(client, cid):
    f = mk(client, cid, asset_ids=[add_asset(cid)])
    up(client, cid, png(1), finding_id=str(f["id"]))
    directory = mcp_client.CAPTURES_ROOT / str(cid)
    assert (directory / "evidence").exists()
    assert client.delete(f"/api/campaigns/{cid}").status_code == 204
    assert not directory.exists()
    assert client.get(f"/api/findings/{f['id']}").status_code == 404
