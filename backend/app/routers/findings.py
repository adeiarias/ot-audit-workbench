from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import cvss, events
from ..db import get_db
from ..models import Asset, Campaign, Finding, rating_from_score
from ..schemas import FindingCreate, FindingOut, FindingUpdate

router = APIRouter(prefix="/api", tags=["findings"])

_NULLABLE = {"cvss_score", "depends_on_id"}  # el resto no admite null: se ignora si llega


def _campaign(db: Session, campaign_id: int) -> Campaign:
    c = db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaña no encontrada")
    return c


def _finding(db: Session, finding_id: int) -> Finding:
    f = db.get(Finding, finding_id)
    if f is None:
        raise HTTPException(404, "Hallazgo no encontrado")
    return f


def _check_identifier(db: Session, campaign_id: int, identifier: str, own_id: int | None = None) -> None:
    if not identifier:
        return
    clash = db.scalar(select(Finding).where(Finding.campaign_id == campaign_id, Finding.identifier == identifier))
    if clash is not None and clash.id != own_id:
        raise HTTPException(409, f"Ya existe un hallazgo con el identificador {identifier!r} en esta campaña")


def _resolve_assets(db: Session, campaign_id: int, asset_ids: list[int]) -> list[Asset]:
    ids = set(asset_ids)
    assets = list(db.scalars(select(Asset).where(Asset.campaign_id == campaign_id, Asset.id.in_(ids)))) if ids else []
    if len(assets) != len(ids):
        raise HTTPException(422, "Algún activo no existe o no pertenece a esta campaña")
    return assets


def _check_dependency(db: Session, campaign_id: int, depends_on_id: int | None, own_id: int | None) -> None:
    if depends_on_id is None:
        return
    if depends_on_id == own_id:
        raise HTTPException(422, "Un hallazgo no puede depender de sí mismo")
    dep = db.get(Finding, depends_on_id)
    if dep is None or dep.campaign_id != campaign_id:
        raise HTTPException(422, "El hallazgo del que depende no existe en esta campaña")
    # evita ciclos: seguir la cadena de dependencias desde el destino
    seen, cur = set(), dep
    while cur is not None and cur.id not in seen:
        if own_id is not None and cur.depends_on_id == own_id:
            raise HTTPException(422, "La dependencia crearía un ciclo")
        seen.add(cur.id)
        cur = db.get(Finding, cur.depends_on_id) if cur.depends_on_id else None


@router.get("/cvss/score")
def cvss_score(vector: str):
    """Puntuación base calculada desde un vector CVSS 3.0/3.1 (para la vista previa del editor)."""
    score = cvss.base_score(vector)
    if score is None:
        raise HTTPException(422, "Solo se calcula con vectores CVSS 3.0/3.1 completos (AV, AC, PR, UI, S, C, I, A); en CVSS 4.0 la puntuación es manual")
    return {"score": score, "rating": rating_from_score(score)}


def _sync_score(finding: Finding) -> None:
    """El vector manda: si es calculable (3.0/3.1 completo), la puntuación sale de él. Si no, se conserva la manual."""
    score = cvss.base_score(finding.cvss_vector) if finding.cvss_vector else None
    if score is not None:
        finding.cvss_score = score


@router.get("/campaigns/{campaign_id}/findings", response_model=list[FindingOut])
def list_findings(campaign_id: int, db: Session = Depends(get_db)):
    _campaign(db, campaign_id)
    return db.scalars(select(Finding).where(Finding.campaign_id == campaign_id).order_by(Finding.id)).all()


@router.post("/campaigns/{campaign_id}/findings", response_model=FindingOut, status_code=201)
def create_finding(campaign_id: int, payload: FindingCreate, db: Session = Depends(get_db)):
    _campaign(db, campaign_id)
    _check_identifier(db, campaign_id, payload.identifier)
    _check_dependency(db, campaign_id, payload.depends_on_id, None)
    data = payload.model_dump(exclude={"asset_ids"})
    finding = Finding(campaign_id=campaign_id, **data)
    finding.assets = _resolve_assets(db, campaign_id, payload.asset_ids)
    _sync_score(finding)
    db.add(finding)
    db.commit()
    events.publish(campaign_id, {"type": "changed"})
    return finding


@router.get("/findings/{finding_id}", response_model=FindingOut)
def get_finding(finding_id: int, db: Session = Depends(get_db)):
    return _finding(db, finding_id)


@router.patch("/findings/{finding_id}", response_model=FindingOut)
def update_finding(finding_id: int, payload: FindingUpdate, db: Session = Depends(get_db)):
    finding = _finding(db, finding_id)
    changes = payload.model_dump(exclude_unset=True)
    asset_ids = changes.pop("asset_ids", None)
    changes = {k: v for k, v in changes.items() if v is not None or k in _NULLABLE}
    if "identifier" in changes:
        _check_identifier(db, finding.campaign_id, changes["identifier"], finding.id)
    if "depends_on_id" in changes:
        _check_dependency(db, finding.campaign_id, changes["depends_on_id"], finding.id)
    if asset_ids is not None:
        finding.assets = _resolve_assets(db, finding.campaign_id, asset_ids)
    for key, value in changes.items():
        setattr(finding, key, value)
    _sync_score(finding)
    db.commit()
    events.publish(finding.campaign_id, {"type": "changed"})
    return finding


@router.delete("/findings/{finding_id}", status_code=204)
def delete_finding(finding_id: int, db: Session = Depends(get_db)):
    finding = _finding(db, finding_id)
    campaign_id = finding.campaign_id
    db.delete(finding)  # las evidencias quedan sin hallazgo (SET NULL), no se borran
    db.commit()
    events.publish(campaign_id, {"type": "changed"})
    return Response(status_code=204)
