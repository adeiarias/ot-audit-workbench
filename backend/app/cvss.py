"""Puntuación base de CVSS 3.0 / 3.1 a partir del vector (fórmulas de FIRST). CVSS 4.0 NO se calcula (puntuación manual)."""
import math

_AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}
_AC = {"L": 0.77, "H": 0.44}
_PR = {"U": {"N": 0.85, "L": 0.62, "H": 0.27}, "C": {"N": 0.85, "L": 0.68, "H": 0.5}}
_UI = {"N": 0.85, "R": 0.62}
_CIA = {"H": 0.56, "L": 0.22, "N": 0.0}
_REQUIRED = ("AV", "AC", "PR", "UI", "S", "C", "I", "A")


def _roundup(x: float, version: str) -> float:
    if version == "3.0":
        return math.ceil(x * 10) / 10
    i = round(x * 100000)  # 3.1: evita errores de coma flotante
    return i / 100000 if i % 10000 == 0 else (math.floor(i / 10000) + 1) / 10


def base_score(vector: str) -> float | None:
    """Puntuación base 0–10, o None si el vector no es 3.0/3.1 o no trae las 8 métricas base válidas (se mantiene la manual)."""
    parts = vector.strip().split("/")
    if not parts or parts[0] not in ("CVSS:3.0", "CVSS:3.1"):
        return None
    version = parts[0][5:]
    m: dict[str, str] = {}
    for p in parts[1:]:
        k, _, v = p.partition(":")
        if k in m:
            return None  # métrica repetida
        m[k] = v
    if any(k not in m for k in _REQUIRED):
        return None
    try:
        scope_changed = {"U": False, "C": True}[m["S"]]
        iss = 1 - (1 - _CIA[m["C"]]) * (1 - _CIA[m["I"]]) * (1 - _CIA[m["A"]])
        impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if scope_changed else 6.42 * iss
        exploitability = 8.22 * _AV[m["AV"]] * _AC[m["AC"]] * _PR[m["S"]][m["PR"]] * _UI[m["UI"]]
    except KeyError:
        return None
    if impact <= 0:
        return 0.0
    total = 1.08 * (impact + exploitability) if scope_changed else impact + exploitability
    return _roundup(min(total, 10), version)
