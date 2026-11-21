import io
import shutil
import subprocess

import pytest
from docx import Document

from app import mcp_client
from app.db import SessionLocal
from app.models import Asset, Report
from app.report import pdf
from app.report.richtext import marker_numbers, parse_blocks, split_inline
from tests.images import real_png

SCOPE = "10.0.0.0/24\nplc.corp"
V31 = "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H"


@pytest.fixture()
def cid(client):
    r = client.post("/api/campaigns", json={"name": "Vending OT", "audit_type": "OT", "start_date": "2026-11-10", "end_date": "2026-11-14", "scope": SCOPE, "llm_enabled": True})
    return r.json()["id"]


def add_finding(client, cid, **kw):
    r = client.post(f"/api/campaigns/{cid}/findings", json={"name": "Kiosk Mode Bypass", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def add_evidence(client, cid, finding_id, color=(40, 90, 160), caption="captura", name="e.png", data=None):
    r = client.post(f"/api/campaigns/{cid}/evidence", files={"file": (name, data or real_png(rgb=color))}, data={"caption": caption, "finding_id": str(finding_id)})
    assert r.status_code == 201, r.text
    return r.json()


def seed(client, cid):
    with SessionLocal() as db:
        asset = Asset(campaign_id=cid, ip="10.0.0.5", hostname="plc.corp", vendor="Siemens", ports=[{"port": 502, "proto": "tcp", "service": "modbus"}], sources=["nmap"])
        db.add(asset)
        db.commit()
        asset_id = asset.id
    f1 = add_finding(client, cid, asset_ids=[asset_id], identifier="F-001", name="Kiosk Mode Bypass", phase="exploitation", status="confirmed", cvss_vector=V31, cvss_score=7.6,
                     description="Descripción con **negrita**.", poc="• Paso uno\n  o sub-paso\n\n[Evidencia 1: pantalla de login]\n\n```bash\nid; whoami\n```\n\n[Evidencia 3: no existe]",
                     impact="• Acceso al sistema de ficheros", recommendations="• **Hardening**: quitar depuración", affected_other="Vending Machine")
    add_finding(client, cid, identifier="F-002", name="ADB habilitado", phase="post_exploitation", cvss_score=6.8, description="d", poc="p", impact="i", recommendations="r", depends_on_id=f1)
    add_finding(client, cid, identifier="F-003", name="Falso positivo", phase="discovery", status="false_positive", description="x")
    add_evidence(client, cid, f1, caption="pantalla de login")
    return f1


def export(client, cid, fmt, **params):
    return client.get(f"/api/campaigns/{cid}/report/export", params={"format": fmt, **params})


def headings(doc, style):
    return [p.text for p in doc.paragraphs if p.style.name == style]


# ---------------------------------------------------------------- datos

def test_defaults_roundtrip_and_validation(client, cid):
    r = client.get(f"/api/campaigns/{cid}/report").json()
    assert r["data"]["language"] == "es" and r["data"]["classification"] == "Confidencial" and r["data"]["test_type"] == ""
    assert "Falta el cliente" in r["warnings"] and "No hay hallazgos que incluir" in r["warnings"]
    body = {**r["data"], "client": "ACME", "dut_name": "VM-3000", "test_type": "grey", "conclusions": "Cierre."}
    saved = client.put(f"/api/campaigns/{cid}/report", json=body).json()
    assert saved["data"]["client"] == "ACME" and "Falta el cliente" not in saved["warnings"] and "Faltan las Conclusiones" not in saved["warnings"]
    assert client.get(f"/api/campaigns/{cid}/report").json()["data"]["test_type"] == "grey"
    assert client.put(f"/api/campaigns/{cid}/report", json={**body, "test_type": "rojo"}).status_code == 422
    assert client.put(f"/api/campaigns/{cid}/report", json={**body, "language": "fr"}).status_code == 422
    assert client.get("/api/campaigns/999/report").status_code == 404


def test_warnings_flag_quality_problems(client, cid):
    f1 = seed(client, cid)
    add_evidence(client, cid, f1, color=(30, 120, 70), caption="sin citar", name="e2.png")  # vinculada pero no citada
    ev = client.post(f"/api/campaigns/{cid}/evidence", files={"file": ("x.png", real_png(rgb=(1, 2, 3)))}).json()  # sin vincular
    add_finding(client, cid, name="Sin ID ni CVSS")
    w = "\n".join(client.get(f"/api/campaigns/{cid}/report").json()["warnings"])
    assert "«Sin ID ni CVSS»: sin identificador" in w and "sin puntuación CVSS" in w
    assert "cita «Evidencia 3» pero solo hay 2" in w
    assert "Evidencia 2 (e2.png) está vinculada pero no se cita" in w
    assert "1 evidencia(s) sin vincular" in w and "1 falso(s) positivo(s) excluido(s)" in w and "en estado «borrador»" in w
    drafts_off = client.get(f"/api/campaigns/{cid}/report", params={"drafts": "false"}).json()["warnings"]
    assert not any("«borrador»" in x for x in drafts_off)


# ---------------------------------------------------------------- Markdown

def test_markdown_export_follows_skill_structure(client, cid):
    seed(client, cid)
    client.put(f"/api/campaigns/{cid}/report", json={"dut_name": "VM-3000", "client": "ACME", "test_type": "grey", "exploitation_summary": "Narrativa."})
    r = export(client, cid, "md")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown") and "attachment" in r.headers["content-disposition"]
    md = r.text
    assert "## 8. Hallazgos" in md and "### 8.1 Explotación" in md and "### 8.2 Post-Explotación" in md  # numeración sin huecos (no hay Descubrimiento)
    assert "#### F-001 Kiosk Mode Bypass" in md and f"**Criticidad:** High (7.6): {V31}" in md
    assert "**Activos afectados:** 10.0.0.5 (plc.corp), Vending Machine" in md and "**Requiere el hallazgo:** F-001" in md
    assert "[Evidencia 1: pantalla de login]" in md and "Falso positivo" not in md
    assert md.index("## 6.") < md.index("## 7.") < md.index("## 8.") < md.index("## 9.") and "[PENDIENTE]" in md  # secciones sin rellenar visibles
    en = client.put(f"/api/campaigns/{cid}/report", json={"language": "en"}).json()
    assert "Proof of Concept" in export(client, cid, "md").text and "### 8.1 Exploitation" in export(client, cid, "md").text


# ---------------------------------------------------------------- Word

def test_docx_structure_images_and_placeholders(client, cid):
    seed(client, cid)
    client.put(f"/api/campaigns/{cid}/report", json={"dut_name": "VM-3000", "client": "ACME", "test_type": "grey", "conclusions": "Cierre."})
    r = export(client, cid, "docx")
    assert r.status_code == 200 and "wordprocessingml" in r.headers["content-type"] and r.content[:2] == b"PK"
    doc = Document(io.BytesIO(r.content))
    h1 = headings(doc, "Heading 1")
    assert [h.split(".")[0] for h in h1] == ["1", "2", "3", "4", "5", "6", "7", "8", "9"] and h1[7] == "8. Hallazgos"
    assert "Índice" not in h1 and "Índice" in headings(doc, "TocTitle")  # el título del índice no se lista a sí mismo
    assert headings(doc, "Heading 2")[-2:] == ["8.1 Explotación", "8.2 Post-Explotación"]
    assert headings(doc, "Heading 3") == ["F-001 Kiosk Mode Bypass", "F-002 ADB habilitado"]  # el falso positivo no entra
    assert len(doc.inline_shapes) == 1  # Evidencia 1 (la 3 no existe: marcador)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "[Evidencia 3: no existe]" in text and "Evidencia 1: pantalla de login" in text and "id; whoami" in text
    assert "PAGE" in doc.sections[0].footer._element.xml and "NUMPAGES" in doc.sections[0].footer._element.xml
    assert 'TOC \\o "1-3"' in doc.element.xml
    cells = [c.text for t in doc.tables for row in t.rows for c in row.cells]
    assert "High (7.6): " + V31 in cells and "10.0.0.5 (plc.corp), Vending Machine" in cells
    assert any("502/tcp modbus" in c for c in cells)
    assert "[PENDIENTE]" in text  # secciones narrativas vacías: visibles


def test_docx_survives_terminal_garbage_and_odd_images(client, cid):
    f1 = add_finding(client, cid, identifier="F-1", name="Salida de terminal \x07", description="rojo \x1b[31mERROR\x1b[0m y NUL\x00 fin", poc="`x\x0b` <b>&amp;</b> " + "A" * 5000)
    add_evidence(client, cid, f1, name="a.webp", data=b"RIFF\x00\x00\x00\x00WEBP" + bytes(40), caption="webp")  # no incrustable
    ev = add_evidence(client, cid, f1, color=(5, 6, 7), caption="se pierde el fichero")
    from app.models import Evidence
    with SessionLocal() as db:
        import pathlib
        pathlib.Path(db.get(Evidence, ev["id"]).path).unlink()  # el fichero desaparece del disco
    client.put(f"/api/campaigns/{cid}/report", json={"poc": "", "dut_description": "ok"})
    f = client.patch(f"/api/findings/{f1}", json={"poc": "[Evidencia 1: webp]\n[Evidencia 2: perdida]"}).json()
    r = export(client, cid, "docx")
    assert r.status_code == 200
    doc = Document(io.BytesIO(r.content))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "ERROR y NUL fin" in text and "\x1b" not in doc.element.xml
    assert "[Evidencia 1: webp]" in text and "[Evidencia 2: perdida]" in text  # degradan a marcador, sin romper


def test_export_validation(client, cid):
    assert export(client, cid, "exe").status_code == 422
    assert client.get("/api/campaigns/999/report/export").status_code == 404


# ---------------------------------------------------------------- PDF

@pytest.mark.skipif(not pdf.available() or not shutil.which("pdftotext"), reason="LibreOffice/UNO o poppler no disponibles")
def test_pdf_export_has_toc_and_brand_font(client, cid, tmp_path):
    seed(client, cid)
    client.put(f"/api/campaigns/{cid}/report", json={"dut_name": "VM-3000", "client": "ACME", "test_type": "grey"})
    r = export(client, cid, "pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    f = tmp_path / "r.pdf"
    f.write_bytes(r.content)
    text = subprocess.run(["pdftotext", "-layout", str(f), "-"], capture_output=True, text=True).stdout
    assert "Kiosk Mode Bypass" in text and "Página 2 de" in text
    toc_line = [ln for ln in text.splitlines() if ln.strip().startswith("8. Hallazgos")][0]
    assert toc_line.strip()[-1].isdigit()  # el índice se ha actualizado con números de página
    fonts = subprocess.run(["pdffonts", str(f)], capture_output=True, text=True).stdout
    assert "Arial" in fonts or "Liberation" in fonts  # tipografía del informe (Arial o su equivalente métrico)
    assert not list((mcp_client.CAPTURES_ROOT / str(cid) / "reports").glob("*.docx"))  # el docx intermedio no se queda


# ---------------------------------------------------------------- IA

def test_draft_gating(client, cid, llm):
    off = client.post("/api/campaigns", json={"name": "x", "audit_type": "OT", "start_date": "2026-11-14", "scope": SCOPE}).json()["id"]
    assert client.post(f"/api/campaigns/{off}/report/draft", json={"section": "conclusions"}).status_code == 403
    assert client.post(f"/api/campaigns/{cid}/report/draft", json={"section": "conclusions"}).status_code == 422  # sin hallazgos
    seed(client, cid)
    r = client.post(f"/api/campaigns/{cid}/report/draft", json={"section": "exploitation_summary"})
    assert r.status_code == 422 and "tipo de prueba" in r.json()["detail"]  # la skill exige saber white/grey/black
    assert client.post(f"/api/campaigns/{cid}/report/draft", json={"section": "introduction"}).status_code == 422
    assert llm.calls == []  # nada se envió al modelo en ninguno de los casos


def test_draft_is_redacted_styled_and_restored(client, cid, llm):
    seed(client, cid)
    client.put(f"/api/campaigns/{cid}/report", json={"test_type": "grey", "dut_name": "VM-3000", "language": "es"})
    llm.say(lambda: f"Con acceso a {__import__('tests.test_chat', fromlist=['tok']).tok('10.0.0.5')()} se ha podido salir del kiosco.")
    r = client.post(f"/api/campaigns/{cid}/report/draft", json={"section": "exploitation_summary"})
    assert r.status_code == 200
    assert r.json() == {"section": "exploitation_summary", "text": "Con acceso a 10.0.0.5 se ha podido salir del kiosco."}  # seudónimo restaurado
    sent = llm.calls[0]
    blob = str(sent["messages"])
    assert "10.0.0.5" not in blob and "plc.corp" not in blob and "Falso positivo" not in blob  # nada real; falso positivo fuera
    assert "Resumen de Explotación" in sent["system"] and "NUNCA viñetas" in sent["system"] and "NO inventes" in sent["system"]
    assert sent["tools"] == [] and '"test_type": "grey"' in blob and "español" in blob
    assert '"depends_on": "F-001"' in blob  # la cadena la dicta la dependencia declarada
    # no se guarda solo: el borrador vuelve a la UI
    assert client.get(f"/api/campaigns/{cid}/report").json()["data"]["exploitation_summary"] == ""


def test_draft_refusal_and_other_sections(client, cid, llm):
    seed(client, cid)
    llm.refuse("cyber")
    r = client.post(f"/api/campaigns/{cid}/report/draft", json={"section": "conclusions"})
    assert r.status_code == 422 and "cyber" in r.json()["detail"]
    llm.say("• **Hardening**: …")
    assert client.post(f"/api/campaigns/{cid}/report/draft", json={"section": "remediation_summary"}).status_code == 200  # no exige test_type
    assert "Resumen de Remediaciones" in llm.calls[1]["system"] and "4-8 viñetas" in llm.calls[1]["system"]


def test_report_removed_with_campaign(client, cid):
    seed(client, cid)
    client.put(f"/api/campaigns/{cid}/report", json={"client": "ACME"})
    export(client, cid, "md")
    directory = mcp_client.CAPTURES_ROOT / str(cid)
    assert (directory / "reports").exists()
    client.delete(f"/api/campaigns/{cid}")
    assert not directory.exists()
    with SessionLocal() as db:
        assert db.get(Report, cid) is None


# ---------------------------------------------------------------- parser

def test_richtext_parser():
    blocks = parse_blocks("Intro\ncontinúa\n\n• uno\n  o sub\n- dos\n\n```py\nx = 1\n\ny = 2\n```\n[Evidencia 2: algo]\n[evidence 3]\nfinal")
    assert [(b.kind) for b in blocks] == ["p", "ul", "code", "evidence", "evidence", "p"]
    assert blocks[0].text == "Intro\ncontinúa" and blocks[1].items == [(0, "uno"), (1, "sub"), (0, "dos")]
    assert blocks[2].text == "x = 1\n\ny = 2" and (blocks[3].number, blocks[3].text) == (2, "algo") and blocks[4].number == 3
    assert [b.kind for b in parse_blocks("```\nsin cerrar")] == ["code"]
    assert [b.kind for b in parse_blocks("o esto no es viñeta")] == ["p"]  # 'o' solo cuenta si está indentado
    assert split_inline("a **b** y `c` d") == [("", "a "), ("b", "b"), ("", " y "), ("code", "c"), ("", " d")]
    assert marker_numbers("[Evidencia 1: a] x [Evidence 4]") == {1, 4}
