"""Forecast mensual de contenedores por ruta en Python puro (sin numpy/pandas/sklearn).

Pronóstico puntual = alpha × estacional + (1 − alpha) × nivel reciente, donde
  estacional = promedio del mismo mes de años previos × factor de crecimiento (últimos 3 meses completos antes de
               `as_of` frente a esos mismos meses en años previos);
  nivel      = promedio de los últimos 12 meses completos (sin temporada).
`alpha` (1, 0.5 ó 0) se elige por el menor error de backtest de la ruta: series muy estacionales usan el mismo mes
de otros años; series ruidosas, el nivel reciente. P10/P50/P90 = pronóstico × cuantiles de la razón real/pronóstico
del backtest (mismo horizonte), o, con pocos datos, los cuantiles de los mismos meses previos.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date

from ..dates import add_months

__all__ = ["Forecast", "InsufficientHistory", "add_months", "forecast_lane"]

_MAX_YEARS_BACK = 5
_GROWTH_BOUNDS = (0.5, 2.0)
_MIN_RATIOS = 8  # con menos errores de backtest los cuantiles de razones no son fiables
_ALPHAS = (1.0, 0.5, 0.0)  # peso del pronóstico estacional; el resto va al nivel reciente
_LEVEL_MONTHS, _LEVEL_MIN = 12, 6


class InsufficientHistory(ValueError):
    """No hay el mismo mes de ningún año previo para esta ruta."""


@dataclass(frozen=True)
class Forecast:
    origin: str
    destination: str
    target: date
    p10: int
    p50: int
    p90: int
    baseline: float
    growth: float
    years_used: int
    mae: float
    naive_mae: float
    coverage: float
    n_backtest: int
    alpha: float = 1.0


def _level(usable: dict[date, int], as_of: date) -> float | None:
    values = [usable[m] for j in range(1, _LEVEL_MONTHS + 1) if (m := add_months(as_of, -j)) in usable]
    return statistics.fmean(values) if len(values) >= _LEVEL_MIN else None


def _point(usable: dict[date, int], target: date, as_of: date, recent_months: int, alpha: float = 1.0):
    """(pronóstico, baseline, growth, años usados, mismos meses) o None si no hay el mismo mes de ningún año previo."""
    same_month = [usable[m] for k in range(1, _MAX_YEARS_BACK + 1) if (m := add_months(target, -12 * k)) in usable]
    if not same_month:
        return None
    baseline = statistics.fmean(same_month)
    window = [add_months(as_of, -j) for j in range(1, recent_months + 1)]
    growth = 1.0
    if all(m in usable for m in window):
        prior = [sum(usable[add_months(m, -12 * k)] for m in window) for k in range(1, _MAX_YEARS_BACK + 1)
                 if all(add_months(m, -12 * k) in usable for m in window)]
        if prior and statistics.fmean(prior) > 0:
            growth = min(max(sum(usable[m] for m in window) / statistics.fmean(prior), _GROWTH_BOUNDS[0]), _GROWTH_BOUNDS[1])
    point = baseline * growth
    level = _level(usable, as_of) if alpha < 1.0 else None
    if level is not None:
        point = alpha * point + (1 - alpha) * level
    return point, baseline, growth, len(same_month), same_month


def _quantile(sorted_values: list[float], q: float) -> float:
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def _backtest(usable: dict[date, int], horizon: int, recent_months: int, alpha: float):
    """Repite el pronóstico sobre cada mes histórico con solo los datos anteriores: (razones, error modelo, error ingenuo)."""
    ratios, model_err, naive_err = [], [], []
    for month in sorted(usable):
        as_k = add_months(month, -horizon)
        past = _point({m: v for m, v in usable.items() if m < as_k}, month, as_k, recent_months, alpha)
        if past is None:
            continue
        actual, forecast = usable[month], past[0]
        if forecast > 0:
            ratios.append(actual / forecast)
        naive = usable.get(add_months(month, -12))
        if naive is not None:
            model_err.append(abs(actual - forecast))
            naive_err.append(abs(actual - naive))
    return sorted(ratios), model_err, naive_err


def forecast_lane(history: dict[date, int], origin: str, destination: str, target: date, as_of: date,
                  recent_months: int = 3) -> Forecast:
    horizon = (target.year - as_of.year) * 12 + target.month - as_of.month
    if horizon < 1:
        raise ValueError("target debe ser un mes posterior al mes de as_of")
    usable = {m: v for m, v in history.items() if m < as_of}
    if _point(usable, target, as_of, recent_months) is None:
        raise InsufficientHistory(f"{origin}-{destination}: sin el mes {target:%m} de años previos")

    best = None  # (mae, alpha, razones, errores modelo, errores ingenuo)
    for alpha in _ALPHAS:
        ratios, model_err, naive_err = _backtest(usable, horizon, recent_months, alpha)
        mae = statistics.fmean(model_err) if model_err else math.inf
        if best is None or mae < best[0]:  # empate: gana el estacional (primero en _ALPHAS)
            best = (mae, alpha, ratios, model_err, naive_err)
    _, alpha, ratios, model_err, naive_err = best

    point, baseline, growth, years, same_month = _point(usable, target, as_of, recent_months, alpha)
    q10, q50, q90 = ((_quantile(ratios, q) for q in (0.1, 0.5, 0.9)) if ratios else (1.0, 1.0, 1.0))
    if len(ratios) >= _MIN_RATIOS:
        p10, p50, p90 = sorted(max(0, round(point * q)) for q in (q10, q50, q90))
    else:  # historial corto o intermitente: la dispersión de los mismos meses previos, escalada por el crecimiento
        past = sorted(same_month)
        p10, p50, p90 = (max(0, round(_quantile(past, q) * growth)) for q in (0.1, 0.5, 0.9))
    coverage = sum(q10 <= r <= q90 for r in ratios) / len(ratios) if ratios else 0.0
    return Forecast(origin, destination, target, p10, p50, p90, baseline, growth, years,
                    mae=statistics.fmean(model_err) if model_err else 0.0,
                    naive_mae=statistics.fmean(naive_err) if naive_err else 0.0,
                    coverage=coverage, n_backtest=len(model_err), alpha=alpha)
