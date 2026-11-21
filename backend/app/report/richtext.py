"""Texto de los hallazgos/secciones: Markdown mínimo → bloques.

Soporta: párrafos, listas con -, •, * (y sub-listas con `o` indentado), bloques ``` de código,
marcadores de evidencia `[Evidencia N: descripción]` en línea propia, y en línea **negrita** y `código`.
"""
import re
from dataclasses import dataclass, field

EVIDENCE_RE = re.compile(r"^\[Evidenc(?:ia|e)\s+(\d+)\s*(?::\s*(.*?))?\s*\]$", re.I)
_BULLET = re.compile(r"^(\s*)([-•*]|o)\s+(.*)$")
INLINE_RE = re.compile(r"(\*\*[^*\n]+\*\*|`[^`\n]+`)")
ANY_MARKER_RE = re.compile(r"\[Evidenc(?:ia|e)\s+(\d+)\s*(?::[^\]]*)?\]", re.I)


@dataclass
class Block:
    kind: str  # p | ul | code | evidence
    text: str = ""
    items: list[tuple[int, str]] = field(default_factory=list)  # (nivel, texto) para ul
    number: int = 0  # evidence


def parse_blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    para: list[str] = []
    items: list[tuple[int, str]] = []
    code: list[str] | None = None

    def flush():
        nonlocal para, items
        if para:
            blocks.append(Block("p", "\n".join(para)))
            para = []
        if items:
            blocks.append(Block("ul", items=items))
            items = []

    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if line.strip().startswith("```"):
            if code is None:
                flush()
                code = []
            else:
                blocks.append(Block("code", "\n".join(code)))
                code = None
            continue
        if code is not None:
            code.append(raw.rstrip("\n"))
            continue
        if not line.strip():
            flush()
            continue
        ev = EVIDENCE_RE.match(line.strip())
        if ev:
            flush()
            blocks.append(Block("evidence", text=ev.group(2) or "", number=int(ev.group(1))))
            continue
        b = _BULLET.match(line)
        # 'o' solo cuenta como viñeta si está indentado (sub-lista); '- ' / '• ' / '* ' siempre
        if b and (b.group(2) != "o" or len(b.group(1)) >= 2):
            if para:
                blocks.append(Block("p", "\n".join(para)))
                para = []
            items.append((1 if len(b.group(1)) >= 2 else 0, b.group(3).strip()))
            continue
        if items:
            blocks.append(Block("ul", items=items))
            items = []
        para.append(line.strip())
    if code is not None:  # fence sin cerrar: se conserva lo escrito
        blocks.append(Block("code", "\n".join(code)))
    flush()
    return blocks


def split_inline(text: str) -> list[tuple[str, str]]:
    """[(estilo, texto)] con estilo ∈ {'', 'b', 'code'}."""
    out: list[tuple[str, str]] = []
    for part in INLINE_RE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append(("b", part[2:-2]))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            out.append(("code", part[1:-1]))
        else:
            out.append(("", part))
    return out


def marker_numbers(text: str) -> set[int]:
    return {int(m.group(1)) for m in ANY_MARKER_RE.finditer(text or "")}
