import re
from datetime import date

from form_agent.dates import add_months
from form_agent.forecast.model import Forecast
from form_agent.forecast.plan import Plan, Recommendation, Unplaced
from form_agent.report.pdf import build_pdf, latin1

AS_OF, TARGET = date(2026, 11, 16), date(2026, 12, 1)
HISTORY = {add_months(date(2025, 11, 1), i): 55 + (i * 7) % 40 for i in range(12)}


def rec(tier="buy", vessel="MOCK FJORD", origin="USMIA", dest="CLSAI", containers=15, day=3):
    return Recommendation(tier, origin, dest, f"r{day}", vessel, "105E", date(2026, 12, day), containers, 2400.0, "USD", -8.0)


def forecast(origin="USMIA", dest="CLSAI", p10=38, p50=91, p90=138):
    return Forecast(origin, dest, TARGET, p10, p50, p90, baseline=80.0, growth=1.05, years_used=3, mae=26.0,
                    naive_mae=41.0, coverage=0.8, n_backtest=24, alpha=0.0)


def render(tmp_path, plan, forecasts=(), narrative="Resumen.", compress=False, histories=None, skipped=None):
    return build_pdf(plan, list(forecasts), narrative, AS_OF, TARGET, tmp_path / "out.pdf", compress=compress,
                     skipped=skipped, histories=histories)


def pages(data: bytes) -> int:
    return len(re.findall(rb"/Type /Page(?!s)", data))


def standard_plan():
    recs = [rec("buy", day=d, containers=c) for d, c in ((3, 12), (10, 14), (17, 12))]
    recs += [rec("prepare", day=d, containers=c) for d, c in ((10, 18), (17, 18), (24, 17))]
    recs += [rec("watch", day=d, containers=c) for d, c in ((17, 15), (24, 16), (31, 16))]
    return Plan(recs, [])


def test_creates_a_valid_pdf_file(tmp_path):
    path = render(tmp_path, standard_plan(), [forecast()], compress=True, histories={("USMIA", "CLSAI"): HISTORY})
    data = path.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 5000


def test_shows_brand_route_tiers_vessel_and_forecast_numbers(tmp_path):
    data = render(tmp_path, standard_plan(), [forecast()], histories={("USMIA", "CLSAI"): HISTORY}).read_bytes()
    for needle in (b"Interworld Freight", b"Miami", b"San Antonio", b"COMPRAR", b"PREPARAR", b"VIGILAR",
                   b"MOCK FJORD", b"Diciembre 2026", b"138", b"91"):
        assert needle in data, needle


def test_standard_scenario_fits_in_two_pages(tmp_path):
    data = render(tmp_path, standard_plan(), [forecast()], histories={("USMIA", "CLSAI"): HISTORY}).read_bytes()
    assert pages(data) <= 2


def test_chart_is_drawn_when_history_is_available(tmp_path):
    with_hist = render(tmp_path, standard_plan(), [forecast()], histories={("USMIA", "CLSAI"): HISTORY}).read_bytes()
    assert b"Contenedores por mes" in with_hist


def test_chart_copes_with_short_history_and_zero_volumes(tmp_path):
    short = {add_months(date(2026, 8, 1), i): 0 for i in range(3)}
    path = render(tmp_path, standard_plan(), [forecast(p10=0, p50=0, p90=0)], histories={("USMIA", "CLSAI"): short})
    assert path.read_bytes().startswith(b"%PDF")


def test_each_lane_gets_its_own_page(tmp_path):
    plan = Plan([rec("buy", origin="USMIA", dest="CLSAI"), rec("buy", origin="USMIA", dest="CLVAP", vessel="MOCK ATLAS")], [])
    data = render(tmp_path, plan, [forecast(), forecast(dest="CLVAP")]).read_bytes()
    assert pages(data) >= 2 and b"Valpara" in data and b"MOCK ATLAS" in data


def test_empty_plan_and_no_forecast_still_render(tmp_path):
    data = render(tmp_path, Plan([], [])).read_bytes()
    assert data.startswith(b"%PDF") and b"Sin pron" in data


def test_lane_without_recommendations_says_so(tmp_path):
    data = render(tmp_path, Plan([], []), [forecast()]).read_bytes()
    assert b"Sin salidas recomendadas" in data


def test_non_latin1_text_does_not_crash(tmp_path):
    path = render(tmp_path, Plan([rec(vessel="MOCK → NOVA")], []), [forecast()],
                  narrative="Subir → 2.5 «bien» ≥ 10 ☃")
    assert path.read_bytes().startswith(b"%PDF")


def test_unplaced_section_is_listed_with_reason(tmp_path):
    plan = Plan([], [Unplaced("buy", "USMIA", "CLSAI", 7, "capacidad libre insuficiente")])
    data = render(tmp_path, plan, [forecast()]).read_bytes()
    assert b"Sin colocar" in data and b"capacidad libre insuficiente" in data


def test_skipped_routes_are_listed_in_the_pdf(tmp_path):
    data = render(tmp_path, Plan([], []), skipped=["PECLL-CNSHA"]).read_bytes()
    assert b"omitidas" in data and b"PECLL-CNSHA" in data


def test_latin1_replaces_unencodable_characters():
    assert latin1("Subir → 2.5 ≥ 10 ☃") == "Subir -> 2.5 >= 10 ?"
    assert latin1("año «x»") == "año «x»"


LONG_NARRATIVE = ("Para el pre-booking de 12/2026 (informe del 16/11/2026), la ruta principal es Miami a San Antonio, con una demanda "
                  "estimada de 38 contenedores en P10, 91 en P50 y 138 en P90. Recomendamos comprar ya 38 contenedores en 2 salidas, el "
                  "volumen con poco riesgo de quedar sin usar (P10). También conviene preparar 53 contenedores en 2 salidas (P50) y vigilar "
                  "47 contenedores en otras 2 salidas (P90), a la espera de que la demanda confirme esos escenarios. El precio medio de la "
                  "propuesta queda un 2,0 % por debajo del promedio de la ruta. No hay contenedores sin colocar ni rutas omitidas.")


def test_standard_scenario_with_a_long_summary_still_fits_in_one_page(tmp_path):
    plan = Plan([rec("buy", day=d) for d in (3, 24)] + [rec("prepare", day=d) for d in (3, 24)] + [rec("watch", day=d) for d in (3, 24)], [])
    data = render(tmp_path, plan, [forecast()], narrative=LONG_NARRATIVE, histories={("USMIA", "CLSAI"): HISTORY}).read_bytes()
    assert pages(data) == 1
