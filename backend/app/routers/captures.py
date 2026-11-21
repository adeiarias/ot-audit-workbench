import asyncio
import hashlib
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .. import events, runs
from ..db import CAPTURES_ROOT, get_db
from ..models import Asset, Campaign, Capture, Flow, FlowEvent, ToolRun
from ..schemas import CaptureOut
from ..scope import is_special_address, target_in_scope
from ..security import origin_allowed

router = APIRouter(prefix="/api", tags=["captures"])

MAX_CAPTURE_BYTES = 500 * 1024 * 1024
_PCAP_MAGICS = {bytes.fromhex(h) for h in ("a1b2c3d4", "d4c3b2a1", "a1b23c4d", "4d3cb2a1")}
_PCAPNG_MAGIC = bytes.fromhex("0a0d0d0a")


def _campaign(db: Session, campaign_id: int) -> Campaign:
    c = db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaña no encontrada")
    return c


def _start_analysis(db: Session, capture: Capture) -> None:
    capture.status, capture.error = "analyzing", ""
    run = ToolRun(campaign_id=capture.campaign_id, server="tshark", tool="pcap_flows", arguments={"path": capture.path})
    db.add(run)
    db.commit()
    runs.spawn(run.id)


@router.post("/campaigns/{campaign_id}/captures", response_model=CaptureOut, status_code=201)
async def upload_capture(campaign_id: int, file: UploadFile, db: Session = Depends(get_db)):
    _campaign(db, campaign_id)
    directory = CAPTURES_ROOT / str(campaign_id) / "pcaps"
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".upload-{uuid.uuid4().hex}"
    sha, size, magic = hashlib.sha256(), 0, b""
    try:
        with open(tmp, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                if not magic:
                    magic = chunk[:4]
                size += len(chunk)
                if size > MAX_CAPTURE_BYTES:
                    raise HTTPException(413, f"Captura demasiado grande (máx. {MAX_CAPTURE_BYTES // 1024 // 1024} MB)")
                sha.update(chunk)
                out.write(chunk)
        if magic not in _PCAP_MAGICS and magic != _PCAPNG_MAGIC:
            raise HTTPException(422, "El fichero no parece un pcap/pcapng")
        digest = sha.hexdigest()
        if db.scalar(select(Capture).where(Capture.campaign_id == campaign_id, Capture.sha256 == digest)):
            raise HTTPException(409, "Esta captura ya está subida en la campaña")
        capture = Capture(
            campaign_id=campaign_id, filename=os.path.basename(file.filename or "captura")[:255],
            path="", sha256=digest, size=size,
        )
        db.add(capture)
        db.flush()  # obtiene el id
        final = directory / f"{capture.id}{'.pcapng' if magic == _PCAPNG_MAGIC else '.pcap'}"
        os.replace(tmp, final)
        capture.path = str(final)
        _start_analysis(db, capture)
        return capture
    finally:
        tmp.unlink(missing_ok=True)


@router.get("/campaigns/{campaign_id}/captures", response_model=list[CaptureOut])
def list_captures(campaign_id: int, db: Session = Depends(get_db)):
    _campaign(db, campaign_id)
    return db.scalars(select(Capture).where(Capture.campaign_id == campaign_id).order_by(Capture.id.desc())).all()


def _capture(db: Session, capture_id: int) -> Capture:
    c = db.get(Capture, capture_id)
    if c is None:
        raise HTTPException(404, "Captura no encontrada")
    return c


@router.post("/captures/{capture_id}/reanalyze", response_model=CaptureOut)
async def reanalyze(capture_id: int, db: Session = Depends(get_db)):
    capture = _capture(db, capture_id)
    _start_analysis(db, capture)
    return capture


@router.delete("/captures/{capture_id}", status_code=204)
def delete_capture(capture_id: int, db: Session = Depends(get_db)):
    capture = _capture(db, capture_id)
    campaign_id, path = capture.campaign_id, Path(capture.path)
    db.delete(capture)  # los Flow caen por ON DELETE CASCADE; los Asset se conservan
    db.commit()
    path.unlink(missing_ok=True)
    events.publish(campaign_id, {"type": "changed"})


@router.get("/campaigns/{campaign_id}/graph")
def graph(campaign_id: int, db: Session = Depends(get_db)):
    """Mapa lógico: nodos (activos + extremos vistos en flujos) y aristas agregadas entre capturas."""
    campaign = _campaign(db, campaign_id)
    edges: dict[tuple, dict] = {}
    for f in db.scalars(select(Flow).where(Flow.campaign_id == campaign_id)):
        key = (f.src_ip, f.dst_ip, f.transport, f.port, f.protocol)
        e = edges.setdefault(key, {"src": f.src_ip, "dst": f.dst_ip, "transport": f.transport, "port": f.port,
                                   "protocol": f.protocol, "packets": 0, "bytes": 0})
        e["packets"] += f.packets
        e["bytes"] += f.bytes

    # Contenido de protocolo por arista (cliente, servidor, transporte, puerto): nº de eventos y de credenciales en claro
    counts = {
        (r.src_ip, r.dst_ip, r.transport, r.port): (r.events, r.secrets)
        for r in db.execute(
            select(FlowEvent.src_ip, FlowEvent.dst_ip, FlowEvent.transport, FlowEvent.port, func.count().label("events"),
                   func.sum(case((FlowEvent.secret, 1), else_=0)).label("secrets"))
            .where(FlowEvent.campaign_id == campaign_id).group_by(FlowEvent.src_ip, FlowEvent.dst_ip, FlowEvent.transport, FlowEvent.port)
        )
    }
    for e in edges.values():
        e["events"], e["secrets"] = counts.get((e["src"], e["dst"], e["transport"], e["port"]), (0, 0))

    assets = {a.ip: a for a in db.scalars(select(Asset).where(Asset.campaign_id == campaign_id))}
    ips = set(assets) | {e["src"] for e in edges.values()} | {e["dst"] for e in edges.values()}
    nodes = []
    for ip in sorted(ips):
        a = assets.get(ip)
        nodes.append({
            "ip": ip,
            "kind": "multicast" if is_special_address(ip) else "host",
            "in_scope": target_in_scope(ip, campaign.scope),
            "is_asset": a is not None,
            "hostname": a.hostname if a else "",
            "mac": a.mac if a else "",
            "vendor": a.vendor if a else "",
        })
    return {"nodes": nodes, "edges": sorted(edges.values(), key=lambda e: -e["packets"])}


@router.get("/campaigns/{campaign_id}/events")
def flow_events(campaign_id: int, src: str, dst: str, port: int, transport: str = "tcp", db: Session = Depends(get_db)):
    """Contenido de protocolo observado en un flujo (cliente→servidor). Credenciales y operaciones de escritura/control primero."""
    _campaign(db, campaign_id)
    rows = db.scalars(
        select(FlowEvent).where(FlowEvent.campaign_id == campaign_id, FlowEvent.src_ip == src, FlowEvent.dst_ip == dst,
                                FlowEvent.port == port, FlowEvent.transport == transport)
    ).all()
    order = {"auth": 0, "control": 1, "write": 2, "request": 3, "response": 4}
    rows.sort(key=lambda e: (not e.secret, order.get(e.kind, 5), -e.count))
    return [
        {"id": e.id, "protocol": e.protocol, "direction": e.direction, "kind": e.kind, "summary": e.summary, "detail": e.detail,
         "count": e.count, "first_seen": e.first_seen, "last_seen": e.last_seen, "secret": e.secret, "secret_kind": e.secret_kind}
        for e in rows
    ]


@router.websocket("/campaigns/{campaign_id}/ws")
async def campaign_events(websocket: WebSocket, campaign_id: int):
    if not origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    queue = events.subscribe(campaign_id)
    receiver = asyncio.ensure_future(websocket.receive())  # detecta desconexión del cliente
    try:
        while True:
            getter = asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait({getter, receiver}, return_when=asyncio.FIRST_COMPLETED)
            if receiver in done:
                getter.cancel()
                break
            await websocket.send_json(getter.result())
    except WebSocketDisconnect:
        pass
    finally:
        receiver.cancel()
        events.unsubscribe(campaign_id, queue)
