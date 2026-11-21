BODY = {"name": "Planta X", "audit_type": "OT", "start_date": "2026-11-14", "scope": "10.0.0.0/24"}


def test_crud_flow(client):
    r = client.post("/api/campaigns", json=BODY)
    assert r.status_code == 201
    c = r.json()
    assert c["status"] == "planned" and c["llm_enabled"] is False

    assert len(client.get("/api/campaigns").json()) == 1

    r = client.patch(f"/api/campaigns/{c['id']}", json={"status": "active", "llm_enabled": True})
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["llm_enabled"] is True

    assert client.delete(f"/api/campaigns/{c['id']}").status_code == 204
    assert client.get(f"/api/campaigns/{c['id']}").status_code == 404


def test_validation(client):
    assert client.post("/api/campaigns", json={**BODY, "audit_type": "Nope"}).status_code == 422
    assert client.post("/api/campaigns", json={**BODY, "end_date": "2026-01-01"}).status_code == 422
    assert client.post("/api/campaigns", json={**BODY, "name": ""}).status_code == 422


def test_patch_end_before_start(client):
    c = client.post("/api/campaigns", json=BODY).json()
    assert client.patch(f"/api/campaigns/{c['id']}", json={"end_date": "2020-01-01"}).status_code == 422
