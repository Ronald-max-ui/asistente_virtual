"""Validated commercial domain values; no repository or service imports."""
import re
from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator, field_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=2000)

class Promotion(StrictModel):
    id: StrictStr
    description: StrictStr
    kind: Literal["percent", "fixed", "informative"]
    value: Decimal | None = None
    conditions: StrictStr
    @model_validator(mode="after")
    def validate_value(self):
        if self.kind == "informative" and self.value is not None:
            raise ValueError("Promoción informativa sin valor calculable")
        if self.kind != "informative" and (self.value is None or not self.value.is_finite() or self.value < 0):
            raise ValueError("Valor de promoción inválido")
        if self.kind == "percent" and self.value > 100:
            raise ValueError("Porcentaje inválido")
        return self

class PriceEntry(StrictModel):
    concept: Literal["inscripcion", "matricula", "mensualidad", "mensualidad_contado", "pago_contado", "ciclo_completo", "descuento"]
    modality: StrictStr | None
    shift: StrictStr | None
    amount: Decimal | None = Field(max_digits=10, decimal_places=2)
    currency: StrictStr = Field(pattern=r"^[A-Z]{3}$")
    status: Literal["active", "free", "pending", "inactive"]
    campaign: StrictStr = Field(min_length=1)
    starts_on: date | None
    ends_on: date | None
    promotions: list[Promotion] = Field(default_factory=list)
    observations: StrictStr = ""

    @field_validator("amount", mode="before")
    @classmethod
    def decimal_only(cls, value):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
            raise ValueError("Monto debe ser decimal exacto")
        if isinstance(value, str) and not re.fullmatch(r"\d+(?:\.\d{1,2})?", value):
            raise ValueError("Formato de monto inválido")
        return value

    @field_validator("starts_on", "ends_on", mode="before")
    @classmethod
    def date_only(cls, value):
        if value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Fecha debe ser YYYY-MM-DD")
        return value

    @model_validator(mode="after")
    def validate_price(self):
        if self.amount is not None and (not self.amount.is_finite() or self.amount < 0 or self.amount.as_tuple().exponent < -2):
            raise ValueError("Monto inválido")
        if self.status == "active" and (self.amount is None or self.amount <= 0):
            raise ValueError("active requiere amount positivo")
        if self.status == "free" and self.amount != Decimal(0):
            raise ValueError("free requiere amount 0")
        if self.status == "pending" and self.amount is not None:
            raise ValueError("pending requiere amount null")
        if self.starts_on and self.ends_on and self.starts_on > self.ends_on:
            raise ValueError("Rango de fechas inválido")
        return self

class ProgramCatalog(StrictModel):
    schema_version: Literal[1]
    program: StrictStr = Field(pattern=r"^[a-z][a-z0-9_]*$")
    program_label: StrictStr = Field(min_length=1)
    aliases: list[StrictStr]
    modalities: list[StrictStr]
    shifts: list[StrictStr] = Field(default_factory=list)
    prices: list[PriceEntry]

    @model_validator(mode="after")
    def validate_entries(self):
        for values in (self.modalities, self.shifts):
            if len(set(values)) != len(values) or any(not re.fullmatch(r"[a-z][a-z0-9_]*", v) for v in values):
                raise ValueError("Variantes inválidas")
        if not self.modalities or not self.prices:
            raise ValueError("Catálogo incompleto")
        for entry in self.prices:
            if entry.modality is not None and entry.modality not in self.modalities:
                raise ValueError("Modalidad no registrada")
            if entry.shift is not None and entry.shift not in self.shifts:
                raise ValueError("Turno no registrado")
        enabled = [p for p in self.prices if p.status != "inactive"]
        for index, first in enumerate(enabled):
            for second in enabled[index+1:]:
                same_scope = first.concept == second.concept and (first.modality is None or second.modality is None or first.modality == second.modality) and (first.shift is None or second.shift is None or first.shift == second.shift)
                overlap = max(first.starts_on or date.min, second.starts_on or date.min) <= min(first.ends_on or date.max, second.ends_on or date.max)
                if same_scope and overlap:
                    raise ValueError("Campañas superpuestas para una misma tarifa")
        return self

CONCEPTOS = ("inscripcion", "matricula", "mensualidad", "mensualidad_contado", "pago_contado", "ciclo_completo", "descuento")
