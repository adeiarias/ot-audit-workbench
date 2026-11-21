"""Convierte la salida de las herramientas en Asset (upsert por campaña+IP)."""
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import Asset, Campaign, Capture, Flow, FlowEvent, ToolRun
from .scope import is_special_address, target_in_scope


def _upsert(db: Session, campaign_id: int, ip: str, source: str, *, hostname="", mac="", vendor="", ports=()) -> Asset:
    asset = db.scalar(select(Asset).where(Asset.campaign_id == campaign_id, Asset.ip == ip))
    if asset is None:
        asset = Asset(campaign_id=campaign_id, ip=ip, ports=[], sources=[])
        db.add(asset)
    asset.hostname = hostname or asset.hostname
    asset.mac = mac or asset.mac
    asset.vendor = vendor or asset.vendor
    merged = {(p["port"], p["proto"]): p for p in asset.ports}
    for p in ports:
        key = (p["port"], p["proto"])
        # no pisar datos ya conocidos con vacíos
        merged[key] = {**merged.get(key, {}), **{k: v for k, v in p.items() if v not in ("", None)}}
    asset.ports = sorted(merged.values(), key=lambda p: (p["proto"], p["port"]))
    if source not in asset.sources:
        asset.sources = [*asset.sources, source]
    asset.last_seen = datetime.now(timezone.utc)
    return asset


def parse_nmap(db: Session, run: ToolRun, xml_text: str) -> int:
    campaign_id = run.campaign_id
    root = ET.fromstring(xml_text)
    count = 0
    for host in root.findall("host"):
        status = host.find("status")
        if status is None or status.get("state") != "up":
            continue
        ip = mac = vendor = ""
        for addr in host.findall("address"):
            if addr.get("addrtype") in ("ipv4", "ipv6"):
                ip = addr.get("addr", "")
            elif addr.get("addrtype") == "mac":
                mac, vendor = addr.get("addr", ""), addr.get("vendor", "")
        if not ip:
            continue
        hn = host.find("hostnames/hostname")
        ports = []
        for p in host.findall("ports/port"):
            st = p.find("state")
            if st is None or st.get("state") != "open":
                continue
            svc = p.find("service")
            ports.append({
                "port": int(p.get("portid")),
                "proto": p.get("protocol", "tcp"),
                "service": svc.get("name", "") if svc is not None else "",
                "product": svc.get("product", "") if svc is not None else "",
                "version": svc.get("version", "") if svc is not None else "",
            })
        _upsert(db, campaign_id, ip, "nmap", hostname=hn.get("name", "") if hn is not None else "", mac=mac, vendor=vendor, ports=ports)
        count += 1
    return count


def parse_modbus(db: Session, run: ToolRun, output: str) -> int:
    campaign_id = run.campaign_id
    data = json.loads(output)
    if not data.get("ok") and "exception_code" not in data:
        return 0
    # Una respuesta Modbus válida (incluso una excepción Modbus) confirma el servicio.
    _upsert(db, campaign_id, data["host"], "modbus", ports=[{"port": data["port"], "proto": "tcp", "service": "modbus"}])
    return 1


def parse_tshark(db: Session, run: ToolRun, output: str) -> int:
    """Flujos del pcap → Flow (reemplaza los de esa captura). Assets solo para IPs unicast EN ALCANCE."""
    campaign = db.get(Campaign, run.campaign_id)
    capture = db.scalar(select(Capture).where(Capture.campaign_id == run.campaign_id, Capture.path == run.arguments["path"]))
    if capture is None:
        raise ValueError("Captura no encontrada para este análisis")
    data = json.loads(output)

    db.execute(delete(Flow).where(Flow.capture_id == capture.id))
    db.execute(delete(FlowEvent).where(FlowEvent.capture_id == capture.id))
    ips: set[str] = set()
    for f in data["flows"]:
        db.add(Flow(
            campaign_id=run.campaign_id, capture_id=capture.id,
            src_ip=f["src"], dst_ip=f["dst"], transport=f["transport"], port=f["port"], protocol=f["protocol"],
            packets=f["packets"], bytes=f["bytes"],
            first_seen=datetime.fromtimestamp(f["first"], timezone.utc), last_seen=datetime.fromtimestamp(f["last"], timezone.utc),
        ))
        ips.update((f["src"], f["dst"]))
    for e in data.get("events", []):
        db.add(FlowEvent(
            campaign_id=run.campaign_id, capture_id=capture.id, src_ip=e["src"], dst_ip=e["dst"], transport=e["transport"], port=e["port"],
            protocol=e["protocol"], direction=e["direction"], kind=e["kind"], summary=e["summary"][:300], detail=e["detail"], count=e["count"],
            first_seen=datetime.fromtimestamp(e["first"], timezone.utc), last_seen=datetime.fromtimestamp(e["last"], timezone.utc),
            secret=e["secret"], secret_kind=e["secret_kind"],
        ))
    macs = {h["ip"]: h["mac"] for h in data["hosts"]}
    ips.update(macs)
    for ip in sorted(ips):
        if not is_special_address(ip) and target_in_scope(ip, campaign.scope):
            _upsert(db, run.campaign_id, ip, "tshark", mac=macs.get(ip, ""))

    capture.packets = data["packets"]
    capture.non_ip_packets = data["non_ip_packets"]
    capture.status = "analyzed"
    capture.error = ""
    return len(data["flows"])


PARSERS = {("nmap", "nmap_scan"): parse_nmap, ("modbus", "modbus_read"): parse_modbus, ("tshark", "pcap_flows"): parse_tshark}
