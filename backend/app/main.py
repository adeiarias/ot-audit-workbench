from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import models  # noqa: F401  (registra tablas)
from . import migrations
from .db import Base, engine, harden_permissions
from . import runs
from .llm import agent
from .routers import campaigns, captures, chat, evidence, findings, llm as llm_router, report, runs as runs_router, scope as scope_router, summary
from .security import ALLOWED_HOSTS, ALLOWED_ORIGINS, OriginGuardMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI):
    harden_permissions()
    migrations.migrate(engine)  # columnas nuevas en tablas existentes (con copia de seguridad)
    Base.metadata.create_all(engine)  # tablas nuevas
    harden_permissions()  # también las copias y ficheros -wal/-shm que acaban de aparecer
    runs.fail_stale_runs()
    agent.fail_stale_calls()
    if agent.on_run_finished not in runs.FINISH_HOOKS:
        runs.FINISH_HOOKS.append(agent.on_run_finished)
    yield


app = FastAPI(title="Audit Platform", lifespan=lifespan)

# Solo el dev server de Vite en local. El orden importa: el último añadido es el más externo.
app.add_middleware(OriginGuardMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=sorted(ALLOWED_ORIGINS), allow_methods=["*"], allow_headers=["*"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

app.include_router(campaigns.router)
app.include_router(runs_router.router)
app.include_router(captures.router)
app.include_router(findings.router)
app.include_router(evidence.router)
app.include_router(chat.router)
app.include_router(report.router)
app.include_router(llm_router.router)
app.include_router(scope_router.router)
app.include_router(summary.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
