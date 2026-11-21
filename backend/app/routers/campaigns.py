import shutil

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import CAPTURES_ROOT, get_db
from .. import events
from ..llm import agent
from ..models import Campaign, LLMProfile, ScopeChange
from ..schemas import CampaignCreate, CampaignOut, CampaignUpdate

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


def _get_or_404(db: Session, campaign_id: int) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaña no encontrada")
    return campaign


@router.get("", response_model=list[CampaignOut])
def list_campaigns(db: Session = Depends(get_db)):
    return db.scalars(select(Campaign).order_by(Campaign.start_date.desc(), Campaign.id.desc())).all()


@router.post("", response_model=CampaignOut, status_code=201)
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    campaign = Campaign(**payload.model_dump())
    db.add(campaign)
    db.flush()
    if campaign.scope.strip():
        db.add(ScopeChange(campaign_id=campaign.id, old_scope="", new_scope=campaign.scope))  # alcance inicial en el historial
    db.commit()
    return campaign


@router.get("/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, campaign_id)


_NULLABLE = {"end_date", "llm_profile_id"}  # el resto no admite null: se ignora si llega


@router.patch("/{campaign_id}", response_model=CampaignOut)
def update_campaign(campaign_id: int, payload: CampaignUpdate, db: Session = Depends(get_db)):
    campaign = _get_or_404(db, campaign_id)
    changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None or k in _NULLABLE}
    if changes.get("llm_profile_id") is not None and db.get(LLMProfile, changes["llm_profile_id"]) is None:
        raise HTTPException(422, "El perfil de LLM no existe")
    old_scope = campaign.scope
    for key, value in changes.items():
        setattr(campaign, key, value)
    if campaign.end_date and campaign.end_date < campaign.start_date:
        raise HTTPException(422, "end_date no puede ser anterior a start_date")
    scope_changed = "scope" in changes and changes["scope"] != old_scope
    if scope_changed:
        db.add(ScopeChange(campaign_id=campaign.id, old_scope=old_scope, new_scope=campaign.scope))
        agent.invalidate_out_of_scope_calls(db, campaign)  # acciones del asistente pendientes de aprobar y ya fuera de alcance
    db.commit()
    if scope_changed:
        events.publish(campaign.id, {"type": "changed"})
    return campaign


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, campaign_id))
    db.commit()
    shutil.rmtree(CAPTURES_ROOT / str(campaign_id), ignore_errors=True)
    return Response(status_code=204)
