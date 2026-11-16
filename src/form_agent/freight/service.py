"""Une horarios (ScheduleProvider) con precios (RateProvider) en opciones numeradas para el usuario."""
from __future__ import annotations

from .carriers.base import RateProvider, ScheduleProvider
from .models import SailingOption, ShipmentRequest


def find_options(request: ShipmentRequest, schedules: ScheduleProvider, rates: RateProvider) -> list[SailingOption]:
    sailings = sorted((s for s in schedules.search(request) if s.etd >= request.departure_date), key=lambda s: s.etd)
    options = []
    for i, sailing in enumerate(sailings, start=1):
        quote = rates.quote(request, sailing)
        total = quote.price_per_container * request.container_count if quote else None
        options.append(SailingOption(id=i, sailing=sailing, quote=quote, total_price=total))
    return options
