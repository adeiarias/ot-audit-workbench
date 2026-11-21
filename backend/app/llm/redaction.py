"""Capa de anonimización: lo que sale hacia el LLM va seudonimizado; lo que vuelve se restaura.

- Reversible (mapa persistente por campaña): IPv4/IPv6, CIDR, MAC, hostnames conocidos y dominios internos.
- Irreversible: secretos (claves privadas, tokens, contraseñas, community strings…) → [REDACTED].
El modelo trabaja con seudónimos (IP-0001…); los argumentos de sus herramientas se restauran ANTES de
validar alcance y ejecutar, así que la comprobación siempre se hace con valores reales.
"""
import ipaddress
import re
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Asset, Campaign, RedactionMap
from ..scope import _as_network  # noqa: PLC2701

_SECRETS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"(?i)\b(authorization\s*:\s*(?:bearer|basic)\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)\b((?:password|passwd|pwd|passphrase|secret|token|api[_-]?key|community)\s*[:=]\s*)(?!\[REDACTED)(\"[^\"]*\"|'[^']*'|\S+)"), r"\1[REDACTED]"),
]
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?!\d)")
# Candidatos IPv6 (incluye forma comprimida ::); cada uno se valida con ipaddress, así "12:30:45" o una MAC no se tocan.
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?:/\d{1,3})?(?![\w:])")
_MAC = re.compile(r"(?<![0-9A-Fa-f:-])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:-])")
_INTERNAL_HOST = re.compile(r"(?<![\w.-])[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9-]+)*\.(?:local|lan|corp|internal|intra|home|localdomain)(?![\w-])", re.I)
_TOKEN = re.compile(r"\b(IP|NET|HOST|MAC)-(\d{4})\b")


def map_strings(obj: Any, fn: Callable[[str], str]) -> Any:
    """Aplica fn a todas las cadenas de una estructura JSON (claves intactas)."""
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [map_strings(x, fn) for x in obj]
    if isinstance(obj, dict):
        return {k: map_strings(v, fn) for k, v in obj.items()}
    return obj


class Redactor:
    def __init__(self, db: Session, campaign_id: int, enabled: bool = True):
        self.db, self.campaign_id, self.enabled = db, campaign_id, enabled
        self._fwd: dict[str, str] = {}  # clave normalizada → token
        self._rev: dict[str, str] = {}  # token → valor real
        self._count: dict[str, int] = {}
        for m in db.scalars(select(RedactionMap).where(RedactionMap.campaign_id == campaign_id)):
            self._fwd[self._key(m.kind, m.real)] = m.token
            self._rev[m.token] = m.real
            self._count[m.kind] = max(self._count.get(m.kind, 0), int(m.token.split("-")[1]))
        self._hosts = self._known_hosts()

    @staticmethod
    def _key(kind: str, real: str) -> str:
        return f"{kind}:{real.lower() if kind in ('HOST', 'MAC') else real}"

    def _known_hosts(self) -> re.Pattern | None:
        names = {a.hostname for a in self.db.scalars(select(Asset).where(Asset.campaign_id == self.campaign_id)) if a.hostname}
        campaign = self.db.get(Campaign, self.campaign_id)
        for line in (campaign.scope if campaign else "").splitlines():
            line = line.split("#", 1)[0].strip()
            if line and _as_network(line) is None:
                names.add(line)
        if not names:
            return None
        alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        return re.compile(rf"(?<![\w.-])(?:{alt})(?![\w-])", re.I)

    def _token(self, kind: str, real: str) -> str:
        key = self._key(kind, real)
        if key in self._fwd:
            return self._fwd[key]
        self._count[kind] = self._count.get(kind, 0) + 1
        token = f"{kind}-{self._count[kind]:04d}"
        self._fwd[key], self._rev[token] = token, real
        self.db.add(RedactionMap(campaign_id=self.campaign_id, kind=kind, real=real, token=token))
        self.db.flush()
        return token

    # -- salida hacia el LLM --
    def redact(self, text: str) -> str:
        if not self.enabled or not text:
            return text
        for pattern, repl in _SECRETS:
            text = pattern.sub(repl, text)

        def ip(m: re.Match) -> str:
            raw = m.group(0)
            try:
                if "/" in raw:
                    ipaddress.ip_network(raw, strict=False)
                    return self._token("NET", raw)
                ipaddress.ip_address(raw)
                return self._token("IP", raw)
            except ValueError:
                return raw  # p. ej. 999.1.1.1 o un número de versión

        text = _IPV4.sub(ip, text)
        text = _IPV6.sub(ip, text)
        text = _MAC.sub(lambda m: self._token("MAC", m.group(0)), text)
        if self._hosts:
            text = self._hosts.sub(lambda m: self._token("HOST", m.group(0)), text)
        return _INTERNAL_HOST.sub(lambda m: self._token("HOST", m.group(0)), text)

    # -- entrada desde el LLM --
    def restore(self, text: str) -> str:
        if not text:
            return text
        return _TOKEN.sub(lambda m: self._rev.get(m.group(0), m.group(0)), text)

    def redact_obj(self, obj: Any) -> Any:
        return map_strings(obj, self.redact)

    def restore_obj(self, obj: Any) -> Any:
        return map_strings(obj, self.restore)
