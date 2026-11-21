from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Asset, Campaign, Capture, Evidence, Finding, Flow, ScopeChange, ToolRun, rating_from_score
from ..report.collect import build_context, load_data
from ..scope import parse_scope, target_in_scope

router = APIRouter(prefix="/api", tags=["summary"])


def _count(db: Session, model, campaign_id: int) -> int:
    return db.scalar(select(func.count()).select_from(model).where(model.campaign_id == campaign_id)) or 0


@router.get("/campaigns/{campaign_id}/summary")
def summary(campaign_id: int, db: Session = Depends(get_db)):
    c = db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaña no encontrada")
    assets = list(db.scalars(select(Asset).where(Asset.campaign_id == campaign_id)))
    findings = list(db.scalars(select(Finding).where(Finding.campaign_id == campaign_id)))
    by_rating = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "None": 0, "": 0}
    by_phase = {"discovery": 0, "exploitation": 0, "post_exploitation": 0}
    by_status = {"draft": 0, "confirmed": 0, "false_positive": 0}
    for f in findings:
        if f.status.value != "false_positive":  # los falsos positivos no cuentan para la criticidad
            by_rating[rating_from_score(f.cvss_score)] += 1
            by_phase[f.phase.value] += 1
        by_status[f.status.value] += 1
    runs_by_status = {s: n for s, n in db.execute(select(ToolRun.status, func.count()).where(ToolRun.campaign_id == campaign_id).group_by(ToolRun.status))}
    protocols = [
        {"protocol": p, "packets": int(pk), "flows": n}
        for p, pk, n in db.execute(select(Flow.protocol, func.sum(Flow.packets), func.count()).where(Flow.campaign_id == campaign_id)
                                   .group_by(Flow.protocol).order_by(func.sum(Flow.packets).desc()).limit(8))
    ]
    recent = db.scalars(select(ToolRun).where(ToolRun.campaign_id == campaign_id).order_by(ToolRun.id.desc()).limit(6)).all()
    rules, _ = parse_scope(c.scope)
    ctx = build_context(db, c, load_data(db, campaign_id))
    return {
        "counts": {"assets": len(assets), "assets_out_of_scope": sum(1 for a in assets if not target_in_scope(a.ip, c.scope)), "flows": _count(db, Flow, campaign_id),
                   "captures": _count(db, Capture, campaign_id), "evidence": _count(db, Evidence, campaign_id), "runs": _count(db, ToolRun, campaign_id),
                   "findings": len(findings)},
        "runs_by_status": {k.value if hasattr(k, "value") else k: v for k, v in runs_by_status.items()},
        "findings_by_rating": by_rating, "findings_by_phase": by_phase, "findings_by_status": by_status,
        "protocols": protocols,
        "recent_runs": [{"id": r.id, "server": r.server, "tool": r.tool, "arguments": r.arguments, "status": r.status.value, "origin": r.origin, "created_at": r.created_at} for r in recent],
        "scope": {"rules": [{"kind": r.kind, "value": r.value, "warning": r.warning} for r in rules], "changes": _count(db, ScopeChange, campaign_id)},
        "report_warnings": len(ctx.warnings),
    }
