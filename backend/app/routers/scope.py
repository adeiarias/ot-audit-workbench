from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Campaign, ScopeChange
from ..scope import diff_scope, parse_scope

router = APIRouter(prefix="/api", tags=["scope"])


class ScopeIn(BaseModel):
    scope: str = Field(default="", max_length=100_000)


@router.post("/scope/parse")
def parse(payload: ScopeIn):
    """Análisis en vivo para el editor: qué reconoce de cada línea y qué errores hay (con número de línea)."""
    rules, issues = parse_scope(payload.scope)
    counts = {"ip": 0, "cidr": 0, "hostname": 0}
    for r in rules:
        counts[r.kind] += 1
    return {
        "rules": [{"line": r.line, "kind": r.kind, "value": r.value, "warning": r.warning} for r in rules],
        "errors": [{"line": i.line, "text": i.text, "error": i.error} for i in issues],
        "counts": counts, "warnings": sum(1 for r in rules if r.warning),
    }


@router.get("/campaigns/{campaign_id}/scope-history")
def scope_history(campaign_id: int, db: Session = Depends(get_db)):
    if db.get(Campaign, campaign_id) is None:
        raise HTTPException(404, "Campaña no encontrada")
    out = []
    for c in db.scalars(select(ScopeChange).where(ScopeChange.campaign_id == campaign_id).order_by(ScopeChange.id.desc())):
        added, removed = diff_scope(c.old_scope, c.new_scope)
        out.append({"id": c.id, "changed_at": c.changed_at, "initial": c.old_scope == "", "added": added, "removed": removed, "old_scope": c.old_scope, "new_scope": c.new_scope})
    return out
