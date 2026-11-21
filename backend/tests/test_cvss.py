import pytest

from app import cvss

KNOWN = [  # puntuaciones publicadas / de la calculadora de FIRST
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0),
    ("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", 8.8),
    ("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H", 9.9),
    ("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", 7.8),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N", 6.1),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N", 7.5),
    ("CVSS:3.1/AV:A/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N", 4.3),
    ("CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N", 0.0),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H/E:P/RL:O/RC:C", 9.8),  # las métricas temporales/de entorno no cambian la base
]


@pytest.mark.parametrize("vector, score", KNOWN)
def test_known_scores(vector, score):
    assert cvss.base_score(vector) == score


@pytest.mark.parametrize("vector", [
    "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N",  # 4.0: no se calcula
    "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H",  # falta A
    "CVSS:3.1/AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",  # valor inválido
    "CVSS:3.1/AV:N/AV:L/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",  # repetida
    "", "basura",
])
def test_not_computable(vector):
    assert cvss.base_score(vector) is None


def test_api_computes_and_overrides(client):
    cid = client.post("/api/campaigns", json={"name": "C", "audit_type": "OT", "start_date": "2026-11-14", "scope": "10.0.0.0/24"}).json()["id"]
    assert client.get("/api/cvss/score", params={"vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}).json() == {"score": 9.8, "rating": "Critical"}
    assert client.get("/api/cvss/score", params={"vector": "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"}).status_code == 422
    # el vector manda sobre la puntuación tecleada
    f = client.post(f"/api/campaigns/{cid}/findings", json={"name": "x", "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", "cvss_score": 1.0}).json()
    assert f["cvss_score"] == 9.8 and f["rating"] == "Critical"
    f = client.patch(f"/api/findings/{f['id']}", json={"cvss_vector": "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H"}).json()
    assert f["cvss_score"] == 7.8 and f["rating"] == "High"
    # 4.0: la puntuación manual se conserva
    g = client.post(f"/api/campaigns/{cid}/findings", json={"name": "y", "cvss_vector": "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N", "cvss_score": 9.3}).json()
    assert g["cvss_score"] == 9.3
    # sin vector: manual
    assert client.post(f"/api/campaigns/{cid}/findings", json={"name": "z", "cvss_score": 5.5}).json()["cvss_score"] == 5.5
