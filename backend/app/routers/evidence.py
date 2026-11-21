import hashlib
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import events
from ..db import CAPTURES_ROOT, get_db
from ..models import Campaign, Evidence, Finding
from ..schemas import EvidenceOut, EvidenceUpdate

router = APIRouter(prefix="/api", tags=["evidence"])

MAX_EVIDENCE_BYTES = 20 * 1024 * 1024


def sniff_image(head: bytes) -> tuple[str, str] | None:
    """(mime, extensión) por firma binaria. Solo formatos raster: SVG queda fuera a propósito (puede llevar scripts)."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", ".gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def _evidence(db: Session, evidence_id: int) -> Evidence:
    e = db.get(Evidence, evidence_id)
    if e is None:
        raise HTTPException(404, "Evidencia no encontrada")
    return e


def _next_position(db: Session, finding_id: int) -> int:
    return (db.scalar(select(func.max(Evidence.position)).where(Evidence.finding_id == finding_id)) or 0) + 1


def _check_finding(db: Session, campaign_id: int, finding_id: int) -> None:
    f = db.get(Finding, finding_id)
    if f is None or f.campaign_id != campaign_id:
        raise HTTPException(422, "El hallazgo no existe en esta campaña")


@router.post("/campaigns/{campaign_id}/evidence", response_model=EvidenceOut, status_code=201)
async def upload_evidence(
    campaign_id: int,
    file: UploadFile,
    caption: str = Form("", max_length=500),
    finding_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    if db.get(Campaign, campaign_id) is None:
        raise HTTPException(404, "Campaña no encontrada")
    if finding_id is not None:
        _check_finding(db, campaign_id, finding_id)
    directory = CAPTURES_ROOT / str(campaign_id) / "evidence"
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".upload-{uuid.uuid4().hex}"
    sha, size, head = hashlib.sha256(), 0, b""
    try:
        with open(tmp, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                if len(head) < 16:
                    head += chunk[: 16 - len(head)]
                size += len(chunk)
                if size > MAX_EVIDENCE_BYTES:
                    raise HTTPException(413, f"Imagen demasiado grande (máx. {MAX_EVIDENCE_BYTES // 1024 // 1024} MB)")
                sha.update(chunk)
                out.write(chunk)
        kind = sniff_image(head)
        if kind is None:
            raise HTTPException(422, "Formato no admitido: solo PNG, JPEG, GIF o WebP")
        digest = sha.hexdigest()
        if db.scalar(select(Evidence).where(Evidence.campaign_id == campaign_id, Evidence.sha256 == digest)):
            raise HTTPException(409, "Esta imagen ya está subida en la campaña")
        ev = Evidence(
            campaign_id=campaign_id, finding_id=finding_id, filename=os.path.basename(file.filename or "imagen")[:255],
            path="", mime=kind[0], sha256=digest, size=size, caption=caption,
            position=_next_position(db, finding_id) if finding_id else 0,
        )
        db.add(ev)
        db.flush()
        final = directory / f"{ev.id}{kind[1]}"
        os.replace(tmp, final)
        ev.path = str(final)
        db.commit()
        events.publish(campaign_id, {"type": "changed"})
        return ev
    finally:
        tmp.unlink(missing_ok=True)


@router.get("/campaigns/{campaign_id}/evidence", response_model=list[EvidenceOut])
def list_evidence(campaign_id: int, db: Session = Depends(get_db)):
    if db.get(Campaign, campaign_id) is None:
        raise HTTPException(404, "Campaña no encontrada")
    return db.scalars(select(Evidence).where(Evidence.campaign_id == campaign_id).order_by(Evidence.id)).all()


@router.patch("/evidence/{evidence_id}", response_model=EvidenceOut)
def update_evidence(evidence_id: int, payload: EvidenceUpdate, db: Session = Depends(get_db)):
    ev = _evidence(db, evidence_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("caption") is not None:
        ev.caption = changes["caption"]
    if "finding_id" in changes and changes["finding_id"] != ev.finding_id:
        new = changes["finding_id"]
        if new is None:
            ev.finding_id, ev.position = None, 0
        else:
            _check_finding(db, ev.campaign_id, new)
            ev.finding_id, ev.position = new, _next_position(db, new)
    db.commit()
    events.publish(ev.campaign_id, {"type": "changed"})
    return ev


@router.delete("/evidence/{evidence_id}", status_code=204)
def delete_evidence(evidence_id: int, db: Session = Depends(get_db)):
    ev = _evidence(db, evidence_id)
    campaign_id, path = ev.campaign_id, Path(ev.path)
    db.delete(ev)
    db.commit()
    path.unlink(missing_ok=True)
    events.publish(campaign_id, {"type": "changed"})


@router.get("/evidence/{evidence_id}/file")
def evidence_file(evidence_id: int, db: Session = Depends(get_db)):
    ev = _evidence(db, evidence_id)
    path = Path(ev.path)
    if not path.is_file():
        raise HTTPException(404, "Fichero no encontrado en disco")
    return FileResponse(path, media_type=ev.mime, headers={
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, max-age=3600",  # el contenido es inmutable (id ligado al hash)
    })
