import sqlite3
from datetime import date
from statistics import fmean

from form_agent.freight.carriers.mockdb import lane_pairs
from form_agent.history.mockdb import CUSTOMER_LANES, ensure_history_db, list_lanes, load_history

TODAY = date(2026, 11, 16)


def build(tmp_path, today=TODAY):
    path = tmp_path / "history.sqlite"
    ensure_history_db(path, today=today)
    return path


def test_customer_ships_from_miami_to_chile_on_lanes_that_have_sailings():
    assert ("USMIA", "CLSAI") in CUSTOMER_LANES
    assert all(lane in lane_pairs() for lane in CUSTOMER_LANES)


def test_has_36_complete_months_before_today_for_every_customer_lane(tmp_path):
    path = build(tmp_path)
    assert sorted(list_lanes(path)) == sorted(CUSTOMER_LANES)
    for origin, dest in CUSTOMER_LANES:
        h = load_history(path, origin, dest)
        assert len(h) == 36
        assert min(h) == date(2023, 11, 1) and max(h) == date(2026, 10, 1)


def test_average_is_about_77_containers_per_month(tmp_path):
    h = load_history(build(tmp_path), *CUSTOMER_LANES[0])
    assert 65 <= fmean(h.values()) <= 90


def test_volume_is_volatile_but_bounded(tmp_path):
    h = load_history(build(tmp_path), *CUSTOMER_LANES[0])
    assert 10 <= min(h.values()) and max(h.values()) <= 200
    assert max(h.values()) - min(h.values()) >= 60  # un cliente real no manda siempre lo mismo


def test_is_deterministic(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a, b = build(tmp_path / "a"), build(tmp_path / "b")
    assert load_history(a, *CUSTOMER_LANES[0]) == load_history(b, *CUSTOMER_LANES[0])


def test_rebuilds_on_new_month_keeping_36_months(tmp_path):
    path = build(tmp_path)
    ensure_history_db(path, today=date(2026, 12, 2))
    h = load_history(path, *CUSTOMER_LANES[0])
    assert len(h) == 36 and max(h) == date(2026, 11, 1) and min(h) == date(2023, 12, 1)


def test_same_month_does_not_rebuild(tmp_path):
    path = build(tmp_path)
    before = load_history(path, *CUSTOMER_LANES[0])
    ensure_history_db(path, today=date(2026, 11, 30))
    assert load_history(path, *CUSTOMER_LANES[0]) == before


def test_volumes_are_non_negative_integers(tmp_path):
    h = load_history(build(tmp_path), *CUSTOMER_LANES[0])
    assert all(isinstance(v, int) and v >= 0 for v in h.values())


def test_rebuilds_when_the_cached_database_comes_from_an_older_generator(tmp_path):
    path = build(tmp_path)
    con = sqlite3.connect(path)  # simula una BD del generador anterior: mismo mes, marca sin versión, datos viejos
    con.execute("UPDATE meta SET value='2026-11' WHERE key='built_on'")
    con.execute("DELETE FROM shipments")
    con.commit()
    con.close()
    ensure_history_db(path, today=TODAY)
    assert len(load_history(path, *CUSTOMER_LANES[0])) == 36
