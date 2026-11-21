from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm import agent, client
from ..llm.redaction import Redactor
from ..models import AgentCall, Campaign, ChatMessage

router = APIRouter(prefix="/api", tags=["chat"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


def _campaign(db: Session, campaign_id: int) -> Campaign:
    c = db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaña no encontrada")
    return c


def _http(e: agent.ChatError) -> HTTPException:
    return HTTPException(e.status, e.message)


def _llm_info(db: Session, campaign: Campaign | None) -> dict:
    s = client.resolve(db, campaign)
    return {"configured": client.configured(s), "problem": client.problem(s), "provider": s.provider, "provider_label": s.label,
            "model": s.model, "effort": s.effort, "external": s.external, "tools": s.tools,
            "profile_id": s.profile_id, "profile_name": s.profile_name, "source": s.source}


@router.get("/llm/status")
def llm_status(db: Session = Depends(get_db)):
    return _llm_info(db, None)


@router.get("/campaigns/{campaign_id}/chat")
def get_chat(campaign_id: int, db: Session = Depends(get_db)):
    campaign = _campaign(db, campaign_id)
    red = Redactor(db, campaign_id, campaign.llm_redaction)
    calls: dict[int, list[AgentCall]] = {}
    for c in db.scalars(select(AgentCall).where(AgentCall.campaign_id == campaign_id).order_by(AgentCall.id)):
        calls.setdefault(c.message_id, []).append(c)
    items = []
    for m in db.scalars(select(ChatMessage).where(ChatMessage.campaign_id == campaign_id).order_by(ChatMessage.id)):
        if m.kind == "error":
            items.append({"id": m.id, "role": "error", "text": m.api_content[0]["text"], "calls": []})
        elif m.role == "user":
            if m.display_text:  # los mensajes solo con tool_result no se muestran
                items.append({"id": m.id, "role": "user", "text": m.display_text, "calls": []})
        else:
            text = "\n\n".join(b["text"] for b in m.api_content if b.get("type") == "text")
            items.append({
                "id": m.id, "role": "assistant", "text": red.restore(text), "stop_reason": m.stop_reason,
                "calls": [{
                    "id": c.id, "name": c.name, "input": c.input, "status": c.status, "requires_approval": c.requires_approval,
                    "run_id": c.run_id, "result_preview": c.result_text[:1500],
                } for c in calls.get(m.id, [])],
            })
    last = db.scalars(select(ChatMessage).where(ChatMessage.campaign_id == campaign_id, ChatMessage.role == "assistant", ChatMessage.kind == "normal").order_by(ChatMessage.id.desc()).limit(1)).first()
    return {
        "enabled": campaign.llm_enabled, "redaction": campaign.llm_redaction, **_llm_info(db, campaign),
        "conversation_provider": (last.provider or "anthropic") if last else None,  # con qué proveedor empezó la conversación (None = vacía)
        "busy": agent.is_busy(campaign_id), "messages": items,
    }


@router.post("/campaigns/{campaign_id}/chat", status_code=202)
async def post_chat(campaign_id: int, payload: ChatIn, db: Session = Depends(get_db)):
    campaign = _campaign(db, campaign_id)
    try:
        agent.post_message(db, campaign, payload.message)
    except agent.ChatError as e:
        raise _http(e) from None
    return {"status": "accepted"}


@router.delete("/campaigns/{campaign_id}/chat", status_code=204)
def reset_chat(campaign_id: int, db: Session = Depends(get_db)):
    _campaign(db, campaign_id)
    try:
        agent.reset(db, campaign_id)
    except agent.ChatError as e:
        raise _http(e) from None
    return Response(status_code=204)


@router.post("/agent-calls/{call_id}/approve")
async def approve_call(call_id: int, db: Session = Depends(get_db)):
    await agent.mcp_tools()  # tras un reinicio la caché está vacía
    try:
        c = agent.approve(db, call_id)
    except agent.ChatError as e:
        raise _http(e) from None
    return {"id": c.id, "status": c.status, "run_id": c.run_id}


@router.post("/agent-calls/{call_id}/deny")
async def deny_call(call_id: int, db: Session = Depends(get_db)):
    try:
        c = agent.deny(db, call_id)
    except agent.ChatError as e:
        raise _http(e) from None
    return {"id": c.id, "status": c.status}
