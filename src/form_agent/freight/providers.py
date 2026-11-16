from __future__ import annotations

from datetime import date

import httpx

from ..config import Settings
from .carriers.base import RateProvider, ScheduleProvider
from .carriers.hapag import HapagScheduleProvider
from .carriers.mock import MockRateProvider
from .carriers.mockdb import MockDBRateProvider, MockDBScheduleProvider


def build_providers(settings: Settings, today: date | None = None) -> tuple[ScheduleProvider, RateProvider]:
    """Con credenciales completas de Hapag-Lloyd: horarios reales (y precios genéricos simulados, porque ninguna
    naviera grande tiene API pública de precios). Sin ellas: todo sale de la BD simulada (horarios, capacidad, precio)."""
    if settings.hapag_base_url and settings.hapag_client_id and settings.hapag_client_secret:
        client = httpx.Client(base_url=settings.hapag_base_url, timeout=20)
        return HapagScheduleProvider(client, settings.hapag_client_id, settings.hapag_client_secret), MockRateProvider()
    return MockDBScheduleProvider(settings.mock_db_path, today=today), MockDBRateProvider(settings.mock_db_path)
