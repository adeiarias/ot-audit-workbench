"""Punto único de acceso al LLM. Proveedores:

- anthropic (por defecto): API de Claude.
- deepseek | litellm | openai: cualquier API compatible con /chat/completions de OpenAI
  (DeepSeek, un proxy LiteLLM —que a su vez puede apuntar a modelos locales—, Ollama, vLLM, OpenAI…).

Configuración por entorno (se lee en cada llamada):
  AUDIT_LLM_PROVIDER   anthropic | deepseek | litellm | openai
  AUDIT_LLM_MODEL      modelo (alias del proxy en LiteLLM). Por defecto: claude-opus-5-5 / deepseek-flash
  AUDIT_LLM_BASE_URL   deepseek: https://api.deepseek.com · litellm: http://localhost:4000 · openai: obligatoria (p. ej. http://localhost:11434/v1)
  AUDIT_LLM_API_KEY    o la propia del proveedor: ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, LITELLM_API_KEY, OPENAI_API_KEY
  AUDIT_LLM_EFFORT     esfuerzo de razonamiento (anthropic: low…max; deepseek: low/high/max). Por defecto high
  AUDIT_LLM_MAX_TOKENS salida máxima en proveedores OpenAI-compatibles (por defecto 8192)
  AUDIT_LLM_TOOLS      0 = sin herramientas (modelos que no las soportan): el chat queda como consulta sobre la instantánea
  AUDIT_LLM_PASS_REASONING  1/0: reenviar reasoning_content (por defecto 1 solo con deepseek; actívalo si LiteLLM apunta a DeepSeek)
  AUDIT_LLM_EXTRA_BODY JSON que se fusiona en el cuerpo de la petición (p. ej. {"thinking":{"type":"disabled"}})
"""
import ipaddress
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Campaign, LLMProfile

PROVIDERS = ("anthropic", "deepseek", "litellm", "openai")
_DEFAULT_MODEL = {"anthropic": "claude-opus-5-5", "deepseek": "deepseek-flash", "litellm": "", "openai": ""}
_DEFAULT_URL = {"anthropic": "", "deepseek": "https://api.deepseek.com", "litellm": "http://localhost:4000", "openai": ""}
_KEY_VARS = {"anthropic": ("ANTHROPIC_API_KEY",), "deepseek": ("DEEPSEEK_API_KEY",),
             "litellm": ("LITELLM_API_KEY", "LITELLM_MASTER_KEY"), "openai": ("OPENAI_API_KEY",)}
_LABEL = {"anthropic": "Anthropic", "deepseek": "DeepSeek", "litellm": "LiteLLM", "openai": "API compatible con OpenAI"}


@dataclass
class LLMResponse:
    content: list[dict]  # bloques canónicos (formato Anthropic: text / tool_use / thinking) tal cual se guardan y reenvían
    stop_reason: str  # end_turn | tool_use | max_tokens | refusal
    refusal_category: str | None = None
    usage: dict = field(default_factory=dict)


@dataclass
class Settings:
    provider: str
    model: str
    base_url: str
    api_key: str
    effort: str
    max_tokens: int
    tools: bool
    pass_reasoning: bool
    extra_body: dict
    source: str = "env"  # env | profile
    profile_id: int | None = None
    profile_name: str = ""

    @property
    def host(self) -> str:
        return urlparse(self.base_url).netloc if self.base_url else "api.anthropic.com"

    @property
    def external(self) -> bool:
        """True si los datos salen de tu red (servidor remoto). localhost y redes privadas cuentan como locales."""
        name = (urlparse(self.base_url).hostname or "") if self.base_url else "api.anthropic.com"
        if name == "localhost" or name.endswith((".local", ".internal", ".lan")):
            return False
        try:
            ip = ipaddress.ip_address(name)
            return not (ip.is_loopback or ip.is_private or ip.is_link_local)
        except ValueError:
            return "." in name  # dominio público; un host sin puntos (p. ej. "litellm" dentro de docker) es interno

    @property
    def label(self) -> str:
        return f"{_LABEL.get(self.provider, self.provider)} ({self.host})"


def _truthy(value: str | None, default: bool) -> bool:
    return default if value is None or value == "" else value.strip().lower() not in ("0", "false", "no", "off")


def env_settings() -> Settings:
    provider = os.environ.get("AUDIT_LLM_PROVIDER", "anthropic").strip().lower()
    key = os.environ.get("AUDIT_LLM_API_KEY", "")
    for var in _KEY_VARS.get(provider, ()):
        key = key or os.environ.get(var, "")
    try:
        extra = json.loads(os.environ.get("AUDIT_LLM_EXTRA_BODY") or "{}")
        extra = extra if isinstance(extra, dict) else {}
    except ValueError:
        extra = {}
    try:
        max_tokens = int(os.environ.get("AUDIT_LLM_MAX_TOKENS") or 8192)
    except ValueError:
        max_tokens = 8192
    return Settings(
        provider=provider,
        model=os.environ.get("AUDIT_LLM_MODEL") or _DEFAULT_MODEL.get(provider, ""),
        base_url=(os.environ.get("AUDIT_LLM_BASE_URL") or _DEFAULT_URL.get(provider, "")).rstrip("/"),
        api_key=key,
        effort=os.environ.get("AUDIT_LLM_EFFORT", "high"),
        max_tokens=max_tokens,
        tools=_truthy(os.environ.get("AUDIT_LLM_TOOLS"), True),
        pass_reasoning=_truthy(os.environ.get("AUDIT_LLM_PASS_REASONING"), provider == "deepseek"),
        extra_body=extra,
    )


settings = env_settings  # compatibilidad: configuración por entorno


def from_profile(p: LLMProfile) -> Settings:
    provider = (p.provider or "").strip().lower()
    key = p.api_key or ""
    for var in _KEY_VARS.get(provider, ()):  # sin clave en el perfil, vale la del entorno
        key = key or os.environ.get(var, "")
    return Settings(
        provider=provider, model=p.model or _DEFAULT_MODEL.get(provider, ""), base_url=(p.base_url or _DEFAULT_URL.get(provider, "")).rstrip("/"),
        api_key=key, effort=p.effort or "high", max_tokens=p.max_tokens or 8192, tools=bool(p.tools),
        pass_reasoning=p.pass_reasoning if p.pass_reasoning is not None else provider == "deepseek",
        extra_body=p.extra_body or {}, source="profile", profile_id=p.id, profile_name=p.name,
    )


def resolve(db: Session, campaign: Campaign | None) -> Settings:
    """Proveedor de una campaña: su perfil elegido → el perfil predeterminado → la configuración por entorno."""
    prof = db.get(LLMProfile, campaign.llm_profile_id) if campaign is not None and campaign.llm_profile_id else None
    if prof is None:
        prof = db.scalar(select(LLMProfile).where(LLMProfile.is_default.is_(True)))
    return from_profile(prof) if prof is not None else env_settings()


def problem(s: Settings | None = None) -> str | None:
    """Motivo por el que el LLM no está listo (None = listo)."""
    s = s or env_settings()
    if s.provider not in PROVIDERS:
        return f"AUDIT_LLM_PROVIDER={s.provider!r} no es válido (usa: {', '.join(PROVIDERS)})"
    if s.provider == "anthropic":
        if not (s.api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN") or (Path.home() / ".config" / "anthropic").exists()):  # `ant auth login` también vale
            return "No hay credenciales de Anthropic (añade la clave en el perfil o define ANTHROPIC_API_KEY y reinicia el backend)"
        return None
    if not s.model:
        return "Falta AUDIT_LLM_MODEL (en LiteLLM, el model_name de tu config.yaml)"
    if not s.base_url:
        return "Falta AUDIT_LLM_BASE_URL (p. ej. http://localhost:11434/v1)"
    if urlparse(s.base_url).scheme not in ("http", "https") or not urlparse(s.base_url).netloc:
        return f"AUDIT_LLM_BASE_URL no es una URL http(s) válida: {s.base_url!r}"
    if s.provider == "deepseek" and not s.api_key:
        return "Falta la clave de DeepSeek (añádela en el perfil o define DEEPSEEK_API_KEY y reinicia el backend)"
    return None


def configured(s: Settings | None = None) -> bool:
    return problem(s) is None


async def create_message(system: str, messages: list[dict], tools: list[dict], settings: Settings | None = None) -> LLMResponse:
    s = settings or env_settings()
    if not s.tools:
        tools = []
    if s.provider == "anthropic":
        return await _anthropic(s, system, messages, tools)
    from . import openai_compat

    return await openai_compat.create_message(s, system, messages, tools)


async def _anthropic(s: Settings, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(max_retries=2, **({"api_key": s.api_key} if s.api_key else {}))
    # Thinking siempre activo en Opus 5.5 (no se envía el parámetro). Streaming para evitar timeouts en turnos largos.
    # Fallbacks de rechazo: si un clasificador declina, el servidor reintenta con el modelo alternativo por categoría.
    async with client.beta.messages.stream(
        model=s.model, max_tokens=16_000, system=system, messages=messages, **({"tools": tools} if tools else {}),
        output_config={"effort": s.effort},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
    ) as stream:
        msg = await stream.get_final_message()
    details = getattr(msg, "stop_details", None)
    return LLMResponse(
        content=[b.model_dump(mode="json", exclude_none=True) for b in msg.content],
        stop_reason=msg.stop_reason or "",
        refusal_category=getattr(details, "category", None) if details else None,
        usage=msg.usage.model_dump(mode="json", exclude_none=True) if getattr(msg, "usage", None) else {},
    )
