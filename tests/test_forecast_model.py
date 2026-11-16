import random
from datetime import date

import pytest

from form_agent.forecast.model import Forecast, InsufficientHistory, add_months, forecast_lane

AS_OF = date(2026, 11, 1)
DEC = date(2026, 12, 1)


def series(f, start=date(2023, 11, 1), n=36):
    months = [add_months(start, i) for i in range(n)]
    return {m: f(m) for m in months}


def run(history, target=DEC, as_of=AS_OF) -> Forecast:
    return forecast_lane(history, "CLSAI", "CNSHA", target, as_of)


def test_flat_history_forecasts_the_same_value():
    f = run(series(lambda m: 100))
    assert f.p50 == 100 and f.growth == pytest.approx(1.0) and f.p10 <= f.p50 <= f.p90


def test_seasonal_pattern_is_reproduced():
    f = run(series(lambda m: 300 if m.month == 12 else 100))
    assert 285 <= f.p50 <= 315


def test_growth_factor_scales_forecast():
    f = run(series(lambda m: 150 if m >= date(2026, 8, 1) else 100))
    assert f.growth == pytest.approx(1.5) and f.p50 == 150


def test_quantiles_are_monotonic_non_negative_ints():
    rng = random.Random("q")
    f = run(series(lambda m: int(100 * (1.6 if m.month == 12 else 1) * rng.uniform(0.7, 1.3))))
    assert all(isinstance(v, int) and v >= 0 for v in (f.p10, f.p50, f.p90))
    assert f.p10 <= f.p50 <= f.p90 and f.p10 < f.p90


def test_all_zero_history_returns_zeros_without_error():
    f = run(series(lambda m: 0))
    assert (f.p10, f.p50, f.p90) == (0, 0, 0) and f.growth == 1.0


def test_raises_insufficient_history_without_prior_same_month():
    with pytest.raises(InsufficientHistory):
        run(series(lambda m: 100, start=date(2026, 5, 1), n=6))


def test_year_wrap_target_january_uses_sep_to_nov_window():
    h = series(lambda m: 200 if m >= date(2026, 10, 1) else 100, start=date(2023, 12, 1))
    f = forecast_lane(h, "CLSAI", "CNSHA", date(2027, 1, 1), date(2026, 12, 1))
    assert f.growth > 1.5 and f.baseline == pytest.approx(100)


def test_add_months_handles_year_boundaries():
    assert add_months(date(2026, 11, 1), 3) == date(2027, 2, 1)
    assert add_months(date(2026, 11, 1), -12) == date(2025, 11, 1)
    assert add_months(date(2026, 11, 1), 0) == date(2026, 11, 1)
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_beats_naive_on_seasonal_growing_series():
    season = {12: 1.6, 11: 1.25, 2: 0.7}
    start = date(2023, 11, 1)

    def f(m):
        idx = (m.year - start.year) * 12 + m.month - start.month
        return round(100 * season.get(m.month, 1.0) * 1.08 ** (idx / 12) * random.Random(str(m)).uniform(0.95, 1.05))

    fc = run(series(f))
    assert fc.n_backtest > 10 and fc.mae < fc.naive_mae


def test_intermittent_history_does_not_collapse_quantiles_into_a_buy_everything_forecast():
    # solo dic-2025 tuvo envíos: dos de tres diciembres fueron 0, así que P10 y P50 no pueden ser 17
    h = series(lambda m: 50 if m == date(2025, 12, 1) else 0)
    f = run(h)
    assert (f.p10, f.p50) == (0, 0) and f.p90 > 0


def test_strongly_seasonal_series_keeps_using_the_same_month_of_previous_years():
    f = run(series(lambda m: 300 if m.month == 12 else 100))
    assert f.alpha == 1.0
