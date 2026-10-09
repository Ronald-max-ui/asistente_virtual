"""DTO administrativos; reglas monetarias reutilizadas de PricingService."""
from typing import Literal, Annotated
from datetime import date
from pathlib import PurePosixPath
import math
from pydantic import Field, StrictBool, StrictStr, model_validator
from domain.pricing import StrictModel, PriceEntry, Promotion
ProgramName = Annotated[StrictStr, Field(max_length=120)]
Variant = Annotated[StrictStr, Field(max_length=64)]

class ProgramRecord(StrictModel):
    id: StrictStr = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    name: StrictStr = Field(min_length=1, max_length=120)
    kind: Literal["carrera_tecnica", "curso_corto"]
    enabled: StrictBool = True
    aliases: list[ProgramName] = Field(default_factory=list, max_length=50)
    modalities: list[Variant] = Field(max_length=20)
    shifts: list[Variant] = Field(default_factory=list, max_length=30)
    academic_path: StrictStr | None = Field(default=None, max_length=240)
    @model_validator(mode="after")
    def path_is_relative(self):
        if self.academic_path and ("\\" in self.academic_path or PurePosixPath(self.academic_path).is_absolute() or ".." in PurePosixPath(self.academic_path).parts or not self.academic_path.endswith(".md")):
            raise ValueError("academic_path debe ser relativo a knowledge y terminar en .md")
        return self

class PriceRecord(PriceEntry):
    campaign: StrictStr = "base"
    id: StrictStr = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=128)
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
    id: StrictStr = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=64)
    name: StrictStr = Field(min_length=1, max_length=120)
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
    id: StrictStr = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=64)
    name: StrictStr = Field(min_length=1, max_length=120)
    url: StrictStr = Field(pattern=r"^/static/avatars/[a-zA-Z0-9_-]+\.vrm$")
    enabled: StrictBool = True
    active: StrictBool = False
    thumbnail_url: StrictStr | None = Field(default=None,pattern=r"^/static/(?:media|branding)/[a-zA-Z0-9_-]+\.(?:png|webp|jpe?g)$")
    description: StrictStr = Field(default="",max_length=500)

class SettingsRecord(StrictModel):
    assistant_name: StrictStr = Field(min_length=1, max_length=120)
    active_avatar_id: StrictStr | None = None
    logo_url: StrictStr | None = Field(default=None, pattern=r"^/static/(?:media|branding)/[a-zA-Z0-9_-]+\.(?:png|webp|jpe?g)$")
    favicon_url: StrictStr | None = Field(default=None, pattern=r"^/static/(?:media|branding)/[a-zA-Z0-9_-]+\.(?:png|webp)$")
    kiosk_text_enabled: StrictBool = False
    primary_color: StrictStr | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    initial_message: StrictStr = Field(default="",max_length=500)
    voice: dict = Field(default_factory=dict)
    extensions: dict = Field(default_factory=dict)
    @model_validator(mode='after')
    def settings_are_public_configuration_not_secrets(self):
        sensitive = {'api_key','groq_api_key','admin_api_token','authorization','password','secret','access_token','refresh_token','token'}
        def check(value, depth=0):
            if depth > 8: raise ValueError('Configuración anidada demasiado profunda')
            if isinstance(value, dict):
                if len(value) > 64: raise ValueError('Demasiadas claves de configuración')
                for key, child in value.items():
                    if not isinstance(key,str) or len(key)>64 or key.lower().replace('-','_') in sensitive:
                        raise ValueError('No se admiten credenciales en settings')
                    check(child, depth+1)
            elif isinstance(value, list):
                if len(value)>100: raise ValueError('Lista de configuración demasiado grande')
                for child in value: check(child, depth+1)
            elif isinstance(value,str) and len(value)>2000:
                raise ValueError('Valor de configuración demasiado largo')
            elif isinstance(value,float) and not math.isfinite(value):
                raise ValueError('Número de configuración no válido')
        if self.voice:
            from domain.voice import VoiceConfig
            VoiceConfig.model_validate(self.voice)
        if '<' in self.initial_message or '>' in self.initial_message or any(ord(c)<32 and c not in '\n\t' for c in self.initial_message):
            raise ValueError('El mensaje inicial debe ser texto plano')
        check(self.voice)
        check(self.extensions)
        return self
