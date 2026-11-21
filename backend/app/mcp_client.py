"""Orquestador MCP.

- Los servidores se lanzan como subproceso stdio (uno por llamada: simple y aislado).
- Solo se pueden invocar herramientas registradas en TOOL_POLICY (allowlist). Los servidores propios están en código; los de
  terceros se declaran en `mcp_servers.yaml` (o `AUDIT_MCP_MANIFEST`) y son **deny-by-default**: cada herramienta debe listarse,
  con `allowed_args` explícito, y declarar su objetivo de red (`target_arg`, se valida contra el alcance) o su captura
  (`capture_arg`: el modelo/UI solo da `capture_id` y la ruta real la resuelve este módulo, confinada a la campaña).
- Un servidor externo se lanza con un entorno mínimo: nunca hereda las claves de la app (solo lo que declare `env`).
"""
import asyncio
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .db import CAPTURES_ROOT

log = logging.getLogger(__name__)

SERVERS_DIR = Path(__file__).resolve().parents[1] / "mcp_servers"
CALL_TIMEOUT = 1000  # s; algo mayor que el timeout interno de nmap
MAX_OUTPUT = 2_000_000  # caracteres; la salida de un servidor externo no se guarda sin límite
DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "mcp_servers.yaml"


class McpToolError(Exception):
    pass



@dataclass(frozen=True)
class ToolPolicy:
    target_arg: str | None  # argumento que contiene el objetivo de red (se valida contra el alcance)
    active: bool  # genera tráfico hacia el objetivo (en Fase 4 exigirá aprobación humana)
    internal: bool = False  # solo la propia app puede lanzarla (p. ej. análisis de pcaps subidos)
    capture_arg: str | None = None  # argumento del servidor con la ruta de la captura; la app expone `capture_id` en su lugar
    allowed_args: frozenset[str] | None = None  # si se declara, cualquier otro argumento se rechaza
    llm: bool = True  # el asistente puede usarla (False: solo el auditor desde la UI)
    external: bool = False  # servidor de terceros (manifiesto)


@dataclass(frozen=True)
class ServerSpec:
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    external: bool = False


def _builtin(script: str, env: dict[str, str] | None = None) -> ServerSpec:
    return ServerSpec(sys.executable, (str(SERVERS_DIR / script),), env or {})


SERVERS: dict[str, ServerSpec] = {
    "nmap": _builtin("nmap_server.py"),
    "modbus": _builtin("modbus_server.py"),
    "tshark": _builtin("tshark_server.py", {"AUDIT_CAPTURES_ROOT": str(CAPTURES_ROOT)}),
}

TOOL_POLICY: dict[tuple[str, str], ToolPolicy] = {
    ("nmap", "nmap_scan"): ToolPolicy(target_arg="target", active=True),
    ("modbus", "modbus_read"): ToolPolicy(target_arg="host", active=True),
    ("tshark", "pcap_flows"): ToolPolicy(target_arg=None, active=False, internal=True),
}


_BUILTIN_SERVERS, _BUILTIN_POLICY = dict(SERVERS), dict(TOOL_POLICY)


class ManifestError(ValueError):
    pass


def load_manifest(path: Path | str | None = None) -> list[str]:
    """(Re)carga los servidores de terceros del manifiesto YAML. Devuelve sus nombres. Un manifiesto inválido NO se aplica a medias."""
    import yaml

    path = Path(path or os.environ.get("AUDIT_MCP_MANIFEST") or DEFAULT_MANIFEST)
    servers, policy = dict(_BUILTIN_SERVERS), dict(_BUILTIN_POLICY)
    if path.exists():
        data = yaml.safe_load(path.read_text()) or {}
        for name, cfg in (data.get("servers") or {}).items():
            if name in _BUILTIN_SERVERS:
                raise ManifestError(f"{name}: el nombre choca con un servidor propio")
            command = cfg.get("command")
            if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
                raise ManifestError(f"{name}: `command` debe ser una lista (ejecutable y argumentos; sin shell)")
            env = {str(k): str(v) for k, v in (cfg.get("env") or {}).items()}
            servers[name] = ServerSpec(command[0], tuple(command[1:]), env, external=True)
            for tool, t in (cfg.get("tools") or {}).items():
                t = t or {}
                if "active" not in t:
                    raise ManifestError(f"{name}/{tool}: declara `active: true|false` (es obligatorio)")
                if t.get("allowed_args") is None:
                    raise ManifestError(f"{name}/{tool}: declara `allowed_args` (lista; vacía si no admite argumentos)")
                target, capture = t.get("target_arg"), t.get("capture_arg")
                if not target and not capture:
                    raise ManifestError(f"{name}/{tool}: debe declarar `target_arg` (objetivo de red) o `capture_arg` (captura)")
                if target and capture:
                    raise ManifestError(f"{name}/{tool}: `target_arg` y `capture_arg` son excluyentes")
                if capture and t["active"]:
                    raise ManifestError(f"{name}/{tool}: una herramienta que solo lee una captura no puede ser activa")
                allowed = frozenset(t["allowed_args"])
                if (target or capture) not in allowed:
                    raise ManifestError(f"{name}/{tool}: `allowed_args` debe incluir {target or capture!r}")
                policy[(name, tool)] = ToolPolicy(
                    target_arg=target, active=bool(t["active"]), capture_arg=capture, allowed_args=allowed,
                    llm=bool(t.get("llm", True)), external=True,
                )
    SERVERS.clear(), TOOL_POLICY.clear()
    SERVERS.update(servers), TOOL_POLICY.update(policy)
    return [n for n, sp in servers.items() if sp.external]


def _params(server: str) -> StdioServerParameters:
    spec = SERVERS[server]
    # env mínimo: la librería lo fusiona con unas pocas variables seguras (PATH, HOME…), nunca con el entorno de la app
    return StdioServerParameters(command=spec.command, args=list(spec.args), env=spec.env or {})


def _available(server: str) -> bool:
    cmd = SERVERS[server].command
    return Path(cmd).exists() if os.sep in cmd else shutil.which(cmd) is not None


def _public_schema(policy: ToolPolicy, schema: dict) -> dict:
    """Esquema que ven la UI y el modelo: solo los argumentos permitidos y `capture_id` en lugar de la ruta."""
    schema = dict(schema or {})
    props = dict(schema.get("properties") or {})
    required = list(schema.get("required") or [])
    if policy.allowed_args is not None:
        props = {k: v for k, v in props.items() if k in policy.allowed_args}
        required = [r for r in required if r in props]
    if policy.capture_arg:
        props.pop(policy.capture_arg, None)
        required = [r for r in required if r != policy.capture_arg]
        props = {"capture_id": {"type": "integer", "description": "ID de una captura subida a la campaña (pestaña Capturas)"}, **props}
        required = ["capture_id", *required]
    schema["properties"], schema["required"] = props, required
    schema["additionalProperties"] = False
    return schema


def bind_arguments(db, campaign_id: int, server: str, tool: str, arguments: dict) -> dict:
    """Valida los argumentos contra la política y devuelve los que se enviarán al servidor (con la ruta real de la captura)."""
    from .models import Capture

    policy = TOOL_POLICY.get((server, tool))
    if policy is None:
        raise McpToolError(f"Herramienta no permitida: {server}/{tool}")
    allowed = policy.allowed_args
    if allowed is not None:
        extra = sorted(set(arguments) - ({"capture_id"} if policy.capture_arg else set()) - allowed)
        if extra:
            raise McpToolError(f"Argumentos no permitidos para {tool}: {', '.join(extra)}")
    if not policy.capture_arg:
        return dict(arguments)
    if policy.capture_arg in arguments:
        raise McpToolError(f"No se admite la ruta ({policy.capture_arg}): indica `capture_id`")
    cid = arguments.get("capture_id")
    if isinstance(cid, bool) or not isinstance(cid, int):
        raise McpToolError("`capture_id` debe ser el ID (entero) de una captura de la campaña")
    cap = db.get(Capture, cid)
    if cap is None or cap.campaign_id != campaign_id:
        raise McpToolError(f"La captura {cid} no existe en esta campaña")
    path = Path(cap.path).resolve()
    if not path.is_relative_to((CAPTURES_ROOT / str(campaign_id)).resolve()) or not path.is_file():
        raise McpToolError(f"El fichero de la captura {cid} no está disponible")
    out = {k: v for k, v in arguments.items() if k != "capture_id"}
    out[policy.capture_arg] = str(path)
    return out


async def list_tools() -> list[dict]:
    """Herramientas expuestas por los servidores que además están en la allowlist."""
    out = []
    for server, spec in list(SERVERS.items()):
        if not _available(server):
            log.warning("Servidor MCP %r no disponible (%s): se omite", server, spec.command)
            continue
        try:
            async with stdio_client(_params(server)) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
        except Exception:  # noqa: BLE001 — un servidor de terceros roto no debe dejar sin herramientas a los demás
            if not spec.external:
                raise
            log.exception("Servidor MCP externo %r falló al listar herramientas: se omite", server)
            continue
        for tool in tools:
            policy = TOOL_POLICY.get((server, tool.name))
            if policy:
                out.append({
                    "server": server,
                    "tool": tool.name,
                    "description": tool.description or "",
                    "input_schema": _public_schema(policy, tool.input_schema),
                    "target_arg": policy.target_arg,
                    "capture_arg": policy.capture_arg,
                    "active": policy.active,
                    "internal": policy.internal,
                    "llm": policy.llm,
                    "external": policy.external,
                })
    return out


async def call_tool(server: str, tool: str, arguments: dict) -> str:
    if (server, tool) not in TOOL_POLICY:
        raise McpToolError(f"Herramienta no permitida: {server}/{tool}")

    async def _run() -> tuple[str, bool]:
        async with stdio_client(_params(server)) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
                text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
                return text, bool(result.is_error)

    try:
        text, is_error = await asyncio.wait_for(_run(), timeout=CALL_TIMEOUT)
    except asyncio.TimeoutError:
        raise McpToolError(f"Tiempo máximo superado ({CALL_TIMEOUT} s)") from None
    # Se lanza FUERA de los contextos anyio: dentro quedaría envuelto en un ExceptionGroup.
    if is_error:
        raise McpToolError(text or "error sin detalle")
    if SERVERS[server].external and len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + f"\n[… salida truncada a {MAX_OUTPUT} caracteres]"
    return text


load_manifest()
