"""Reúne los datos de la campaña para el informe y calcula avisos de calidad."""
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Asset, Campaign, Capture, Evidence, Finding, Flow, Report, rating_from_score
from .model import PHASE_ORDER, RATING_ORDER, ReportData
from .richtext import marker_numbers

FLOW_LIMIT = 25


@dataclass
class FindingView:
    f: Finding
    rating: str
    evidence: list[Evidence]  # ordenadas por posición: la N-ésima es «Evidencia N»
    assets: list[str]  # IPs (+ hostname) y activos sin IP
    depends_label: str


@dataclass
class ReportContext:
    campaign: Campaign
    data: ReportData
    report_date: date
    findings: list[FindingView]
    assets: list[Asset]
    flows: list[Flow]
    flows_total: int
    captures: list[Capture]
    rating_counts: dict[str, int]
    warnings: list[str] = field(default_factory=list)


def load_data(db: Session, campaign_id: int) -> ReportData:
    row = db.get(Report, campaign_id)
    return ReportData(**(row.data if row else {}))


def finding_label(f: Finding) -> str:
    return f.identifier or "[ID]"


def build_context(db: Session, campaign: Campaign, data: ReportData, include_drafts: bool = True) -> ReportContext:
    cid = campaign.id
    assets = list(db.scalars(select(Asset).where(Asset.campaign_id == cid).order_by(Asset.id)))
    by_id = {a.id: a for a in assets}
    all_findings = list(db.scalars(select(Finding).where(Finding.campaign_id == cid).order_by(Finding.id)))
    ev_all = list(db.scalars(select(Evidence).where(Evidence.campaign_id == cid).order_by(Evidence.position, Evidence.id)))
    by_finding: dict[int, list[Evidence]] = {}
    for e in ev_all:
        if e.finding_id:
            by_finding.setdefault(e.finding_id, []).append(e)
    labels = {f.id: finding_label(f) for f in all_findings}

    chosen = [f for f in all_findings if f.status.value != "false_positive" and (include_drafts or f.status.value != "draft")]
    chosen.sort(key=lambda f: (PHASE_ORDER.index(f.phase.value), f.id))
    views = []
    for f in chosen:
        names = []
        for aid in f.asset_ids:
            a = by_id.get(aid)
            if a:
                names.append(a.ip + (f" ({a.hostname})" if a.hostname else ""))
        if f.affected_other:
            names.append(f.affected_other)
        views.append(FindingView(f, rating_from_score(f.cvss_score), by_finding.get(f.id, []), names, labels.get(f.depends_on_id, "") if f.depends_on_id else ""))

    counts = {r: 0 for r in RATING_ORDER}
    for v in views:
        counts[v.rating] += 1

    flows_total = len(list(db.scalars(select(Flow.id).where(Flow.campaign_id == cid))))
    flows = list(db.scalars(select(Flow).where(Flow.campaign_id == cid).order_by(Flow.packets.desc()).limit(FLOW_LIMIT)))
    captures = list(db.scalars(select(Capture).where(Capture.campaign_id == cid).order_by(Capture.id)))
    ctx = ReportContext(campaign, data, data.report_date or date.today(), views, assets, flows, flows_total, captures, counts)
    ctx.warnings = _warnings(ctx, all_findings, ev_all)
    return ctx


def _warnings(ctx: ReportContext, all_findings: list[Finding], ev_all: list[Evidence]) -> list[str]:
    d, w = ctx.data, []
    for key, msg in (("client", "Falta el cliente"), ("dut_name", "Falta el nombre del sistema auditado (DUT)"), ("test_type", "Falta el tipo de prueba (white/grey/black box)"),
                     ("dut_description", "Falta la descripción del DUT"), ("exploitation_summary", "Falta el Resumen de Explotación"),
                     ("remediation_summary", "Falta el Resumen de Remediaciones"), ("conclusions", "Faltan las Conclusiones")):
        if not getattr(d, key).strip():
            w.append(msg)
    if not ctx.findings:
        w.append("No hay hallazgos que incluir")
    drafts = sum(1 for v in ctx.findings if v.f.status.value == "draft")
    if drafts:
        w.append(f"{drafts} hallazgo(s) en estado «borrador» incluidos en el informe")
    fp = sum(1 for f in all_findings if f.status.value == "false_positive")
    if fp:
        w.append(f"{fp} falso(s) positivo(s) excluido(s) del informe")
    for v in ctx.findings:
        name = f"{finding_label(v.f)} {v.f.name}"
        if not v.f.identifier:
            w.append(f"«{v.f.name}»: sin identificador (se mostrará [ID])")
        if v.f.cvss_score is None:
            w.append(f"{name}: sin puntuación CVSS")
        elif not v.f.cvss_vector:
            w.append(f"{name}: tiene puntuación pero no vector CVSS")
        for key, label in (("description", "Description"), ("recommendations", "Recommendations")):
            if not getattr(v.f, key).strip():
                w.append(f"{name}: {label} vacío")
        used = marker_numbers(v.f.poc)
        for n in sorted(used):
            if n > len(v.evidence):
                w.append(f"{name}: el PoC cita «Evidencia {n}» pero solo hay {len(v.evidence)} vinculada(s)")
        for i, e in enumerate(v.evidence, 1):
            if i not in used:
                w.append(f"{name}: la Evidencia {i} ({e.filename}) está vinculada pero no se cita en el PoC")
            if e.mime == "image/webp":
                w.append(f"{name}: la Evidencia {i} es WebP y no se puede incrustar en Word (se dejará un marcador)")
    unlinked = sum(1 for e in ev_all if not e.finding_id)
    if unlinked:
        w.append(f"{unlinked} evidencia(s) sin vincular a ningún hallazgo (no aparecerán en el informe)")
    return w
