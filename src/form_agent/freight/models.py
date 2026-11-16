"""Modelos del dominio: la solicitud de envío y las opciones de salida."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator


class ShipmentRequest(BaseModel):
    """Datos que el agente extrae del correo. Puertos en UN/LOCODE (5 letras, ej. CLSAI)."""
    origin_port: str
    destination_port: str
    container_count: int = Field(gt=0)
    container_type: str = "40HC"  # 20DRY, 40DRY, 40HC...
    weight_kg: float | None = Field(default=None, gt=0)
    departure_date: date

    @field_validator("origin_port", "destination_port")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class Sailing(BaseModel):
    """Una salida publicada por la naviera (sin precio)."""
    carrier: str
    vessel_name: str
    vessel_imo: str | None = None
    voyage: str | None = None
    etd: date
    eta: date | None = None
    transshipments: int = 0
    ref: str | None = None  # id estable en la fuente de datos (la BD simulada lo usa para buscar precio y capacidad)


class Quote(BaseModel):
    """Precio por contenedor y nota de disponibilidad."""
    price_per_container: float
    currency: str = "USD"
    availability: str = "sujeta a confirmación al reservar"
    source: str = "mock"
    free_teu: int | None = None  # TEU libres si la fuente lo informa (None = desconocido)


class SailingOption(BaseModel):
    """Lo que se le muestra al usuario: salida + precio total."""
    id: int
    sailing: Sailing
    quote: Quote | None = None
    total_price: float | None = None

    @property
    def etd(self) -> date:
        return self.sailing.etd
