from collections import defaultdict
from datetime import date, timedelta

import pytest

from form_agent.forecast.model import Forecast
from form_agent.forecast.plan import build_plan, month_sailings
from form_agent.freight.carriers.mockdb import MockDBRateProvider, MockDBScheduleProvider
from form_agent.freight.models import Quote, Sailing

MONTH = date(2026, 12, 1)
LANE = ("CLSAI", "CNSHA")


def sailing(ref, etd):
    return Sailing(carrier="T", vessel_name=f"SHIP-{ref}", voyage="1E", etd=etd, ref=ref)


class FakeSchedules:
    def __init__(self, sailings):
        self.sailings = sailings

    def search(self, request):
        lo, hi = request.departure_date, request.departure_date + timedelta(days=21)
        return [s for s in self.sailings if lo <= s.etd <= hi and (request.origin_port, request.destination_port) == LANE]


class FakeRates:
    def __init__(self, prices, free_teu=None):
        self.prices, self.free_teu = prices, free_teu

    def quote(self, request, sailing):
        return Quote(price_per_container=self.prices[sailing.ref], free_teu=self.free_teu)


def providers(free_teu=None, with_sailings=True):
    sailings = [sailing("a", date(2026, 12, 3)), sailing("b", date(2026, 12, 10)), sailing("c", date(2026, 12, 17))]
    return FakeSchedules(sailings if with_sailings else []), FakeRates({"a": 100.0, "b": 120.0, "c": 140.0}, free_teu)


def fc(p10, p50, p90):
    return Forecast(*LANE, MONTH, p10, p50, p90, baseline=0.0, growth=1.0, years_used=3, mae=0.0, naive_mae=0.0,
                    coverage=0.8, n_backtest=10)


def by_tier(plan):
    out = defaultdict(list)
    for r in plan.recommendations:
        out[r.tier].append((r.ref, r.containers))
    return out


def test_buy_tier_goes_to_cheapest_sailing_first_up_to_max_share():
    plan = build_plan([fc(10, 10, 10)], *providers())
    assert by_tier(plan)["buy"] == [("a", 5), ("b", 5)]


def test_tiers_split_p10_p50_p90_amounts():
    plan = build_plan([fc(10, 30, 50)], *providers())
    totals = {t: sum(c for _, c in rows) for t, rows in by_tier(plan).items()}
    assert totals == {"buy": 10, "prepare": 20, "watch": 20} and plan.unplaced == []


def test_never_exceeds_free_capacity_shared_across_tiers():
    plan = build_plan([fc(10, 30, 50)], *providers(free_teu=8))  # 40HC = 2 TEU -> 4 contenedores por salida
    per_sailing = defaultdict(int)
    for r in plan.recommendations:
        per_sailing[r.ref] += r.containers
    assert per_sailing and all(v <= 4 for v in per_sailing.values())
    assert plan.unplaced


def test_no_sailings_in_month_goes_to_unplaced_with_reason():
    plan = build_plan([fc(10, 30, 50)], *providers(with_sailings=False))
    assert plan.recommendations == []
    assert {u.tier for u in plan.unplaced} == {"buy", "prepare", "watch"}
    assert all("sin salidas" in u.reason for u in plan.unplaced)


def test_insufficient_capacity_reports_remainder_as_unplaced():
    plan = build_plan([fc(10, 10, 10)], *providers(free_teu=2), max_share=1.0)  # 1 contenedor por salida
    assert sum(c for _, c in by_tier(plan)["buy"]) == 3
    (u,) = plan.unplaced
    assert (u.tier, u.containers) == ("buy", 7) and "capacidad" in u.reason


def test_zero_forecast_yields_no_recommendations_and_no_unplaced():
    plan = build_plan([fc(0, 0, 0)], *providers())
    assert plan.recommendations == [] and plan.unplaced == []


def test_vs_avg_pct_is_negative_for_cheapest_sailing():
    plan = build_plan([fc(10, 10, 10)], *providers())
    cheapest = next(r for r in plan.recommendations if r.ref == "a")
    assert cheapest.vs_avg_pct == pytest.approx((100 / 120 - 1) * 100)


def test_month_sailings_dedupes_and_stays_inside_target_month(tmp_path):
    path = tmp_path / "mock.sqlite"
    found = month_sailings("CLSAI", "CNSHA", MONTH, MockDBScheduleProvider(path, today=date(2026, 11, 16)),
                           MockDBRateProvider(path), "40HC")
    refs = [s.ref for s, _ in found]
    assert len(refs) >= 3 and len(refs) == len(set(refs))
    assert all(MONTH <= s.etd < date(2027, 1, 1) for s, _ in found)


def test_share_limit_remainder_is_reported_as_share_limit_not_capacity():
    one = FakeSchedules([sailing("a", date(2026, 12, 3))])
    plan = build_plan([fc(10, 10, 10)], one, FakeRates({"a": 100.0}, free_teu=None))
    (u,) = plan.unplaced
    assert u.containers == 5 and "reparto" in u.reason and "capacidad" not in u.reason
