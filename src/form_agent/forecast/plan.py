"""Reparte los contenedores pronosticados (P10/P50/P90) entre las salidas del mes objetivo, por ruta."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from ..dates import add_months
from ..freight.carriers.base import RateProvider, ScheduleProvider
from ..freight.models import Quote, Sailing, ShipmentRequest
from .model import Forecast

TIERS = ("buy", "prepare", "watch")  # comprar (P10), preparar (P10→P50), vigilar (P50→P90)
_TEU = {"20DRY": 1, "40DRY": 2, "40HC": 2, "45HC": 3}


@dataclass(frozen=True)
class Recommendation:
    tier: str
    origin: str
    destination: str
    ref: str | None
    vessel_name: str
    voyage: str | None
    etd: date
    containers: int
    price_per_container: float
    currency: str
    vs_avg_pct: float  # negativo = más barata que el promedio de las salidas de esa ruta en el mes


@dataclass(frozen=True)
class Unplaced:
    tier: str
    origin: str
    destination: str
    containers: int
    reason: str


@dataclass(frozen=True)
class Plan:
    recommendations: list[Recommendation]
    unplaced: list[Unplaced]


def month_sailings(origin: str, destination: str, month: date, schedules: ScheduleProvider, rates: RateProvider,
                   container_type: str) -> list[tuple[Sailing, Quote]]:
    """Salidas con precio dentro del mes. Los proveedores devuelven ventanas de ~21 días: se consulta cada semana."""
    end, found = add_months(month, 1), {}
    for week in range(5):
        start = month + timedelta(days=7 * week)
        if start >= end:
            break
        request = ShipmentRequest(origin_port=origin, destination_port=destination, container_count=1,
                                  container_type=container_type, departure_date=start)
        for s in schedules.search(request):
            key = (s.vessel_name, s.voyage, s.etd)
            if month <= s.etd < end and key not in found and (q := rates.quote(request, s)) is not None:
                found[key] = (s, q)
    return sorted(found.values(), key=lambda sq: (sq[1].price_per_container, sq[0].etd))


def build_plan(forecasts: list[Forecast], schedules: ScheduleProvider, rates: RateProvider,
               container_type: str = "40HC", max_share: float = 0.5) -> Plan:
    teu = _TEU.get(container_type, 2)
    recommendations: list[Recommendation] = []
    unplaced: list[Unplaced] = []
    for f in forecasts:
        amounts = {"buy": f.p10, "prepare": f.p50 - f.p10, "watch": f.p90 - f.p50}
        if not any(amounts.values()):
            continue
        options = month_sailings(f.origin, f.destination, f.target, schedules, rates, container_type)
        avg = statistics.fmean(q.price_per_container for _, q in options) if options else 0.0
        room = {id(s): (math.inf if q.free_teu is None else q.free_teu // teu) for s, q in options}
        for tier in TIERS:
            remaining = amounts[tier]
            if remaining <= 0:
                continue
            per_sailing_cap = max(1, math.ceil(max_share * remaining))
            for s, q in options:
                take = min(remaining, per_sailing_cap, room[id(s)])
                if take <= 0:
                    continue
                room[id(s)] -= take
                remaining -= take
                recommendations.append(Recommendation(
                    tier, f.origin, f.destination, s.ref, s.vessel_name, s.voyage, s.etd, int(take),
                    q.price_per_container, q.currency, (q.price_per_container / avg - 1) * 100))
            if remaining > 0:
                if not options:
                    reason = "sin salidas en el mes"
                elif any(v > 0 for v in room.values()):  # aún queda capacidad: lo frena el tope por salida
                    reason = "límite de reparto por salida (max_share)"
                else:
                    reason = "capacidad libre insuficiente"
                unplaced.append(Unplaced(tier, f.origin, f.destination, int(remaining), reason))
    return Plan(recommendations, unplaced)
