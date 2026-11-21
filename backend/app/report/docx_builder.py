"""Maquetación del informe en Word (python-docx).

No hay plantilla Word: toda la maquetación vive aquí.
Reglas aplicadas: Arial como tipografía, negro #2D2A26 para texto y cian solo como acento decorativo (nunca como texto sobre blanco).
"""
import re
from dataclasses import replace
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_COLOR_INDEX
from docx.image.image import Image as DocxImage
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from ..scope import _lines
from .collect import ReportContext, finding_label
from .model import (BLACK, FONT, ACCENT, GREY_FILL, GREY_LINE, GREY_TEXT, LABELS, MONO, PHASE_ORDER, RATING_COLOR, RATING_ORDER)
from .richtext import Block, parse_blocks, split_inline

CONTENT_WIDTH_CM = 16.0
MAX_IMG_W_CM, MAX_IMG_H_CM = 14.5, 16.0
_PPR_AFTER_BDR = ("w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE",
                  "w:autoSpaceDN", "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents",
                  "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle",
                  "w:rPr", "w:sectPr", "w:pPrChange")
_PPR_AFTER_SHD = _PPR_AFTER_BDR[1:]


# Caracteres no permitidos en XML 1.0 (controles salvo \t \n \r). Un PoC con salida de terminal (ANSI, NUL…) rompería python-docx.
_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def clean(text: str) -> str:
    return _XML_BAD.sub("", _ANSI.sub("", text))


def _san(value):
    if isinstance(value, Enum):  # los enums de la BD heredan de str: no deben convertirse en str planos
        return value
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, list):
        return [_san(v) for v in value]
    if isinstance(value, dict):
        return {k: _san(v) for k, v in value.items()}
    return value


def _san_row(obj):
    """Copia de solo lectura de una fila ORM con todas sus cadenas saneadas."""
    return SimpleNamespace(**{c.key: _san(getattr(obj, c.key)) for c in obj.__table__.columns})


def _sanitize(ctx: ReportContext) -> ReportContext:
    data = ctx.data.model_copy(update={k: clean(v) for k, v in ctx.data.model_dump().items() if isinstance(v, str)})
    views = [replace(v, f=_san_row(v.f), evidence=[_san_row(e) for e in v.evidence], assets=_san(v.assets), depends_label=clean(v.depends_label)) for v in ctx.findings]
    return replace(ctx, campaign=_san_row(ctx.campaign), data=data, findings=views, assets=[_san_row(a) for a in ctx.assets],
                   flows=[_san_row(f) for f in ctx.flows], captures=[_san_row(c) for c in ctx.captures])


def rgb(hex_: str) -> RGBColor:
    return RGBColor.from_string(hex_)


# ---------------------------------------------------------------- utilidades OOXML

def _set_font(font, name: str, size: float | None = None, bold: bool | None = None, color: str | None = None, italic: bool | None = None):
    font.name = name
    rpr = font._element.get_or_add_rPr()
    fonts = rpr.get_or_add_rFonts()
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        if fonts.get(qn(attr)) is not None:
            del fonts.attrib[qn(attr)]
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fonts.set(qn(attr), name)
    if size is not None:
        font.size = Pt(size)
    if bold is not None:
        font.bold = bold
    if italic is not None:
        font.italic = italic
    if color:
        font.color.rgb = rgb(color)


def _p_border(paragraph_or_style_ppr, side: str, color: str, size: int = 12, space: int = 4):
    ppr = paragraph_or_style_ppr
    bdr = ppr.find(qn("w:pBdr"))
    if bdr is None:
        bdr = OxmlElement("w:pBdr")
        ppr.insert_element_before(bdr, *_PPR_AFTER_BDR)
    el = OxmlElement(f"w:{side}")
    for k, v in (("w:val", "single"), ("w:sz", str(size)), ("w:space", str(space)), ("w:color", color)):
        el.set(qn(k), v)
    bdr.append(el)


def _p_shade(paragraph, fill: str):
    ppr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    for k, v in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", fill)):
        shd.set(qn(k), v)
    ppr.insert_element_before(shd, *_PPR_AFTER_SHD)


def _cell_shade(cell, fill: str):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    for k, v in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", fill)):
        shd.set(qn(k), v)
    tcpr.insert_element_before(shd, "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign", "w:hideMark")


def _table_borders(table, color: str = GREY_LINE, inside: bool = True, outer: bool = True):
    tblpr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{side}")
        on = outer if side in ("top", "left", "bottom", "right") else inside
        el.set(qn("w:val"), "single" if on else "nil")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        borders.append(el)
    tblpr.insert_element_before(borders, "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook")


def _cell_margins(table, top=60, bottom=60, left=100, right=100):
    tblpr = table._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for side, v in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:w"), str(v))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tblpr.insert_element_before(mar, "w:tblLook")


def _row_flags(row, header: bool = False):
    trpr = row._tr.get_or_add_trPr()
    trpr.append(OxmlElement("w:cantSplit"))
    if header:
        trpr.append(OxmlElement("w:tblHeader"))


def _right_tab(paragraph):
    """Un único tabulador a la derecha del área de texto (anula los centro/derecha heredados del estilo Header/Footer)."""
    ppr = paragraph._p.get_or_add_pPr()
    tabs = OxmlElement("w:tabs")
    for val, pos in (("clear", 4680), ("clear", 9360), ("right", int(CONTENT_WIDTH_CM * 567))):
        t = OxmlElement("w:tab")
        t.set(qn("w:val"), val)
        t.set(qn("w:pos"), str(pos))
        tabs.append(t)
    ppr.insert_element_before(tabs, *_PPR_AFTER_SHD[1:])


def _field(paragraph, instr: str, placeholder: str = ""):
    def fc(kind):
        r = paragraph.add_run()
        el = OxmlElement("w:fldChar")
        el.set(qn("w:fldCharType"), kind)
        r._r.append(el)
        return r

    fc("begin")
    r = paragraph.add_run()
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = f" {instr} "
    r._r.append(it)
    fc("separate")
    ph = paragraph.add_run(placeholder)
    fc("end")
    return ph


# ---------------------------------------------------------------- estilos

def _setup(doc: Document):
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.5)
    sec.top_margin, sec.bottom_margin = Cm(2.6), Cm(2.2)
    sec.header_distance, sec.footer_distance = Cm(1.1), Cm(1.0)
    sec.different_first_page_header_footer = True

    st = doc.styles
    _set_font(st["Normal"].font, FONT, 10, color=BLACK)
    st["Normal"].paragraph_format.space_after = Pt(6)
    st["Normal"].paragraph_format.line_spacing = 1.15
    for name, size, before, after in (("Heading 1", 18, 20, 10), ("Heading 2", 14, 14, 6), ("Heading 3", 11.5, 12, 4)):
        h = st[name]
        _set_font(h.font, FONT, size, bold=True, color=BLACK, italic=False)
        pf = h.paragraph_format
        pf.space_before, pf.space_after, pf.keep_with_next = Pt(before), Pt(after), True
    _p_border(st["Heading 1"].element.get_or_add_pPr(), "bottom", ACCENT, size=18, space=4)  # acento de marca (decorativo)
    for name in ("List Bullet", "List Bullet 2"):
        _set_font(st[name].font, FONT, 10, color=BLACK)
        st[name].paragraph_format.space_after = Pt(3)
    code = st.add_style("CodeBlock", WD_STYLE_TYPE.PARAGRAPH)
    code.base_style = st["Normal"]
    _set_font(code.font, MONO, 8.5, color=BLACK)
    code.paragraph_format.space_after = Pt(0)
    code.paragraph_format.line_spacing = 1.0
    cap = st.add_style("EvidenceCaption", WD_STYLE_TYPE.PARAGRAPH)
    cap.base_style = st["Normal"]
    _set_font(cap.font, FONT, 8.5, color=GREY_TEXT, italic=True)
    cap.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_after = Pt(10)
    toc_title = st.add_style("TocTitle", WD_STYLE_TYPE.PARAGRAPH)  # como Heading 1 pero fuera del propio índice
    toc_title.base_style = st["Normal"]
    _set_font(toc_title.font, FONT, 18, bold=True, color=BLACK)
    toc_title.paragraph_format.space_before, toc_title.paragraph_format.space_after = Pt(0), Pt(10)
    _p_border(toc_title.element.get_or_add_pPr(), "bottom", ACCENT, size=18, space=4)
    lab = st.add_style("FindingLabel", WD_STYLE_TYPE.PARAGRAPH)
    lab.base_style = st["Normal"]
    _set_font(lab.font, FONT, 10.5, bold=True, color=BLACK)
    lab.paragraph_format.space_before, lab.paragraph_format.space_after, lab.paragraph_format.keep_with_next = Pt(10), Pt(3), True

    settings = doc.settings.element
    upd = OxmlElement("w:updateFields")  # Word actualiza índice y nº de páginas al abrir
    upd.set(qn("w:val"), "true")
    settings.append(upd)
    doc.core_properties.author = ""
    doc.core_properties.comments = ""


# ---------------------------------------------------------------- texto

def _runs(paragraph, text: str, *, size: float | None = None, bold: bool = False, color: str | None = None, italic: bool = False):
    for style, chunk in split_inline(text):
        r = paragraph.add_run(chunk)
        if style == "code":
            _set_font(r.font, MONO, (size or 10) - 1)
            rpr = r._r.get_or_add_rPr()
            shd = OxmlElement("w:shd")
            for k, v in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", GREY_FILL)):
                shd.set(qn(k), v)
            rpr.append(shd)
        else:
            if style == "b" or bold:
                r.bold = True
            if size:
                r.font.size = Pt(size)
            if color:
                r.font.color.rgb = rgb(color)
            if italic:
                r.italic = True


def _pending(doc, L, what: str = ""):
    p = doc.add_paragraph()
    r = p.add_run(f"[{L['pending']}{': ' + what if what else ''}]")
    r.font.highlight_color = WD_COLOR_INDEX.YELLOW
    return p


def _picture(doc, ev, L, number: int, caption: str, warnings: list[str]):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.space_before = Pt(6)
    try:
        if ev.mime == "image/webp":
            raise ValueError("webp")
        img = DocxImage.from_file(ev.path)
        w_cm = (img.px_width / (img.horz_dpi or 96)) * 2.54
        h_cm = (img.px_height / (img.vert_dpi or 96)) * 2.54
        scale = min(1.0, MAX_IMG_W_CM / w_cm, MAX_IMG_H_CM / h_cm)
        p.add_run().add_picture(ev.path, width=Cm(w_cm * scale))
    except Exception:  # noqa: BLE001 — formato no incrustable o fichero ausente: marcador visible
        r = p.add_run(f"[{L['evidence']} {number}: {caption or ev.filename}]")
        r.font.highlight_color = WD_COLOR_INDEX.YELLOW
        warnings.append(f"Evidencia {number} ({ev.filename}) no se pudo incrustar")
        p.paragraph_format.keep_with_next = False
        return
    cp = doc.add_paragraph(style="EvidenceCaption")
    cp.add_run(f"{L['evidence']} {number}: {caption or ev.caption or ev.filename}")


def _render(doc, L, text: str, evidence: list | None = None, warnings: list[str] | None = None):
    warnings = warnings if warnings is not None else []
    for b in parse_blocks(text):
        if b.kind == "p":
            p = doc.add_paragraph()
            for i, line in enumerate(b.text.split("\n")):
                if i:
                    p.add_run().add_break()
                _runs(p, line)
        elif b.kind == "ul":
            for level, item in b.items:
                _runs(doc.add_paragraph(style="List Bullet 2" if level else "List Bullet"), item)
        elif b.kind == "code":
            lines = b.text.split("\n") or [""]
            for i, line in enumerate(lines):
                p = doc.add_paragraph(style="CodeBlock")
                p.add_run(line or " ")
                _p_shade(p, GREY_FILL)
                p.paragraph_format.keep_together = True
                if i == len(lines) - 1:
                    p.paragraph_format.space_after = Pt(8)
        elif b.kind == "evidence":
            ev = evidence[b.number - 1] if evidence and 0 < b.number <= len(evidence) else None
            if ev:
                _picture(doc, ev, L, b.number, b.text, warnings)
            else:
                p = doc.add_paragraph()
                r = p.add_run(f"[{L['evidence']} {b.number}: {b.text or '…'}]")
                r.font.highlight_color = WD_COLOR_INDEX.YELLOW


def _section_text(doc, L, text: str, what: str):
    if text.strip():
        _render(doc, L, text)
    else:
        _pending(doc, L, what)


# ---------------------------------------------------------------- tablas

def _table(doc, headers: list[str], rows: list[list[str]], widths: list[float]):
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment, t.autofit = WD_TABLE_ALIGNMENT.CENTER, False
    _table_borders(t)
    _cell_margins(t)
    _row_flags(t.rows[0], header=True)
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        c.width = Cm(widths[i])
        _cell_shade(c, BLACK)
        p = c.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(h)
        _set_font(r.font, FONT, 9, bold=True, color="FFFFFF")
    for row in rows:
        cells = t.add_row().cells
        _row_flags(t.rows[-1])
        for i, val in enumerate(row):
            cells[i].width = Cm(widths[i])
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(val)
            r.font.size = Pt(9)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)
    return t


def _kv_table(doc, rows: list[tuple[str, str, str | None]], label_w: float = 4.2):
    """(etiqueta, valor, color_hex_opcional para el valor)."""
    t = doc.add_table(rows=0, cols=2)
    t.alignment, t.autofit = WD_TABLE_ALIGNMENT.CENTER, False
    _table_borders(t)
    _cell_margins(t)
    for label, value, color in rows:
        cells = t.add_row().cells
        _row_flags(t.rows[-1])
        cells[0].width, cells[1].width = Cm(label_w), Cm(CONTENT_WIDTH_CM - label_w)
        _cell_shade(cells[0], GREY_FILL)
        for cell, text, bold in ((cells[0], label, True), (cells[1], value, False)):
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(text)
            r.font.size = Pt(9.5)
            r.bold = bold or bool(color and cell is cells[1])
            if color and cell is cells[1]:
                r.font.color.rgb = rgb(color)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


# ---------------------------------------------------------------- partes del documento

def _cover(doc, ctx: ReportContext, L):
    d = ctx.data
    for _ in range(8):
        doc.add_paragraph()
    bar = doc.add_paragraph()
    _p_border(bar._p.get_or_add_pPr(), "top", ACCENT, size=36, space=10)
    t = doc.add_paragraph()
    r = t.add_run(L["title"])
    _set_font(r.font, FONT, 30, bold=True, color=BLACK)
    t.paragraph_format.space_after = Pt(6)
    s = doc.add_paragraph()
    r = s.add_run(d.dut_name or f"[{L['pending']}]")
    _set_font(r.font, FONT, 18, color=BLACK)
    c = doc.add_paragraph()
    r = c.add_run(ctx.campaign.name)
    _set_font(r.font, FONT, 12, color=GREY_TEXT)
    for _ in range(6):
        doc.add_paragraph()
    rows = [(L["client"], d.client or f"[{L['pending']}]"), (L["dut"], d.dut_name or f"[{L['pending']}]"), (L["test_type"], L["test_types"][d.test_type]),
            (L["version"], d.version), (L["date"], ctx.report_date.isoformat()), (L["author"], d.author or f"[{L['pending']}]"), (L["classification"], d.classification)]
    t = doc.add_table(rows=0, cols=2)
    t.autofit = False
    _table_borders(t, GREY_LINE, inside=True, outer=False)
    _cell_margins(t)
    for label, value in rows:
        cells = t.add_row().cells
        cells[0].width, cells[1].width = Cm(4.2), Cm(11.8)
        for cell, text, bold in ((cells[0], label, True), (cells[1], value, False)):
            para = cell.paragraphs[0]
            para.paragraph_format.space_after = Pt(0)
            run = para.add_run(text)
            run.font.size = Pt(10)
            run.bold = bold
    doc.add_page_break()


def _header_footer(doc, ctx: ReportContext, L):
    sec = doc.sections[0]
    hp = sec.header.paragraphs[0]
    hp.add_run("\t")
    r = hp.add_run(f"{L['title']} · {ctx.data.dut_name or ctx.campaign.name}")
    _set_font(r.font, FONT, 8.5, color=GREY_TEXT)
    _right_tab(hp)
    _p_border(hp._p.get_or_add_pPr(), "bottom", GREY_LINE, size=4, space=6)

    fp = sec.footer.paragraphs[0]
    fp.add_run(f"{ctx.data.classification}\t")
    fp.add_run(f"{L['page']} ")
    _field(fp, "PAGE", "1")
    fp.add_run(f" {L['of']} ")
    _field(fp, "NUMPAGES", "1")
    for r in fp.runs:
        _set_font(r.font, FONT, 8.5, color=GREY_TEXT)
    _right_tab(fp)


def _toc(doc, L):
    doc.add_paragraph(L["toc"], style="TocTitle")
    p = doc.add_paragraph()
    ph = _field(p, 'TOC \\o "1-3" \\h \\z \\u', "")
    ph.text = {"es": "Actualiza este campo (clic derecho → Actualizar campo) para generar el índice.",
               "en": "Update this field (right-click → Update field) to generate the table of contents."}[L["lang"]]
    doc.add_page_break()


def _intro_text(ctx: ReportContext, key: str, default_key: str, L) -> str:
    text = getattr(ctx.data, key).strip()
    if text:
        return text
    client = L["client_part"].format(client=ctx.data.client) if ctx.data.client else ""
    return L[default_key].format(dut=ctx.data.dut_name or f"[{L['pending']}]", client=client)


def _discovery(doc, ctx: ReportContext, L):
    doc.add_paragraph(L["assets"], style="Heading 2")
    if ctx.assets:
        rows = []
        for a in ctx.assets:
            ports = ", ".join(f"{p['port']}/{p['proto']} {p.get('service', '')}".strip() for p in a.ports)
            rows.append([a.ip, a.hostname, (a.mac + (f" ({a.vendor})" if a.vendor else "")).strip(), ports])
        _table(doc, [L["col_ip"], L["col_host"], L["col_mac"], L["col_ports"]], rows, [3.0, 3.2, 4.3, 5.5])
    else:
        doc.add_paragraph(L["no_assets"])
    doc.add_paragraph(L["flows"], style="Heading 2")
    if ctx.flows:
        rows = [[f.src_ip, f.dst_ip, f.protocol, f"{f.transport}/{f.port}", str(f.packets)] for f in ctx.flows]
        _table(doc, [L["col_src"], L["col_dst"], L["col_proto"], L["col_port"], L["col_pkts"]], rows, [3.4, 3.4, 3.8, 2.7, 2.7])
        if ctx.flows_total > len(ctx.flows):
            doc.add_paragraph(L["flows_more"].format(n=len(ctx.flows), total=ctx.flows_total)).runs[0].italic = True
    else:
        doc.add_paragraph(L["no_flows"])
    if ctx.captures:
        doc.add_paragraph(L["captures"], style="Heading 2")
        for cap in ctx.captures:
            _runs(doc.add_paragraph(style="List Bullet"), f"{cap.filename} — {cap.packets} pkts · sha256 `{cap.sha256[:16]}…`")


def _findings(doc, ctx: ReportContext, L, warnings: list[str]):
    if not ctx.findings:
        doc.add_paragraph(L["no_findings"])
        return
    doc.add_paragraph(L["findings_summary"], style="Heading 2")
    counts = [[r or "–", str(ctx.rating_counts[r])] for r in RATING_ORDER if ctx.rating_counts[r]]
    _table(doc, [L["col_crit"], "#"], counts, [4.0, 2.0])
    rows = []
    for v in ctx.findings:
        score = f" ({v.f.cvss_score:g})" if v.f.cvss_score is not None else ""
        rows.append([finding_label(v.f), v.f.name, (v.rating or "–") + score, L["phases"][v.f.phase.value]])
    _table(doc, [L["col_id"], L["col_name"], L["col_crit"], L["col_phase"]], rows, [2.2, 8.0, 3.0, 2.8])

    n = 0
    for phase in PHASE_ORDER:
        group = [v for v in ctx.findings if v.f.phase.value == phase]
        if not group:
            continue
        n += 1
        doc.add_paragraph(f"8.{n} {L['phases'][phase]}", style="Heading 2")
        for v in group:
            f = v.f
            doc.add_paragraph(f"{finding_label(f)} {f.name}", style="Heading 3")
            if f.cvss_score is not None:
                crit = f"{v.rating} ({f.cvss_score:g})" + (f": {f.cvss_vector}" if f.cvss_vector else "")
            else:
                crit = f"[{L['pending']}]"
            rows = [(L["f_id"], finding_label(f), None), (L["f_name"], f.name, None), (L["f_crit"], crit, RATING_COLOR[v.rating]),
                    (L["f_assets"], ", ".join(v.assets) or "–", None)]
            if v.depends_label:
                rows.append((L["f_dep"], v.depends_label, None))
            _kv_table(doc, rows)
            doc.add_paragraph(L["f_desc"], style="FindingLabel")
            _section_text(doc, L, f.description, "")
            doc.add_paragraph(L["f_poc"], style="FindingLabel")
            if f.poc.strip():
                _render(doc, L, f.poc, v.evidence, warnings)
            else:
                _pending(doc, L)
            doc.add_paragraph(L["f_impact"], style="FindingLabel")
            _section_text(doc, L, f.impact, "")
            doc.add_paragraph(L["f_rec"], style="FindingLabel")
            _section_text(doc, L, f.recommendations, "")


def build_docx(ctx: ReportContext, out: Path) -> list[str]:
    """Genera el .docx. Devuelve avisos adicionales de maquetación (p. ej. imágenes no incrustables)."""
    ctx = _sanitize(ctx)
    L = {**LABELS[ctx.data.language], "lang": ctx.data.language}
    S, d, c = L["sections"], ctx.data, ctx.campaign
    warnings: list[str] = []
    doc = Document()
    _setup(doc)
    _header_footer(doc, ctx, L)
    _cover(doc, ctx, L)
    _toc(doc, L)

    doc.add_paragraph(f"1. {S[0]}", style="Heading 1")
    _render(doc, L, _intro_text(ctx, "introduction", "intro_default", L))
    doc.add_paragraph(f"2. {S[1]}", style="Heading 1")
    _render(doc, L, _intro_text(ctx, "methodology", "method_default", L))
    doc.add_paragraph(f"3. {S[2]}", style="Heading 1")
    period = f"{c.start_date}" + (f" – {c.end_date}" if c.end_date else "")
    doc.add_paragraph(f"{L['audit_type']}: {c.audit_type.value} · {L['period']}: {period}")
    doc.add_paragraph(L["scope_intro"])
    for line in _lines(c.scope) or ["–"]:
        doc.add_paragraph(line, style="List Bullet")
    doc.add_paragraph(f"4. {S[3]}", style="Heading 1")
    _section_text(doc, L, d.dut_description, "")
    doc.add_paragraph(f"5. {S[4]}", style="Heading 1")
    _discovery(doc, ctx, L)
    doc.add_paragraph(f"6. {S[5]}", style="Heading 1")
    _section_text(doc, L, d.exploitation_summary, "")
    doc.add_paragraph(f"7. {S[6]}", style="Heading 1")
    _section_text(doc, L, d.remediation_summary, "")
    doc.add_paragraph(f"8. {S[7]}", style="Heading 1")
    _findings(doc, ctx, L, warnings)
    doc.add_paragraph(f"9. {S[8]}", style="Heading 1")
    _section_text(doc, L, d.conclusions, "")

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return warnings
