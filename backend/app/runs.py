"""Ciclo de vida de un ToolRun: validar alcance → ejecutar vía MCP → guardar → parsear."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from . import events, mcp_client
from .db import SessionLocal
from .models import Capture, RunStatus, ToolRun
from .parsers import PARSERS

log = logging.getLogger(__name__)
FINISH_HOOKS: list = []  # corutinas async (run_id) llamadas al terminar un run (p. ej. el agente LLM)
_tasks: set[asyncio.Task] = set()  # referencias fuertes para que no se recolecten


def spawn(run_id: int) -> None:
    task = asyncio.create_task(execute(run_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def execute(run_id: int) -> None:
    with SessionLocal() as db:
        run = db.get(ToolRun, run_id)
        if run is None:
            return
        try:
            arguments = mcp_client.bind_arguments(db, run.campaign_id, run.server, run.tool, run.arguments)  # ruta real de la captura, args permitidos
            output = await mcp_client.call_tool(run.server, run.tool, arguments)
            run.output = output
            db.commit()  # la salida cruda se conserva aunque falle el parser
            parser = PARSERS.get((run.server, run.tool))
            if parser:
                parser(db, run, output)
            run.status = RunStatus.succeeded
        except Exception as e:  # noqa: BLE001 — se guarda el error en el run
            log.exception("ToolRun %s falló", run_id)
            db.rollback()
            run = db.get(ToolRun, run_id)
            if run is None:  # campaña borrada durante la ejecución
                return
            run.status = RunStatus.failed
            run.error = f"{type(e).__name__}: {e}"
            if run.tool == "pcap_flows":  # el análisis de una captura falló
                cap = db.scalar(select(Capture).where(Capture.campaign_id == run.campaign_id, Capture.path == run.arguments.get("path")))
                if cap:
                    cap.status, cap.error = "failed", run.error
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        events.publish(run.campaign_id, {"type": "changed", "run_id": run.id})
    for hook in FINISH_HOOKS:
        try:
            await hook(run_id)
        except Exception:  # noqa: BLE001
            log.exception("Hook de fin de run falló")


def fail_stale_runs() -> None:
    """Al arrancar, los runs que quedaron 'running' (proceso anterior muerto) pasan a failed."""
    with SessionLocal() as db:
        for run in db.scalars(select(ToolRun).where(ToolRun.status == RunStatus.running)):
            run.status = RunStatus.failed
            run.error = "Interrumpido: la aplicación se reinició durante la ejecución"
            run.finished_at = datetime.now(timezone.utc)
        for cap in db.scalars(select(Capture).where(Capture.status == "analyzing")):
            cap.status, cap.error = "failed", "Interrumpido: la aplicación se reinició durante el análisis"
        db.commit()
