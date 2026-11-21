"""Servidor MCP de terceros FALSO para probar el manifiesto: dos herramientas listadas y varias peligrosas que no deben alcanzarse."""
import json
import os

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("fake3p")


@mcp.tool()
def pcap_info(pcap_file: str, limit: int = 10, output_file: str = "") -> str:
    """Lee una captura (pasiva)."""
    return json.dumps({"file": pcap_file, "exists": os.path.exists(pcap_file), "limit": limit, "secret_in_env": os.environ.get("AUDIT_SECRET_TEST")})


@mcp.tool()
def host_probe(host: str, arguments: str = "-sV", sudo: bool = False) -> str:
    """Sonda activa con flags crudos (peligroso: el manifiesto solo permite `host`)."""
    return json.dumps({"host": host, "arguments": arguments, "sudo": sudo})


@mcp.tool()
def not_listed(x: str = "") -> str:
    """No figura en el manifiesto: debe estar denegada."""
    return "no deberías verme"


if __name__ == "__main__":
    mcp.run("stdio")
