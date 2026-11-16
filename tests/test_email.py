from form_agent.config import Settings
from form_agent.email import build_html, estimate_cost, parse_final


def test_parse_final_fenced_and_bare():
    assert parse_final('hola\n```json\n{"submitted": true}\n```')["submitted"] is True
    assert parse_final('{"submitted": false}')["submitted"] is False
    assert "raw" in parse_final("sin json")


def test_html_escapes_and_shows_status():
    rep = {"filled": {"name": "<b>x</b>"}, "skipped": ["a"], "submitted": True, "confirmation": "Received!"}
    h = build_html(rep, {"steps": 3, "seconds": 1.0}, "http://x", 0.01, dry_run=False)
    assert "&lt;b&gt;" in h and "<b>x</b>" not in h and "Enviado" in h and "Received!" in h


def test_cost():
    s = Settings(price_in_per_mtok=3, price_out_per_mtok=15)
    assert estimate_cost({"input_tokens": 1_000_000, "output_tokens": 1_000_000}, s) == 18
