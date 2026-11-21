from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import mcp_client, runs
from ..db import get_db
from ..models import Asset, Campaign, ToolRun
from ..schemas import AssetOut, RunCreate, RunOut
from ..scope import target_in_scope

router = APIRouter(prefix="/api", tags=["runs"])

_tools_cache: list[dict] | None = None


@router.get("/tools")
async def list_tools():
    global _tools_cache
    if _tools_cache is None:
        _tools_cache = await mcp_client.list_tools()
    return [t for t in _tools_cache if not t["internal"]]


def _campaign(db: Session, campaign_id: int) -> Campaign:
    c = db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaña no encontrada")
    return c


@router.post("/campaigns/{campaign_id}/runs", response_model=RunOut, status_code=201)
async def create_run(campaign_id: int, payload: RunCreate, db: Session = Depends(get_db)):
    campaign = _campaign(db, campaign_id)
    policy = mcp_client.TOOL_POLICY.get((payload.server, payload.tool))
    if policy is None or policy.internal or (policy.target_arg is None and policy.capture_arg is None):
        raise HTTPException(403, f"Herramienta no permitida: {payload.server}/{payload.tool}")
    if policy.target_arg:
        target = payload.arguments.get(policy.target_arg)
        if not isinstance(target, str) or not target_in_scope(target, campaign.scope):
            raise HTTPException(403, f"Objetivo {target!r} fuera del alcance de la campaña")
    try:
        mcp_client.bind_arguments(db, campaign_id, payload.server, payload.tool, payload.arguments)  # valida args y captura
    except mcp_client.McpToolError as e:
        raise HTTPException(422, str(e)) from None
    run = ToolRun(campaign_id=campaign_id, server=payload.server, tool=payload.tool, arguments=payload.arguments)
    db.add(run)
    db.commit()
    runs.spawn(run.id)
    return run


@router.get("/campaigns/{campaign_id}/runs", response_model=list[RunOut])
def list_runs(campaign_id: int, db: Session = Depends(get_db)):
    _campaign(db, campaign_id)
    return db.scalars(select(ToolRun).where(ToolRun.campaign_id == campaign_id).order_by(ToolRun.id.desc())).all()


@router.get("/campaigns/{campaign_id}/assets", response_model=list[AssetOut])
def list_assets(campaign_id: int, db: Session = Depends(get_db)):
    campaign = _campaign(db, campaign_id)
    return [AssetOut.model_validate(a).model_copy(update={"in_scope": target_in_scope(a.ip, campaign.scope)})
            for a in db.scalars(select(Asset).where(Asset.campaign_id == campaign_id).order_by(Asset.id))]
