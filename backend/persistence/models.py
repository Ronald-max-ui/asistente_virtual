"""DTO administrativos; reglas monetarias reutilizadas de PricingService."""
from typing import Literal
from datetime import date
from pathlib import PurePosixPath
from pydantic import Field, StrictBool, StrictStr, model_validator
from services.pricing_service import StrictModel, PriceEntry, Promotion

class ProgramRecord(StrictModel):
    id: StrictStr = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: StrictStr = Field(min_length=1)
    kind: Literal["carrera_tecnica", "curso_corto"]
    enabled: StrictBool = True
    aliases: list[StrictStr] = Field(default_factory=list)
    modalities: list[StrictStr]
    shifts: list[StrictStr] = Field(default_factory=list)
    academic_path: StrictStr | None = None
    @model_validator(mode="after")
    def path_is_relative(self):
        if self.academic_path and ("\\" in self.academic_path or PurePosixPath(self.academic_path).is_absolute() or ".." in PurePosixPath(self.academic_path).parts or not self.academic_path.endswith(".md")):
            raise ValueError("academic_path debe ser relativo a knowledge y terminar en .md")
        return self

class PriceRecord(PriceEntry):
    campaign: StrictStr = "base"
    id: StrictStr = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    program: StrictStr
    campaign_id: StrictStr | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    @model_validator(mode="after")
    def campaign_window_owned_by_campaign(self):
        if self.campaign_id and (self.starts_on is not None or self.ends_on is not None):
            raise ValueError("Las fechas de una oferta se editan en su campaña")
        return self

class CampaignRecord(StrictModel):
    id: StrictStr = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    name: StrictStr = Field(min_length=1)
    starts_on: StrictStr = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    ends_on: StrictStr = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    enabled: StrictBool = True
    notes: StrictStr = ""
    @model_validator(mode="after")
    def valid_window(self):
        if date.fromisoformat(self.starts_on) > date.fromisoformat(self.ends_on):
            raise ValueError("La fecha de inicio debe ser anterior o igual a la fecha final")
        return self

class AvatarRecord(StrictModel):
    id: StrictStr = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    name: StrictStr = Field(min_length=1)
    url: StrictStr = Field(pattern=r"^/static/avatars/[a-zA-Z0-9_-]+\.vrm$")
    enabled: StrictBool = True
    active: StrictBool = False

class SettingsRecord(StrictModel):
    assistant_name: StrictStr = Field(min_length=1)
    active_avatar_id: StrictStr | None = None
    logo_url: StrictStr | None = Field(default=None, pattern=r"^/static/media/[a-zA-Z0-9_-]+\.(?:png|webp|jpe?g)$")
    primary_color: StrictStr | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    initial_message: StrictStr = ""
    voice: dict = Field(default_factory=dict)
    extensions: dict = Field(default_factory=dict)
