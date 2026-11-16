import sqlite3
from datetime import date

import pytest
from langchain_core.messages import AIMessage

from form_agent.config import Settings
from form_agent.freight.carriers.mockdb import MockDBRateProvider, MockDBScheduleProvider
from form_agent.history.mockdb import ensure_history_db
from form_agent.report import monthly

TODAY = date(2026, 11, 16)


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, history_db_path=str(tmp_path / "h.sqlite"), mock_db_path=str(tmp_path / "m.sqlite"),
                    report_dir=str(tmp_path / "reports"), resend_api_key="x", email_to="a@b.c")


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(monthly, "send_message",
                        lambda s, subject, body, attachments=None, to=None: calls.append(dict(subject=subject, body=body, files=attachments, to=to)) or "id")
    return calls


def providers(settings):
    return MockDBScheduleProvider(settings.mock_db_path, today=TODAY), MockDBRateProvider(settings.mock_db_path)


def run(settings, **kw):
    schedules, rates = providers(settings)
    return monthly.run_monthly_report(settings, today=TODAY, schedules=schedules, rates=rates, **kw)


class Capture:
    def __init__(self):
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return AIMessage(content="Resumen")


def test_run_creates_pdf_named_after_target_month(settings, sent):
    path = run(settings, send=False)
    assert path.name == "monthly-2026-12.pdf" and path.read_bytes().startswith(b"%PDF")


def test_run_sends_one_email_with_pdf_attached_to_email_to(settings, sent):
    path = run(settings)
    assert len(sent) == 1 and sent[0]["files"] == [path] and sent[0]["to"] is None
    assert "Diciembre 2026" in sent[0]["subject"]


def test_run_with_send_false_does_not_email(settings, sent):
    run(settings, send=False)
    assert sent == []


def test_without_email_config_only_saves_pdf(settings, sent):
    settings.resend_api_key = ""
    assert run(settings).exists() and sent == []


def test_run_keeps_pdf_and_main_returns_1_when_resend_fails(settings, monkeypatch, tmp_path, capsys):
    def boom(*a, **k):
        raise RuntimeError("resend caido")

    monkeypatch.setattr(monthly, "send_message", boom)
    with pytest.raises(RuntimeError, match="monthly-2026-12.pdf"):
        run(settings)
    assert (tmp_path / "reports" / "monthly-2026-12.pdf").exists()
    assert monthly.main(["--today", "2026-11-16", "--no-llm"], settings=settings) == 1
    assert "resend caido" in capsys.readouterr().err


def test_lanes_without_history_are_skipped_not_fatal(settings, sent):
    ensure_history_db(settings.history_db_path, today=TODAY)
    con = sqlite3.connect(settings.history_db_path)
    con.execute("DELETE FROM shipments WHERE origin='USMIA' AND destination='CLSAI' AND month < '2026-05-01'")
    con.commit()
    con.close()
    model = Capture()
    assert run(settings, send=False, model=model).exists()
    assert "USMIA-CLSAI" in model.prompts[0]


def test_target_flag_overrides_default(settings, sent, tmp_path):
    assert monthly.main(["--target", "2027-01", "--no-email", "--no-llm", "--today", "2026-11-16"], settings=settings) == 0
    assert (tmp_path / "reports" / "monthly-2027-01.pdf").exists()


def test_no_llm_flag_never_builds_the_language_model(settings, sent, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe crear el modelo")

    monkeypatch.setattr(monthly, "ChatAnthropic", boom)
    settings.anthropic_api_key = "k"
    assert monthly.main(["--no-email", "--no-llm", "--today", "2026-11-16"], settings=settings) == 0


def test_report_date_shown_is_the_run_date_not_the_first_of_the_month(settings, sent):
    model = Capture()
    run(settings, send=False, model=model)
    assert "16/11/2026" in model.prompts[0] and "01/11/2026" not in model.prompts[0]


@pytest.mark.parametrize("target", [date(2026, 11, 1), date(2027, 6, 1)])
def test_target_outside_one_to_six_months_is_rejected(settings, sent, target):
    with pytest.raises(ValueError, match="entre 1 y 6 meses"):
        run(settings, send=False, target=target)


def test_main_returns_1_with_message_for_target_beyond_horizon(settings, sent, capsys):
    assert monthly.main(["--target", "2027-06", "--no-llm", "--no-email", "--today", "2026-11-16"], settings=settings) == 1
    assert "entre 1 y 6 meses" in capsys.readouterr().err


def test_skipped_routes_are_passed_to_the_pdf(settings, sent, monkeypatch):
    ensure_history_db(settings.history_db_path, today=TODAY)
    con = sqlite3.connect(settings.history_db_path)
    con.execute("DELETE FROM shipments WHERE origin='USMIA' AND destination='CLSAI' AND month < '2026-05-01'")
    con.commit()
    con.close()
    seen = {}
    original = monthly.build_pdf
    monkeypatch.setattr(monthly, "build_pdf", lambda *a, **k: seen.update(k) or original(*a, **k))
    run(settings, send=False)
    assert seen["skipped"] == ["USMIA-CLSAI"]


def test_missing_email_config_warns_on_stderr_instead_of_silently_skipping(settings, sent, capsys):
    settings.resend_api_key = ""
    path = run(settings)
    err = capsys.readouterr().err
    assert "no se envio" in err and str(path) in err


def test_customer_history_is_passed_to_the_pdf_for_the_chart(settings, sent, monkeypatch):
    seen = {}
    original = monthly.build_pdf
    monkeypatch.setattr(monthly, "build_pdf", lambda *a, **k: seen.update(k) or original(*a, **k))
    run(settings, send=False)
    hist = seen["histories"][("USMIA", "CLSAI")]
    assert len(hist) == 36 and all(isinstance(v, int) for v in hist.values())


def test_email_body_is_branded_and_lists_the_three_tiers_per_route(settings, sent):
    run(settings)
    body = sent[0]["body"]
    assert "Interworld Freight" in body and "Diciembre 2026" in body
    assert "Miami (USMIA)" in body and "San Antonio (CLSAI)" in body
    assert all(w in body for w in ("COMPRAR", "PREPARAR", "VIGILAR"))
