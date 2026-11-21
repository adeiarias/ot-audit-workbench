"""DOCX → PDF vía LibreOffice headless."""
import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "lo_convert.py"
_SYSTEM_PY = "/usr/bin/python3"  # el único con el módulo `uno` (el del venv no lo ve)
_available: bool | None = None
_lock = asyncio.Lock()  # un solo LibreOffice a la vez


class PdfError(Exception):
    pass


def available() -> bool:
    global _available
    if _available is None:
        ok = shutil.which("soffice") is not None and Path(_SYSTEM_PY).exists()
        if ok:
            ok = subprocess.run([_SYSTEM_PY, "-c", "import uno"], capture_output=True).returncode == 0
        _available = ok
    return _available


async def docx_to_pdf(docx: Path, pdf: Path, timeout: int = 240) -> None:
    if not available():
        raise PdfError("LibreOffice (soffice) con soporte UNO no está disponible en este equipo")
    async with _lock:
        profile = Path(tempfile.mkdtemp(prefix="audit-lo-"))
        try:
            proc = await asyncio.create_subprocess_exec(
                _SYSTEM_PY, str(SCRIPT), str(docx), str(pdf), str(profile),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                raise PdfError(f"La conversión a PDF superó {timeout} s") from None
            if proc.returncode != 0 or not pdf.exists():
                raise PdfError(f"Falló la conversión a PDF: {err.decode(errors='replace')[-400:]}")
        finally:
            shutil.rmtree(profile, ignore_errors=True)
