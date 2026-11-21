"""DOCX → PDF con LibreOffice (UNO). Se ejecuta con el python3 del SISTEMA (el que tiene el módulo `uno`).

Uso: lo_convert.py <entrada.docx> <salida.pdf> <perfil_libreoffice_dir>
Actualiza el índice (TOC) y los campos antes de exportar, para que el PDF lleve índice con números de página.
Comunicación con LibreOffice por pipe local (sin puertos de red).
"""
import os
import subprocess
import sys
import time

import uno
from com.sun.star.beans import PropertyValue


def pv(name, value):
    p = PropertyValue()
    p.Name, p.Value = name, value
    return p


def main(src: str, dst: str, profile: str) -> None:
    pipe = f"audit{os.getpid()}"
    proc = subprocess.Popen(
        ["soffice", f"-env:UserInstallation=file://{profile}", "--headless", "--norestore", "--nologo", "--nodefault", "--nolockcheck",
         f"--accept=pipe,name={pipe};urp;"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
        ctx = None
        for _ in range(240):  # hasta ~2 min (primer arranque con perfil nuevo)
            try:
                ctx = resolver.resolve(f"uno:pipe,name={pipe};urp;StarOffice.ComponentContext")
                break
            except Exception:  # noqa: BLE001
                if proc.poll() is not None:
                    raise RuntimeError("LibreOffice terminó antes de aceptar conexiones")
                time.sleep(0.5)
        if ctx is None:
            raise RuntimeError("No se pudo conectar con LibreOffice")
        desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        doc = desktop.loadComponentFromURL(uno.systemPathToFileUrl(os.path.abspath(src)), "_blank", 0, (pv("Hidden", True),))
        if doc is None:
            raise RuntimeError("LibreOffice no pudo abrir el documento")
        try:
            for _ in range(2):  # dos pasadas: el índice puede desplazar la paginación
                idx = doc.getDocumentIndexes()
                for i in range(idx.getCount()):
                    idx.getByIndex(i).update()
                doc.refresh()
            doc.storeToURL(uno.systemPathToFileUrl(os.path.abspath(dst)), (pv("FilterName", "writer_pdf_Export"),))
        finally:
            doc.close(True)
        try:
            desktop.terminate()
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("uso: lo_convert.py <in.docx> <out.pdf> <perfil_dir>")
    main(*sys.argv[1:])
