import asyncio
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import CAPTURES_ROOT, get_db
from ..llm import client
from ..models import Campaign, Report
from ..report import pdf
from ..report.collect import build_context, load_data
from ..report.docx_builder import build_docx
from ..report.draft import DraftError, draft_section
from ..report.markdown import render_markdown
from ..report.model import ReportData

router = APIRouter(prefix="/api", tags=["report"])

_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "md": "text/markdown; charset=utf-8",
}


class DraftIn(BaseModel):
    section: str


def _campaign(db: Session, campaign_id: int) -> Campaign:
    c = db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaña no encontrada")
    return c


def _view(db: Session, campaign: Campaign, include_drafts: bool = True) -> dict:
    data = load_data(db, campaign.id)
    ctx = build_context(db, campaign, data, include_drafts)
    s = client.resolve(db, campaign)
    return {
        "data": data.model_dump(mode="json"), "warnings": ctx.warnings, "pdf_available": pdf.available(),
        "llm": {"enabled": campaign.llm_enabled, "configured": client.configured(s), "provider_label": s.label, "external": s.external},
    }


@router.get("/campaigns/{campaign_id}/report")
def get_report(campaign_id: int, drafts: bool = True, db: Session = Depends(get_db)):
    return _view(db, _campaign(db, campaign_id), drafts)


@router.put("/campaigns/{campaign_id}/report")
def put_report(campaign_id: int, data: ReportData, db: Session = Depends(get_db)):
    campaign = _campaign(db, campaign_id)
    row = db.get(Report, campaign_id)
    if row is None:
        db.add(Report(campaign_id=campaign_id, data=data.model_dump(mode="json")))
    else:
        row.data = data.model_dump(mode="json")
    db.commit()
    return _view(db, campaign)


@router.post("/campaigns/{campaign_id}/report/draft")
async def draft(campaign_id: int, payload: DraftIn, db: Session = Depends(get_db)):
    campaign = _campaign(db, campaign_id)
    try:
        text = await draft_section(db, campaign, load_data(db, campaign_id), payload.section)
    except DraftError as e:
        raise HTTPException(e.status, e.message) from None
    return {"section": payload.section, "text": text}


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:50] or "campana"


@router.get("/campaigns/{campaign_id}/report/export")
async def export(campaign_id: int, format: str = Query("docx", pattern="^(docx|pdf|md)$"), drafts: bool = True, db: Session = Depends(get_db)):
    campaign = _campaign(db, campaign_id)
    ctx = build_context(db, campaign, load_data(db, campaign_id), drafts)
    directory = CAPTURES_ROOT / str(campaign_id) / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    name = f"Informe_{_slug(campaign.name)}_{datetime.now():%Y%m%d-%H%M%S}.{format}"
    target = directory / name
    if format == "md":
        target.write_text(render_markdown(ctx), encoding="utf-8")
    else:
        docx_path = target if format == "docx" else target.with_suffix(".docx")
        await asyncio.to_thread(build_docx, ctx, docx_path)
        if format == "pdf":
            try:
                await pdf.docx_to_pdf(docx_path, target)
            except pdf.PdfError as e:
                raise HTTPException(503, str(e)) from None
            finally:
                docx_path.unlink(missing_ok=True)
    return FileResponse(target, media_type=_MEDIA[format], filename=name)
