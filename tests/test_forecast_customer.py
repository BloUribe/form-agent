"""El modelo sobre el cliente simulado (~77 contenedores/mes, mucha variación): el pronóstico debe ser creíble."""
from datetime import date

import pytest

from form_agent.forecast.model import forecast_lane
from form_agent.history.mockdb import CUSTOMER_LANES, ensure_history_db, load_history

TODAY = date(2026, 11, 16)
AS_OF = date(2026, 11, 1)


@pytest.fixture
def history(tmp_path):
    path = tmp_path / "h.sqlite"
    ensure_history_db(path, today=TODAY)
    return load_history(path, *CUSTOMER_LANES[0])


@pytest.mark.parametrize("target", [date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)])
def test_forecast_for_the_customer_is_credible_and_beats_naive(history, target):
    f = forecast_lane(history, *CUSTOMER_LANES[0], target, AS_OF)
    assert 60 <= f.p50 <= 110          # alrededor de los ~77 habituales (más la temporada)
    assert 25 <= f.p10 <= 50           # un mes flojo (~30-40), no cero
    assert f.p90 <= 160                # un mes alto, no el doble del habitual
    assert f.p10 < f.p50 < f.p90
    assert f.mae <= f.naive_mae
