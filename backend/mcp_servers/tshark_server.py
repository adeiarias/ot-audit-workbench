"""MCP server (stdio) — análisis OFFLINE de pcaps con tshark (pasivo: no genera tráfico).

Seguridad: solo lee ficheros bajo AUDIT_CAPTURES_ROOT (variable obligatoria; sin ella, falla cerrado).
Devuelve un resumen JSON: hosts (IP↔MAC vía ARP), flujos agregados y eventos de protocolo (HTTP, MQTT, Modbus, S7, FTP)
agregados por flujo (qué se envió: URLs, topics, funciones, comandos; y credenciales en claro marcadas).
"""
import asyncio
import json
import os
import shutil
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import pcap_protocols as proto

mcp = MCPServer("tshark")

_FIELDS = [
    "frame.time_epoch", "frame.len", "ip.src", "ip.dst", "ipv6.src", "ipv6.dst", "ip.proto", "ipv6.nxt",
    "tcp.srcport", "tcp.dstport", "udp.srcport", "udp.dstport", "_ws.col.protocol",
    "arp.src.proto_ipv4", "arp.src.hw_mac",
]
_PROTO_NAMES = {"1": "icmp", "2": "igmp", "6": "tcp", "17": "udp", "47": "gre", "58": "icmpv6", "89": "ospf", "132": "sctp"}
_GENERIC = {"TCP", "UDP", "IPv4", "IPv6", "Data", "ICMP"}  # etiquetas poco informativas
MAX_FLOWS = 5000
MAX_EVENTS, MAX_EVENTS_PER_FLOW = 20000, 300


def _resolve(path: str) -> Path:
    root = os.environ.get("AUDIT_CAPTURES_ROOT")
    if not root:
        raise ToolError("AUDIT_CAPTURES_ROOT no definido")
    p = Path(path).resolve()
    if not p.is_relative_to(Path(root).resolve()):
        raise ToolError("Ruta fuera del directorio de capturas")
    if not p.is_file() or p.suffix.lower() not in (".pcap", ".pcapng"):
        raise ToolError("No es un fichero .pcap/.pcapng existente")
    return p


def _service_port(sport: int, dport: int) -> tuple[int, bool]:
    """Heurística: el puerto de servicio es el menor. Devuelve (puerto, dst_es_servidor)."""
    return (dport, True) if dport <= sport else (sport, False)


async def _analyze(path: Path) -> dict:
    args = ["tshark", "-r", str(path), "-n", "-T", "fields", "-E", "separator=/t", "-E", "occurrence=f"]
    for f in _FIELDS:
        args += ["-e", f]
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

    packets = non_ip = 0
    hosts: dict[str, str] = {}
    flows: dict[tuple, dict] = {}

    async def consume():
        nonlocal packets, non_ip
        assert proc.stdout is not None
        async for raw in proc.stdout:
            cols = raw.decode(errors="replace").rstrip("\n").split("\t")
            cols += [""] * (len(_FIELDS) - len(cols))
            (ts, length, ip4s, ip4d, ip6s, ip6d, ip_proto, nxt, tsp, tdp, usp, udp, label, arp_ip, arp_mac) = cols
            packets += 1
            if arp_ip and arp_mac:
                hosts[arp_ip] = arp_mac.lower()
            src, dst = ip4s or ip6s, ip4d or ip6d
            if not src or not dst:
                non_ip += 1
                continue
            if tsp and tdp:
                transport, sp, dp = "tcp", int(tsp), int(tdp)
            elif usp and udp:
                transport, sp, dp = "udp", int(usp), int(udp)
            else:
                transport, sp, dp = _PROTO_NAMES.get(ip_proto or nxt, f"ip-{ip_proto or nxt}"), 0, 0
            port, dst_is_server = _service_port(sp, dp) if sp or dp else (0, True)
            client, server = (src, dst) if dst_is_server else (dst, src)
            key = (client, server, transport, port)
            f = flows.setdefault(key, {"packets": 0, "bytes": 0, "first": float(ts or 0), "last": 0.0, "labels": {}})
            f["packets"] += 1
            f["bytes"] += int(length or 0)
            f["last"] = float(ts or 0)
            f["labels"][label] = f["labels"].get(label, 0) + 1

    try:
        await asyncio.wait_for(consume(), timeout=600)
    except asyncio.TimeoutError:
        proc.kill()
        raise ToolError("tshark superó el tiempo máximo (600 s)")
    err = (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""
    await proc.wait()
    if proc.returncode != 0 and packets == 0:
        raise ToolError(f"tshark falló (código {proc.returncode}): {err[:500]}")

    out = []
    for (client, server, transport, port), f in flows.items():
        labels = {k: v for k, v in f["labels"].items() if k}
        specific = {k: v for k, v in labels.items() if k not in _GENERIC} or labels
        protocol = max(specific, key=specific.get) if specific else transport.upper()
        out.append({"src": client, "dst": server, "transport": transport, "port": port, "protocol": protocol,
                    "packets": f["packets"], "bytes": f["bytes"], "first": f["first"], "last": f["last"]})
    out.sort(key=lambda x: -x["packets"])
    truncated = len(out) > MAX_FLOWS
    return {
        "packets": packets,
        "non_ip_packets": non_ip,
        "hosts": [{"ip": ip, "mac": mac} for ip, mac in hosts.items()],
        "flows": out[:MAX_FLOWS],
        "truncated": truncated,
    }


_EV_BASE = ["frame.time_epoch", "ip.src", "ip.dst", "ipv6.src", "ipv6.dst", "tcp.srcport", "tcp.dstport"]


async def _events(path: Path) -> tuple[list[dict], bool]:
    """Segunda pasada: solo paquetes de los protocolos soportados, agregados por (flujo, protocolo, resumen)."""
    args = ["tshark", "-r", str(path), "-n", "-Y", proto.DISPLAY_FILTER, "-T", "fields", "-E", "separator=/t", "-E", "occurrence=a",
            "-E", f"aggregator={proto.SEP}"]
    for f in _EV_BASE + proto.FIELDS:
        args += ["-e", f]
    p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    agg: dict[tuple, dict] = {}
    per_flow: dict[tuple, int] = {}
    truncated = False
    nb = len(_EV_BASE)

    async def consume():
        nonlocal truncated
        assert p.stdout is not None
        async for raw in p.stdout:
            cols = raw.decode(errors="replace").rstrip("\n").split("\t")
            cols += [""] * (nb + proto.N - len(cols))
            first = lambda v: v.split(proto.SEP)[0]  # noqa: E731
            ts, ip4s, ip4d, ip6s, ip6d, tsp, tdp = (first(c) for c in cols[:nb])
            src, dst = ip4s or ip6s, ip4d or ip6d
            if not src or not dst or not tsp or not tdp:
                continue
            sp, dp = int(tsp), int(tdp)
            port, dst_is_server = _service_port(sp, dp)
            client, server = (src, dst) if dst_is_server else (dst, src)
            direction = "c2s" if dst_is_server else "s2c"
            ev = proto.event_from_columns(cols[nb:], direction)
            if ev is None:
                continue
            flow = (client, server, "tcp", port)
            key = (flow, ev["protocol"], ev["direction"], ev["kind"], ev["summary"], ev["secret_kind"])
            cur = agg.get(key)
            t = float(ts or 0)
            if cur is None:
                if per_flow.get(flow, 0) >= MAX_EVENTS_PER_FLOW or len(agg) >= MAX_EVENTS:
                    truncated = True
                    continue
                per_flow[flow] = per_flow.get(flow, 0) + 1
                agg[key] = {"src": client, "dst": server, "transport": "tcp", "port": port, **ev, "count": 1, "first": t, "last": t}
            else:
                cur["count"] += 1
                cur["last"] = t

    try:
        await asyncio.wait_for(consume(), timeout=600)
    except asyncio.TimeoutError:
        p.kill()
        raise ToolError("tshark superó el tiempo máximo (600 s) extrayendo protocolos")
    await p.wait()
    return sorted(agg.values(), key=lambda e: (not e["secret"], e["kind"] not in ("control", "write"), -e["count"])), truncated


@mcp.tool()
async def pcap_flows(path: str) -> str:
    """Analiza offline un pcap/pcapng y devuelve JSON con hosts (IP↔MAC por ARP) y flujos agregados (src=cliente, dst=servidor, transporte, puerto de servicio, protocolo, paquetes, bytes) y eventos de protocolo (HTTP, MQTT, Modbus, S7, FTP: peticiones, topics, funciones, comandos y credenciales en claro). Pasivo: no genera tráfico."""
    if shutil.which("tshark") is None:
        raise ToolError("tshark no está instalado")
    p = _resolve(path)
    result = await _analyze(p)
    result["events"], result["events_truncated"] = await _events(p)
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run("stdio")
