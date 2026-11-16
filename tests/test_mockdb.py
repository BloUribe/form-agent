import sqlite3
from datetime import date, timedelta

import pytest

from form_agent.freight.carriers.mockdb import MockDBRateProvider, MockDBScheduleProvider, ensure_mock_db
from form_agent.freight.models import ShipmentRequest
from form_agent.freight.service import find_options

TODAY = date(2026, 11, 16)


def rows(path, sql, *args):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "mock.sqlite"
    ensure_mock_db(path, today=TODAY)
    return path


def request(**over):
    base = dict(origin_port="CLSAI", destination_port="CNSHA", container_count=2, container_type="40HC",
                departure_date=TODAY + timedelta(days=10))
    return ShipmentRequest(**{**base, **over})


def test_sailings_span_from_today_to_six_months_ahead(db):
    lo, hi = rows(db, "SELECT MIN(etd), MAX(etd) FROM sailings")[0]
    assert date.fromisoformat(lo) >= TODAY and date.fromisoformat(lo) <= TODAY + timedelta(days=7)
    assert date(2027, 5, 1) <= date.fromisoformat(hi) <= date(2027, 5, 16)


def test_each_lane_has_a_weekly_departure_for_about_26_weeks(db):
    (n,) = rows(db, "SELECT COUNT(*) FROM sailings WHERE origin='CLSAI' AND destination='CNSHA'")[0]
    assert 25 <= n <= 27


def test_lanes_exist_in_both_directions(db):
    assert rows(db, "SELECT COUNT(*) FROM sailings WHERE origin='CNSHA' AND destination='CLSAI'")[0][0] > 0


def test_arrival_is_after_departure_and_free_capacity_is_non_negative(db):
    assert rows(db, "SELECT COUNT(*) FROM sailings WHERE eta <= etd OR free_teu < 0")[0][0] == 0


def test_build_is_deterministic(tmp_path):
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    ensure_mock_db(a, today=TODAY)
    ensure_mock_db(b, today=TODAY)
    q = "SELECT vessel_imo, voyage, origin, destination, etd, eta, free_teu, price_40hc FROM sailings ORDER BY id"
    assert rows(a, q) == rows(b, q)


def test_rebuilds_on_a_new_day_and_keeps_data_within_the_day(db):
    before = rows(db, "SELECT free_teu FROM sailings ORDER BY id LIMIT 5")
    ensure_mock_db(db, today=TODAY)  # mismo día: no cambia
    assert rows(db, "SELECT free_teu FROM sailings ORDER BY id LIMIT 5") == before
    ensure_mock_db(db, today=TODAY + timedelta(days=40))
    assert date.fromisoformat(rows(db, "SELECT MIN(etd) FROM sailings")[0][0]) >= TODAY + timedelta(days=40)


def test_schedule_provider_returns_only_the_lane_inside_the_window_sorted(db):
    req = request()
    sailings = MockDBScheduleProvider(db, today=TODAY).search(req)
    assert sailings and all(s.etd >= req.departure_date for s in sailings)
    assert all(s.etd <= req.departure_date + timedelta(days=21) for s in sailings)
    assert [s.etd for s in sailings] == sorted(s.etd for s in sailings)
    assert all(s.ref for s in sailings) and all(s.vessel_imo for s in sailings)


def test_schedule_provider_returns_nothing_for_an_unknown_lane(db):
    assert MockDBScheduleProvider(db, today=TODAY).search(request(origin_port="ZZZZZ")) == []


def test_schedule_provider_finds_nothing_beyond_the_six_month_horizon(db):
    assert MockDBScheduleProvider(db, today=TODAY).search(request(departure_date=date(2027, 9, 1))) == []


def test_quote_uses_the_price_for_the_container_type_and_reports_free_capacity(db):
    req = request(container_type="40HC")
    s = MockDBScheduleProvider(db, today=TODAY).search(req)[0]
    (price, free) = rows(db, "SELECT price_40hc, free_teu FROM sailings WHERE ref=?", s.ref)[0]
    q = MockDBRateProvider(db).quote(req, s)
    assert q.price_per_container == pytest.approx(price) and q.currency == "USD"
    assert f"{free} TEU" in q.availability
    assert q.free_teu == free


def test_quote_flags_insufficient_capacity(db):
    req = request(container_count=2, container_type="40HC")  # 4 TEU
    s = MockDBScheduleProvider(db, today=TODAY).search(req)[0]
    con = sqlite3.connect(db)
    con.execute("UPDATE sailings SET free_teu=1 WHERE ref=?", (s.ref,))
    con.commit()
    con.close()
    assert "SIN CAPACIDAD" in MockDBRateProvider(db).quote(req, s).availability


def test_quote_is_none_for_a_sailing_not_in_the_db(db):
    s = MockDBScheduleProvider(db, today=TODAY).search(request())[0].model_copy(update={"ref": "nope"})
    assert MockDBRateProvider(db).quote(request(), s) is None


def test_prices_differ_between_container_types(db):
    s = MockDBScheduleProvider(db, today=TODAY).search(request())[0]
    p = {t: MockDBRateProvider(db).quote(request(container_type=t), s).price_per_container for t in ("20DRY", "40DRY", "40HC")}
    assert p["20DRY"] < p["40DRY"] < p["40HC"]


def test_end_to_end_with_find_options(db):
    req = request()
    opts = find_options(req, MockDBScheduleProvider(db, today=TODAY), MockDBRateProvider(db))
    assert opts and all(o.total_price for o in opts) and [o.id for o in opts] == list(range(1, len(opts) + 1))


def test_rebuilds_when_the_cached_database_comes_from_an_older_generator(db):
    con = sqlite3.connect(db)  # misma fecha, marca sin versión, datos viejos (sin las rutas nuevas)
    con.execute("UPDATE meta SET value=? WHERE key='built_on'", (TODAY.isoformat(),))
    con.execute("DELETE FROM sailings")
    con.commit()
    con.close()
    ensure_mock_db(db, today=TODAY)
    assert rows(db, "SELECT COUNT(*) FROM sailings WHERE origin='USMIA' AND destination='CLSAI'")[0][0] > 20
