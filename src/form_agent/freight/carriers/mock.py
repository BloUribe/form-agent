"""Proveedores simulados y deterministas: para tests y para operar sin credenciales."""
from __future__ import annotations

from datetime import timedelta

from ..models import Quote, Sailing, ShipmentRequest

_BASE_PRICE = {"20DRY": 1800.0, "40DRY": 2900.0, "40HC": 3100.0, "45HC": 3400.0}
_VESSELS = [("MOCK ATLAS", "9000001", 0, 32), ("MOCK BOREAL", "9000002", 3, 35), ("MOCK CORAL", "9000003", 6, 30)]


class MockScheduleProvider:
    def search(self, request: ShipmentRequest) -> list[Sailing]:
        return [Sailing(carrier="MOCK", vessel_name=name, vessel_imo=imo, voyage=f"{i + 101}E",
                        etd=request.departure_date + timedelta(days=offset),
                        eta=request.departure_date + timedelta(days=offset + transit))
                for i, (name, imo, offset, transit) in enumerate(_VESSELS)]


class MockRateProvider:
    def quote(self, request: ShipmentRequest, sailing: Sailing) -> Quote | None:
        base = _BASE_PRICE.get(request.container_type, 3100.0)
        # leve variación por salida para que las opciones se distingan
        extra = (sailing.etd - request.departure_date).days * 15
        return Quote(price_per_container=base + extra, source="mock")
