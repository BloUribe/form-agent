from form_agent.config import Settings
from form_agent.freight.carriers.hapag import HapagScheduleProvider
from form_agent.freight.carriers.mock import MockRateProvider
from form_agent.freight.carriers.mockdb import MockDBRateProvider, MockDBScheduleProvider
from form_agent.freight.providers import build_providers


def settings(tmp_path, **kw):
    return Settings(_env_file=None, mock_db_path=str(tmp_path / "mock.sqlite"), **kw)


def test_without_credentials_uses_the_mock_database_for_schedules_and_rates(tmp_path):
    schedules, rates = build_providers(settings(tmp_path))
    assert isinstance(schedules, MockDBScheduleProvider) and isinstance(rates, MockDBRateProvider)


def test_partial_hapag_config_falls_back_to_the_mock_database(tmp_path):
    schedules, _ = build_providers(settings(tmp_path, hapag_client_id="id", hapag_client_secret="s"))  # falta base_url
    assert isinstance(schedules, MockDBScheduleProvider)


def test_full_hapag_config_uses_real_schedules_with_generic_mock_prices(tmp_path):
    s = settings(tmp_path, hapag_base_url="https://sandbox.example/v1", hapag_client_id="id", hapag_client_secret="s")
    schedules, rates = build_providers(s)
    assert isinstance(schedules, HapagScheduleProvider)
    # los horarios reales no existen en la BD simulada, así que el precio no puede salir de ella
    assert isinstance(rates, MockRateProvider)
