import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from urllib.parse import urlparse

from ..db import get_db
from ..llm import client
from ..models import Campaign, LLMProfile

router = APIRouter(prefix="/api/llm", tags=["llm"])

Provider = Literal["anthropic", "deepseek", "litellm", "openai"]

PRESETS = {
    "anthropic": {"label": "Anthropic (Claude)", "base_url": "", "model": "claude-opus-5-5", "needs_key": True, "hint": "Clave de console.anthropic.com. Sin URL: usa la API oficial."},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com", "model": "deepseek-flash", "needs_key": True, "hint": "Servicio remoto: según su política publicada procesa datos en servidores en China."},
    "litellm": {"label": "LiteLLM (proxy)", "base_url": "http://localhost:4000", "model": "", "needs_key": False, "hint": "El modelo es el model_name de tu config.yaml. Puede apuntar a un modelo local: nada sale de tu red."},
    "openai": {"label": "Compatible con OpenAI (Ollama, vLLM…)", "base_url": "", "model": "", "needs_key": False, "hint": "Cualquier /chat/completions. P. ej. Ollama: http://localhost:11434/v1"},
}


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: Provider
    model: str = Field(default="", max_length=200)
    base_url: str = Field(default="", max_length=300)
    api_key: str | None = Field(default=None, max_length=500)
    effort: str = Field(default="high", max_length=20)
    max_tokens: int = Field(default=8192, ge=256, le=200_000)
    tools: bool = True
    pass_reasoning: bool | None = None
    extra_body: dict = Field(default_factory=dict)
    is_default: bool = False

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if v and (urlparse(v).scheme not in ("http", "https") or not urlparse(v).netloc):
            raise ValueError("La URL debe empezar por http:// o https://")
        return v


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider: Provider | None = None
    model: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=300)
    api_key: str | None = Field(default=None, max_length=500)  # None = conservar la actual
    clear_api_key: bool = False
    effort: str | None = Field(default=None, max_length=20)
    max_tokens: int | None = Field(default=None, ge=256, le=200_000)
    tools: bool | None = None
    pass_reasoning: bool | None = None
    extra_body: dict | None = None
    is_default: bool | None = None

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return ProfileIn._url(v) if v is not None else v


class TestIn(BaseModel):
    profile_id: int | None = None  # None = configuración por entorno


def _hint(key: str) -> str:
    return "" if not key else ("••••" if len(key) < 12 else f"…{key[-4:]}")


def _out(db: Session, p: LLMProfile) -> dict:
    s = client.from_profile(p)
    used = db.scalar(select(func.count()).select_from(Campaign).where(Campaign.llm_profile_id == p.id)) or 0
    return {
        "id": p.id, "name": p.name, "provider": p.provider, "model": p.model, "base_url": p.base_url, "has_key": bool(p.api_key), "key_hint": _hint(p.api_key),
        "effort": p.effort, "max_tokens": p.max_tokens, "tools": p.tools, "pass_reasoning": p.pass_reasoning, "extra_body": p.extra_body, "is_default": p.is_default,
        "label": s.label, "external": s.external, "problem": client.problem(s), "campaigns_using": used,
    }


def _profile(db: Session, profile_id: int) -> LLMProfile:
    p = db.get(LLMProfile, profile_id)
    if p is None:
        raise HTTPException(404, "Perfil no encontrado")
    return p


def _unique_name(db: Session, name: str, own_id: int | None = None) -> None:
    clash = db.scalar(select(LLMProfile).where(LLMProfile.name == name))
    if clash is not None and clash.id != own_id:
        raise HTTPException(409, f"Ya existe un perfil llamado {name!r}")


@router.get("/presets")
def presets():
    return PRESETS


@router.get("/profiles")
def list_profiles(db: Session = Depends(get_db)):
    env = client.env_settings()
    has_default = db.scalar(select(LLMProfile.id).where(LLMProfile.is_default.is_(True)).limit(1)) is not None
    return {
        "profiles": [_out(db, p) for p in db.scalars(select(LLMProfile).order_by(LLMProfile.id))],
        "env": {"provider": env.provider, "model": env.model, "label": env.label, "external": env.external, "problem": client.problem(env), "has_key": bool(env.api_key),
                "in_use_by_default": not has_default},
    }


@router.post("/profiles", status_code=201)
def create_profile(payload: ProfileIn, db: Session = Depends(get_db)):
    _unique_name(db, payload.name)
    data = payload.model_dump()
    data["api_key"] = (data["api_key"] or "").strip()
    if data["is_default"]:
        db.execute(update(LLMProfile).values(is_default=False))
    p = LLMProfile(**data)
    db.add(p)
    db.commit()
    return _out(db, p)


@router.patch("/profiles/{profile_id}")
def update_profile(profile_id: int, payload: ProfileUpdate, db: Session = Depends(get_db)):
    p = _profile(db, profile_id)
    changes = payload.model_dump(exclude_unset=True)
    clear = changes.pop("clear_api_key", False)
    key = changes.pop("api_key", None)
    if "name" in changes:
        _unique_name(db, changes["name"], p.id)
    nullable = {"pass_reasoning"}
    for k, v in changes.items():
        if v is None and k not in nullable:
            continue
        if k == "is_default" and v:
            db.execute(update(LLMProfile).where(LLMProfile.id != p.id).values(is_default=False))
        setattr(p, k, v)
    if clear:
        p.api_key = ""
    elif key is not None and key.strip():
        p.api_key = key.strip()
    db.commit()
    return _out(db, p)


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    db.delete(_profile(db, profile_id))  # las campañas que lo usaban pasan a NULL (ON DELETE SET NULL)
    db.commit()
    return Response(status_code=204)


@router.post("/test")
async def test_connection(payload: TestIn, db: Session = Depends(get_db)):
    """Prueba de conexión: un mensaje mínimo SIN datos de ninguna campaña. Gasta unos pocos tokens."""
    s = client.from_profile(_profile(db, payload.profile_id)) if payload.profile_id else client.env_settings()
    if (reason := client.problem(s)) is not None:
        return {"ok": False, "error": reason, "label": s.label, "model": s.model}
    t0 = time.monotonic()
    try:
        r = await client.create_message("Eres un comprobador de conexión. Responde solo con la palabra OK.", [{"role": "user", "content": [{"type": "text", "text": "ping"}]}], [], settings=s)
        reply = " ".join(b.get("text", "") for b in r.content if b.get("type") == "text").strip()
        return {"ok": True, "ms": int((time.monotonic() - t0) * 1000), "reply": reply[:80], "label": s.label, "model": s.model, "stop_reason": r.stop_reason}
    except Exception as e:  # noqa: BLE001 — se informa al usuario, nunca 500
        msg = f"{type(e).__name__}: {e}"
        if s.api_key:
            msg = msg.replace(s.api_key, "***")
        return {"ok": False, "error": msg[:400], "ms": int((time.monotonic() - t0) * 1000), "label": s.label, "model": s.model}
