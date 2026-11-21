"""Instantánea de la campaña para el primer mensaje del chat (valores reales; se seudonimiza al enviar)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Asset, Campaign, Capture, Finding, Flow, ToolRun, rating_from_score

LIMIT = 12_000


def _cut(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def build_context(db: Session, campaign: Campaign) -> str:
    cid = campaign.id
    out = [
        "<campaign_context>",
        f"Campaña: {campaign.name} · tipo {campaign.audit_type.value} · inicio {campaign.start_date} · estado {campaign.status.value}",
        "Alcance autorizado (una entrada por línea):",
        campaign.scope or "(vacío)",
    ]

    assets = db.scalars(select(Asset).where(Asset.campaign_id == cid).order_by(Asset.id)).all()
    out.append(f"\nActivos ({len(assets)}):")
    for a in assets[:60]:
        ports = ", ".join(f"{p['port']}/{p['proto']} {p.get('service', '')}".strip() for p in a.ports[:12])
        out.append(f"- {a.ip} {a.hostname} {a.vendor} [{ports}] fuentes={','.join(a.sources)}".replace("  ", " "))
    if len(assets) > 60:
        out.append(f"- … y {len(assets) - 60} más (usa get_assets)")

    flows = db.scalars(select(Flow).where(Flow.campaign_id == cid).order_by(Flow.packets.desc()).limit(30)).all()
    caps = db.scalars(select(Capture).where(Capture.campaign_id == cid)).all()
    out.append(f"\nCapturas: {len(caps)} · flujos principales (cliente→servidor):")
    for f in flows:
        out.append(f"- {f.src_ip} → {f.dst_ip} {f.protocol} {f.transport}/{f.port} {f.packets} pkts")

    findings = db.scalars(select(Finding).where(Finding.campaign_id == cid).order_by(Finding.id)).all()
    out.append(f"\nHallazgos ({len(findings)}):")
    for f in findings[:40]:
        out.append(f"- #{f.id} {f.identifier or '[ID]'} {f.name} · {f.phase.value} · {rating_from_score(f.cvss_score) or 'sin CVSS'} · {f.status.value}")

    runs = db.scalars(select(ToolRun).where(ToolRun.campaign_id == cid).order_by(ToolRun.id.desc()).limit(5)).all()
    out.append("\nÚltimas ejecuciones (más reciente primero):")
    for r in runs:
        out.append(f"- run {r.id} {r.server}/{r.tool} {r.arguments} → {r.status.value}: {_cut(r.output or r.error, 600)}")
    out.append("</campaign_context>")
    text = "\n".join(out)
    return text if len(text) <= LIMIT else text[: LIMIT - 40] + "\n[contexto truncado]\n</campaign_context>"
