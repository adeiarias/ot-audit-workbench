from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import AuditType, CampaignStatus, RunStatus
from .scope import validate_scope


class CampaignBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    audit_type: AuditType
    start_date: date
    end_date: date | None = None
    scope: str = ""
    llm_enabled: bool = False
    llm_redaction: bool = True

    @field_validator("scope")
    @classmethod
    def _scope(cls, v: str) -> str:
        validate_scope(v)
        return v

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date no puede ser anterior a start_date")
        return self


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    audit_type: AuditType | None = None
    start_date: date | None = None
    end_date: date | None = None
    scope: str | None = None
    status: CampaignStatus | None = None
    llm_enabled: bool | None = None
    llm_redaction: bool | None = None
    llm_profile_id: int | None = None  # null explícito = volver al predeterminado

    @field_validator("scope")
    @classmethod
    def _scope(cls, v: str | None) -> str | None:
        if v is not None:
            validate_scope(v)
        return v


class CampaignOut(CampaignBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    llm_profile_id: int | None = None
    status: CampaignStatus
    created_at: datetime
    updated_at: datetime


class RunCreate(BaseModel):
    server: str
    tool: str
    arguments: dict = Field(default_factory=dict)


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    server: str
    tool: str
    arguments: dict
    origin: str
    status: RunStatus
    output: str
    error: str
    created_at: datetime
    finished_at: datetime | None


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    ip: str
    hostname: str
    mac: str
    vendor: str
    ports: list
    sources: list
    first_seen: datetime
    last_seen: datetime
    in_scope: bool = True  # se calcula con el alcance ACTUAL de la campaña


class CaptureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    filename: str
    sha256: str
    size: int
    status: str
    error: str
    packets: int
    non_ip_packets: int
    created_at: datetime


import re  # noqa: E402

from .models import FindingPhase, FindingStatus  # noqa: E402

_CVSS_VECTOR = re.compile(r"^CVSS:(3\.0|3\.1|4\.0)(/[A-Za-z]{1,10}:[A-Za-z0-9]{1,10}){3,}$")
_LONG = 100_000


def _check_cvss_vector(v: str | None) -> str | None:
    if v and not _CVSS_VECTOR.match(v):
        raise ValueError("Vector CVSS no válido (esperado p. ej. CVSS:3.1/AV:N/AC:L/...)")
    return v


class FindingBase(BaseModel):
    identifier: str = Field(default="", max_length=50)
    name: str = Field(min_length=1, max_length=300)
    phase: FindingPhase = FindingPhase.discovery
    status: FindingStatus = FindingStatus.draft
    cvss_vector: str = Field(default="", max_length=300)
    cvss_score: float | None = Field(default=None, ge=0, le=10)
    description: str = Field(default="", max_length=_LONG)
    poc: str = Field(default="", max_length=_LONG)
    impact: str = Field(default="", max_length=_LONG)
    recommendations: str = Field(default="", max_length=_LONG)
    affected_other: str = Field(default="", max_length=500)
    depends_on_id: int | None = None
    asset_ids: list[int] = Field(default_factory=list)

    _v = field_validator("cvss_vector")(_check_cvss_vector)


class FindingCreate(FindingBase):
    pass


class FindingUpdate(BaseModel):
    identifier: str | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=300)
    phase: FindingPhase | None = None
    status: FindingStatus | None = None
    cvss_vector: str | None = Field(default=None, max_length=300)
    cvss_score: float | None = Field(default=None, ge=0, le=10)
    description: str | None = Field(default=None, max_length=_LONG)
    poc: str | None = Field(default=None, max_length=_LONG)
    impact: str | None = Field(default=None, max_length=_LONG)
    recommendations: str | None = Field(default=None, max_length=_LONG)
    affected_other: str | None = Field(default=None, max_length=500)
    depends_on_id: int | None = None
    asset_ids: list[int] | None = None

    _v = field_validator("cvss_vector")(_check_cvss_vector)


class FindingOut(FindingBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    rating: str
    created_at: datetime
    updated_at: datetime


class EvidenceUpdate(BaseModel):
    caption: str | None = Field(default=None, max_length=500)
    finding_id: int | None = None  # None explícito = desvincular


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    finding_id: int | None
    position: int
    filename: str
    mime: str
    sha256: str
    size: int
    caption: str
    created_at: datetime
