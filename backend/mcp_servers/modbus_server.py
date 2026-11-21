"""MCP server (stdio) — Modbus/TCP, SOLO LECTURA.

No implementa ninguna función de escritura (FC 5/6/15/16...). Cliente mínimo con sockets.
"""
import asyncio
import json
import struct
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("modbus")

_FUNCTIONS = {"coils": 1, "discrete_inputs": 2, "holding_registers": 3, "input_registers": 4}
_EXCEPTIONS = {1: "ILLEGAL_FUNCTION", 2: "ILLEGAL_DATA_ADDRESS", 3: "ILLEGAL_DATA_VALUE", 4: "SERVER_DEVICE_FAILURE"}


async def _read_exact(reader: asyncio.StreamReader, n: int) -> bytes:
    return await asyncio.wait_for(reader.readexactly(n), timeout=5)


async def read(host: str, port: int, unit_id: int, kind: str, address: int, count: int) -> dict:
    fc = _FUNCTIONS[kind]
    request = struct.pack(">HHHBBHH", 1, 0, 6, unit_id, fc, address, count)
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=5)
    try:
        writer.write(request)
        await writer.drain()
        header = await _read_exact(reader, 7)
        _tid, proto, length, _unit = struct.unpack(">HHHB", header)
        if proto != 0 or not 2 <= length <= 260:
            raise ToolError("Respuesta no Modbus/TCP")
        pdu = await _read_exact(reader, length - 1)
    finally:
        writer.close()
    rfc = pdu[0]
    if rfc == fc | 0x80:
        code = pdu[1] if len(pdu) > 1 else 0
        return {"ok": False, "exception_code": code, "exception": _EXCEPTIONS.get(code, "UNKNOWN")}
    if rfc != fc:
        raise ToolError(f"Código de función inesperado en la respuesta: {rfc}")
    byte_count, data = pdu[1], pdu[2:]
    if len(data) != byte_count:
        raise ToolError("Respuesta truncada")
    if fc in (1, 2):
        values = [bool(data[i // 8] >> (i % 8) & 1) for i in range(count)]
    else:
        values = list(struct.unpack(f">{byte_count // 2}H", data))
    return {"ok": True, "values": values}


@mcp.tool()
async def modbus_read(
    host: str,
    kind: Literal["coils", "discrete_inputs", "holding_registers", "input_registers"] = "holding_registers",
    address: int = 0,
    count: int = 10,
    port: int = 502,
    unit_id: int = 1,
) -> str:
    """Lee (solo lectura) coils, discrete inputs, holding registers o input registers de un dispositivo Modbus/TCP. Devuelve JSON."""
    if not 1 <= count <= 100:
        raise ToolError("count debe estar entre 1 y 100")
    if not 0 <= address <= 65535 - count + 1:
        raise ToolError("address fuera de rango")
    if not 1 <= port <= 65535 or not 0 <= unit_id <= 255:
        raise ToolError("port/unit_id fuera de rango")
    try:
        result = await read(host, port, unit_id, kind, address, count)
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
        raise ToolError(f"No se pudo leer de {host}:{port}: {type(e).__name__} {e}".strip()) from e
    return json.dumps({"host": host, "port": port, "unit_id": unit_id, "kind": kind, "address": address, **result})


if __name__ == "__main__":
    mcp.run("stdio")
