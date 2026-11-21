import enum
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class AuditType(str, enum.Enum):
    OT = "OT"
    IoT = "IoT"
    Web = "Web"
    Mobile = "Mobile"
    Red = "Red"
    Mixta = "Mixta"


class CampaignStatus(str, enum.Enum):
    planned = "planned"
    active = "active"
    closed = "closed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    audit_type: Mapped[AuditType] = mapped_column(Enum(AuditType))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    scope: Mapped[str] = mapped_column(Text, default="")  # rangos/hosts permitidos, uno por línea
    status: Mapped[CampaignStatus] = mapped_column(Enum(CampaignStatus), default=CampaignStatus.planned)
    llm_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # privacidad: LLM off por defecto
    llm_redaction: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")  # seudonimizar IPs/hosts/MAC antes de enviar al LLM
    llm_profile_id: Mapped[int | None] = mapped_column(ForeignKey("llm_profiles.id", ondelete="SET NULL"), nullable=True)  # None = perfil predeterminado o entorno
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class RunStatus(str, enum.Enum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ToolRun(Base):
    __tablename__ = "tool_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    server: Mapped[str] = mapped_column(String(100))
    tool: Mapped[str] = mapped_column(String(100))
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    origin: Mapped[str] = mapped_column(String(20), default="manual")  # manual | agent (Fase 4)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.running)
    output: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("campaign_id", "ip"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    ip: Mapped[str] = mapped_column(String(64))
    hostname: Mapped[str] = mapped_column(String(255), default="")
    mac: Mapped[str] = mapped_column(String(32), default="")
    vendor: Mapped[str] = mapped_column(String(200), default="")
    ports: Mapped[list] = mapped_column(JSON, default=list)  # [{port, proto, service, product, version}]
    sources: Mapped[list] = mapped_column(JSON, default=list)  # herramientas que lo han visto
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Capture(Base):
    __tablename__ = "captures"
    __table_args__ = (UniqueConstraint("campaign_id", "sha256"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))  # nombre original (solo informativo)
    path: Mapped[str] = mapped_column(Text)  # ruta absoluta del fichero guardado
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="analyzing")  # analyzing | analyzed | failed
    error: Mapped[str] = mapped_column(Text, default="")
    packets: Mapped[int] = mapped_column(Integer, default=0)
    non_ip_packets: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Flow(Base):
    __tablename__ = "flows"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    capture_id: Mapped[int] = mapped_column(ForeignKey("captures.id", ondelete="CASCADE"), index=True)
    src_ip: Mapped[str] = mapped_column(String(64))  # cliente (heurística: puerto efímero)
    dst_ip: Mapped[str] = mapped_column(String(64))  # servidor
    transport: Mapped[str] = mapped_column(String(20))
    port: Mapped[int] = mapped_column(Integer)  # puerto de servicio
    protocol: Mapped[str] = mapped_column(String(100))
    packets: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FlowEvent(Base):
    """Contenido de protocolo visto en una captura (HTTP, MQTT, Modbus, S7, FTP), agregado por flujo y resumen."""
    __tablename__ = "flow_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    capture_id: Mapped[int] = mapped_column(ForeignKey("captures.id", ondelete="CASCADE"), index=True)
    src_ip: Mapped[str] = mapped_column(String(64))  # cliente (igual que Flow)
    dst_ip: Mapped[str] = mapped_column(String(64))  # servidor
    transport: Mapped[str] = mapped_column(String(20))
    port: Mapped[int] = mapped_column(Integer)
    protocol: Mapped[str] = mapped_column(String(20))  # http | mqtt | modbus | s7 | ftp
    direction: Mapped[str] = mapped_column(String(3))  # c2s | s2c
    kind: Mapped[str] = mapped_column(String(20))  # request | response | write | control | auth
    summary: Mapped[str] = mapped_column(String(300))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    secret: Mapped[bool] = mapped_column(Boolean, default=False)  # lleva una credencial en claro
    secret_kind: Mapped[str] = mapped_column(String(40), default="")


class FindingPhase(str, enum.Enum):
    discovery = "discovery"  # Descubrimiento
    exploitation = "exploitation"  # Explotación
    post_exploitation = "post_exploitation"  # Post-Explotación


class FindingStatus(str, enum.Enum):
    draft = "draft"
    confirmed = "confirmed"
    false_positive = "false_positive"


finding_assets = Table(
    "finding_assets",
    Base.metadata,
    Column("finding_id", ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True),
    Column("asset_id", ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
)


def rating_from_score(score: float | None) -> str:
    """Rango cualitativo CVSS (idéntico en 3.x y 4.0)."""
    if score is None:
        return ""
    if score == 0:
        return "None"
    if score < 4:
        return "Low"
    if score < 7:
        return "Medium"
    if score < 9:
        return "High"
    return "Critical"


class Finding(Base):
    """Estructura alineada con el informe: Identifier, Name, Criticality, Affected assets, Description (+PoC, Impact), Recommendations."""

    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    identifier: Mapped[str] = mapped_column(String(50), default="")  # lo asigna el auditor
    name: Mapped[str] = mapped_column(String(300))
    phase: Mapped[FindingPhase] = mapped_column(Enum(FindingPhase), default=FindingPhase.discovery)
    status: Mapped[FindingStatus] = mapped_column(Enum(FindingStatus), default=FindingStatus.draft)
    cvss_vector: Mapped[str] = mapped_column(String(300), default="")
    cvss_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    poc: Mapped[str] = mapped_column(Text, default="")
    impact: Mapped[str] = mapped_column(Text, default="")
    recommendations: Mapped[str] = mapped_column(Text, default="")
    affected_other: Mapped[str] = mapped_column(String(500), default="")  # activos sin IP (p. ej. "Vending Machine")
    source_key: Mapped[str] = mapped_column(String(300), default="", index=False)  # origen automático (evento de captura): evita duplicados
    depends_on_id: Mapped[int | None] = mapped_column(ForeignKey("findings.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    assets: Mapped[list["Asset"]] = relationship(secondary=finding_assets, lazy="selectin")

    @property
    def asset_ids(self) -> list[int]:
        return sorted(a.id for a in self.assets)

    @property
    def rating(self) -> str:
        return rating_from_score(self.cvss_score)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("campaign_id", "sha256"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    finding_id: Mapped[int | None] = mapped_column(ForeignKey("findings.id", ondelete="SET NULL"), nullable=True, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)  # orden dentro del hallazgo → "Evidencia N"
    filename: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(String(50))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    caption: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RedactionMap(Base):
    """Seudónimos estables por campaña (IP-0001 ↔ valor real). Los valores reales nunca salen de esta BD."""

    __tablename__ = "redaction_map"
    __table_args__ = (UniqueConstraint("campaign_id", "real"), UniqueConstraint("campaign_id", "token"))

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # IP | NET | HOST | MAC
    real: Mapped[str] = mapped_column(String(300))
    token: Mapped[str] = mapped_column(String(20))


class ChatMessage(Base):
    """Historial EXACTO de la API (api_content): lo enviado y recibido, con seudónimos. Se reenvía sin tocar
    (los bloques de thinking del modelo solo son válidos si el historial es append-only)."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    kind: Mapped[str] = mapped_column(String(10), default="normal")  # normal | error (los error no se reenvían)
    api_content: Mapped[list] = mapped_column(JSON, default=list)
    display_text: Mapped[str] = mapped_column(Text, default="")  # lo que escribió el auditor (valores reales)
    stop_reason: Mapped[str] = mapped_column(String(30), default="")
    provider: Mapped[str] = mapped_column(String(30), default="", server_default="")  # proveedor que generó el mensaje assistant ('' = anthropic, previo)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentCall(Base):
    """Una llamada a herramienta pedida por el modelo (bloque tool_use)."""

    __tablename__ = "agent_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True)
    tool_use_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    input: Mapped[dict] = mapped_column(JSON, default=dict)  # valores REALES (ya restaurados)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | running | done | failed | denied
    result_text: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[int | None] = mapped_column(ForeignKey("tool_runs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Report(Base):
    """Datos editables del informe de una campaña (metadatos y textos). Hallazgos/activos se leen de sus tablas."""

    __tablename__ = "reports"

    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ScopeChange(Base):
    """Historial del alcance: es el límite de lo autorizado, conviene poder demostrar cuándo y cómo cambió."""

    __tablename__ = "scope_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    old_scope: Mapped[str] = mapped_column(Text, default="")
    new_scope: Mapped[str] = mapped_column(Text, default="")
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LLMProfile(Base):
    """Conexión a un proveedor de LLM. La clave se guarda en texto plano en la BD local (decisión del usuario) y NUNCA sale por la API."""

    __tablename__ = "llm_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    provider: Mapped[str] = mapped_column(String(30))  # anthropic | deepseek | litellm | openai
    model: Mapped[str] = mapped_column(String(200), default="")
    base_url: Mapped[str] = mapped_column(String(300), default="")
    api_key: Mapped[str] = mapped_column(Text, default="")
    effort: Mapped[str] = mapped_column(String(20), default="high")
    max_tokens: Mapped[int] = mapped_column(Integer, default=8192)
    tools: Mapped[bool] = mapped_column(Boolean, default=True)
    pass_reasoning: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # None = según proveedor
    extra_body: Mapped[dict] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
