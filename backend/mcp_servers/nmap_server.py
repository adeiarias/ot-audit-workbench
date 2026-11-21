"""MCP server (stdio) — nmap con perfiles conservadores.

Independiente de la app: solo usa la stdlib y el SDK `mcp`. No acepta argumentos libres:
el llamante elige un perfil y, opcionalmente, puertos. Salida: XML de nmap.
"""
import asyncio
import ipaddress
import re
import shutil
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("nmap")

_HOSTNAME = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?$")
_PORTS = re.compile(r"^[0-9]{1,5}([,-][0-9]{1,5}){0,30}$")

# Conservador por defecto: TCP connect (sin root), tasa limitada (dispositivos OT frágiles).
_BASE = ["-oX", "-", "-n", "-T3", "--max-rate", "100", "--host-timeout", "5m"]
_PROFILES = {
    "ping": ["-sn"],
    "top100": ["-sT", "--top-ports", "100"],
    "services": ["-sT", "-sV", "--top-ports", "100"],
}


def _valid_target(target: str) -> bool:
    if target.startswith("-"):
        return False
    try:
        ipaddress.ip_network(target, strict=False)
        return True
    except ValueError:
        return bool(_HOSTNAME.match(target))


@mcp.tool()
async def nmap_scan(
    target: str,
    profile: Literal["ping", "top100", "services"] = "top100",
    ports: str = "",
) -> str:
    """Escanea un host o CIDR con nmap y devuelve el XML. Perfiles: ping (descubrimiento), top100 (100 puertos TCP), services (top100 + detección de versión). `ports` opcional, p. ej. "22,80,502" o "1-1024"."""
    if shutil.which("nmap") is None:
        raise ToolError("nmap no está instalado")
    if not _valid_target(target):
        raise ToolError(f"Objetivo no válido: {target!r}")
    args = [*_BASE, *_PROFILES[profile]]
    if ports:
        if profile == "ping":
            raise ToolError("`ports` no aplica al perfil ping")
        if not _PORTS.match(ports):
            raise ToolError(f"Puertos no válidos: {ports!r}")
        # -p sustituye a --top-ports
        i = args.index("--top-ports")
        del args[i : i + 2]
        args += ["-p", ports]
    proc = await asyncio.create_subprocess_exec(
        "nmap", *args, "--", target,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=900)
    except asyncio.TimeoutError:
        proc.kill()
        raise ToolError("nmap superó el tiempo máximo (900 s)")
    if proc.returncode != 0:
        raise ToolError(f"nmap terminó con código {proc.returncode}: {err.decode(errors='replace')[:500]}")
    return out.decode(errors="replace")


if __name__ == "__main__":
    mcp.run("stdio")
