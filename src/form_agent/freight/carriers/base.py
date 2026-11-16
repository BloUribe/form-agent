"""Interfaces que implementa cada naviera/proveedor. Cambiar de naviera = cambiar de implementación."""
from __future__ import annotations

from typing import Protocol

from ..models import Quote, Sailing, ShipmentRequest


class ScheduleProvider(Protocol):
    def search(self, request: ShipmentRequest) -> list[Sailing]: ...


class RateProvider(Protocol):
    def quote(self, request: ShipmentRequest, sailing: Sailing) -> Quote | None: ...
