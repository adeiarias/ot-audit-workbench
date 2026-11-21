"""Control de alcance: un objetivo solo se acepta si está dentro del alcance de la campaña.

Formato del alcance (uno por línea, `#` comenta): IP, CIDR u hostname exacto.
Los hostnames NO se resuelven por DNS: solo coinciden de forma exacta.
"""
import ipaddress
import re
from dataclasses import dataclass

_HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$")


def _is_hostname(value: str) -> bool:
    """Hostname sintácticamente válido. La última etiqueta no puede ser solo dígitos (RFC 3696): así `10.0.0.256` es un error y no un 'hostname'."""
    return bool(_HOSTNAME.match(value)) and not value.rsplit(".", 1)[-1].isdigit()


def _lines(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def _as_network(value: str):
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError:
        return None


@dataclass(frozen=True)
class ScopeRule:
    line: int
    kind: str  # ip | cidr | hostname
    value: str
    warning: str = ""


@dataclass(frozen=True)
class ScopeIssue:
    line: int
    text: str
    error: str


def _broad_warning(net) -> str:
    too_broad = (net.version == 4 and net.prefixlen < 16) or (net.version == 6 and net.prefixlen < 48)
    if not too_broad:
        return ""
    n = net.num_addresses
    return f"Rango muy amplio ({'más de mil millones de' if n > 10**9 else f'{n:,}'} direcciones): comprueba que es lo autorizado"


def parse_scope(text: str) -> tuple[list[ScopeRule], list[ScopeIssue]]:
    """Analiza el alcance con números de línea (1-based, contando las líneas vacías y los comentarios)."""
    rules: list[ScopeRule] = []
    issues: list[ScopeIssue] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        net = _as_network(line)
        if net is not None:
            rules.append(ScopeRule(n, "cidr" if "/" in line else "ip", line, _broad_warning(net)))
        elif _is_hostname(line):
            rules.append(ScopeRule(n, "hostname", line))
        else:
            issues.append(ScopeIssue(n, line, "No es una IP, un CIDR ni un hostname válido"))
    return rules, issues


def validate_scope(text: str) -> None:
    """Lanza ValueError (con números de línea) si alguna línea no es IP, CIDR ni hostname válido."""
    _, issues = parse_scope(text)
    if issues:
        more = f" (+{len(issues) - 3} más)" if len(issues) > 3 else ""
        raise ValueError("; ".join(f"línea {i.line}: {i.error} ({i.text!r})" for i in issues[:3]) + more)


def diff_scope(old: str, new: str) -> tuple[list[str], list[str]]:
    """(añadidas, quitadas) entradas entre dos alcances."""
    a = {r.value for r in parse_scope(old)[0]}
    b = {r.value for r in parse_scope(new)[0]}
    return sorted(b - a), sorted(a - b)


def target_in_scope(target: str, scope_text: str) -> bool:
    target = target.strip()
    if not target or target.startswith("-"):
        return False
    entries = _lines(scope_text)
    net = _as_network(target)
    if net is not None:
        for entry in entries:
            allowed = _as_network(entry)
            if allowed is not None and allowed.version == net.version and net.subnet_of(allowed):
                return True
        return False
    if not _is_hostname(target):
        return False
    return any(_as_network(e) is None and e.lower() == target.lower() for e in entries)


def is_special_address(value: str) -> bool:
    """Multicast, broadcast limitado o no especificada: no son activos, solo destinos de tráfico."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_multicast or ip.is_unspecified or str(ip) == "255.255.255.255"
