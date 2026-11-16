# Informe mensual de pre-booking (forecast P10/P50/P90) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un comando que genera el informe mensual (PDF) con el forecast de contenedores por ruta y las salidas recomendadas a comprar (P10), preparar (P50) y vigilar (P90), y lo envía por correo.

**Architecture:** Historial simulado en SQLite, modelo de forecast en Python puro (estacional del mismo mes de años previos × factor de crecimiento reciente, cuantiles de errores de backtest), un asignador que reparte contenedores entre las salidas del mes siguiente usando los `ScheduleProvider`/`RateProvider` existentes, un generador de PDF y un orquestador con CLI.

**Tech Stack:** Python 3.12, SQLite, `fpdf2` (única dependencia nueva), pytest, Resend (existente), Claude solo para el texto del resumen.

**Spec:** `docs/superpowers/specs/2026-11-16-monthly-forecast-report-design.md`

## Global Constraints

- Modelo en Python puro: sin numpy, pandas, scipy ni scikit-learn. Única dependencia nueva: `fpdf2`.
- Historial: 36 meses completos anteriores a la fecha del informe, por ruta (origen, destino), con las mismas rutas que `carriers/mockdb.py`.
- P10 = volumen que se supera el 90 % de las veces → nivel `buy`. P50 → `prepare` (de P10 a P50). P90 → `watch` (de P50 a P90). Siempre P10 ≤ P50 ≤ P90, enteros ≥ 0.
- Horizonte por defecto: el mes calendario siguiente a la fecha del informe; configurable con `--target YYYY-MM` hasta 6 meses.
- Los números los calcula código determinista; Claude solo redacta el resumen y, si falla o no hay clave, se usa una plantilla.
- Máximo 50 % del volumen de un nivel y ruta en una sola salida (`max_share=0.5`). Nunca superar los TEU libres de una salida.
- PDF con fuentes base (Helvetica): todo texto debe ser Latin-1; los caracteres fuera se reemplazan, nunca rompen.
- Texto para el usuario en español. Sin reservas reales. Pruebas con `uv run pytest`.
- Los pasos de commit solo se ejecutan si Pablo pidió commits; el mensaje termina con `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- Ruta sin historial del mes objetivo en años previos → se omite con aviso en el informe, no rompe (Task 2 y 6).
- Ruta con todos los volúmenes en cero → P10=P50=P90=0, sin recomendaciones ni división por cero (Task 2).
- Sin salidas en el mes objetivo, o capacidad libre insuficiente → el faltante aparece como `unplaced` con motivo, no se pierde en silencio (Task 3).
- Falla del modelo de lenguaje o de Resend → el PDF igual se guarda en disco; el resumen cae a plantilla (Task 5 y 6).
- Texto con caracteres no Latin-1 (flechas, comillas tipográficas) en el PDF → no lanza excepción (Task 4).
- Cambio de año (objetivo enero, ventana oct-dic) calcula bien los meses (Task 2).

---

### Task 1: Historial simulado de envíos

**Files:**
- Modify: `src/form_agent/freight/carriers/mockdb.py` (agregar `lane_pairs`)
- Create: `src/form_agent/history/__init__.py`, `src/form_agent/history/mockdb.py`
- Modify: `src/form_agent/config.py` (`history_db_path: str = "artifacts/mock_history.sqlite"`, `report_dir: str = "artifacts/reports"`)
- Test: `tests/test_history_mockdb.py`

**Interfaces:**
- Produces: `lane_pairs() -> list[tuple[str, str]]` (las 20 rutas de `_LANES`, en orden);
  `ensure_history_db(path: str | Path, today: date | None = None) -> None`;
  `list_lanes(path: str | Path) -> list[tuple[str, str]]`;
  `load_history(path: str | Path, origin: str, destination: str) -> dict[date, int]` (clave = primer día del mes, valor = contenedores).

- [ ] **Step 1: Write the failing tests** en `tests/test_history_mockdb.py` con `TODAY = date(2026, 11, 16)`:
  `test_has_36_complete_months_before_today_for_every_lane` (cada ruta de `lane_pairs()` tiene exactamente 36 claves, la menor `date(2023, 11, 1)`, la mayor `date(2026, 10, 1)`);
  `test_december_peak_and_growth` (promedio de diciembres > 1.3 × promedio de abril para el total de rutas; total 2025 > total 2023 de los meses comunes);
  `test_is_deterministic` (dos BD con el mismo `today` dan el mismo `load_history`);
  `test_rebuilds_on_new_month_keeping_36_months` (con `today=date(2026, 12, 2)` la mayor clave es `date(2026, 11, 1)` y siguen siendo 36);
  `test_volumes_are_non_negative_integers`.
- [ ] **Step 2: Run** `uv run pytest tests/test_history_mockdb.py -q` → FAIL (`ModuleNotFoundError: form_agent.history`).
- [ ] **Step 3: Implement** `lane_pairs` (derivado de `_LANES`) y `history/mockdb.py`. Tabla `shipments(month TEXT, origin TEXT, destination TEXT, containers INTEGER, PRIMARY KEY(month, origin, destination))` + tabla `meta(built_on)` como en `carriers/mockdb.ensure_mock_db` (reconstruye si `built_on` ≠ mes de `today`). Volumen = base de la ruta (80 a 400) × estacionalidad (diciembre ×1.5, noviembre ×1.25, febrero ×0.7, resto ≈1) × crecimiento (≈ +8 % anual) × ruido, con `random.Random(f"{origin}-{dest}-{month}")` para ser determinista; redondear a entero ≥ 0.
- [ ] **Step 4: Run** `uv run pytest tests/test_history_mockdb.py -q` → PASS.
- [ ] **Step 5: Commit** `git add src/form_agent/history src/form_agent/freight/carriers/mockdb.py src/form_agent/config.py tests/test_history_mockdb.py && git commit -m "feat: historial simulado de envíos (36 meses por ruta)"`.

### Task 2: Modelo de forecast

**Files:**
- Create: `src/form_agent/forecast/__init__.py`, `src/form_agent/forecast/model.py`
- Test: `tests/test_forecast_model.py`

**Interfaces:**
- Consumes: `dict[date, int]` de `load_history`.
- Produces:
  `@dataclass(frozen=True) class Forecast`: `origin: str, destination: str, target: date, p10: int, p50: int, p90: int, baseline: float, growth: float, years_used: int, mae: float, naive_mae: float, coverage: float, n_backtest: int`;
  `class InsufficientHistory(ValueError)`;
  `add_months(d: date, n: int) -> date`;
  `forecast_lane(history: dict[date, int], origin: str, destination: str, target: date, as_of: date, recent_months: int = 3) -> Forecast`.

Algoritmo (no lo determinan firma ni tests, es la decisión central): `horizon` = meses entre el mes de `as_of` y `target` (≥ 1). `baseline` = promedio del valor del mismo mes calendario de `target` en años previos con dato. `growth` = (suma de los `recent_months` meses completos previos a `as_of`) / (promedio de la suma de esos mismos meses calendario en cada año previo con los 3 datos), acotado a [0.5, 2.0], 1.0 si no hay año comparable. Pronóstico puntual = `baseline × growth`. Backtest: para cada mes histórico M con al menos un año previo, repetir el cálculo con `target=M`, `as_of = add_months(M, -horizon)` usando solo datos anteriores a `as_of`; `ratio = real / pronóstico` (se omiten pronósticos 0). P10/P50/P90 = `pronóstico_actual × cuantil_{10,50,90}(ratios)` (interpolación lineal), forzados a ser monótonos, redondeados, ≥ 0. `mae`/`naive_mae` = error absoluto medio del pronóstico y del ingenuo (mismo mes del año anterior) en el backtest; `coverage` = fracción de reales con `ratio` entre los cuantiles 10 y 90 (en muestra, por construcción ≈ 0.8).

- [ ] **Step 1: Write the failing tests.** Helper `series(f)` que arma 36 meses (2023-11 a 2026-10) con `f(date) -> int`.
  `test_flat_history_forecasts_the_same_value` (serie constante 100 → p50 == 100, growth == 1.0, p10 ≤ p50 ≤ p90);
  `test_seasonal_pattern_is_reproduced` (serie con diciembre = 300 y resto 100 → p50 de dic-2026 entre 285 y 315);
  `test_growth_factor_scales_forecast` (serie 100 hasta jul-2026 y 150 en ago-oct-2026, resto de años 100 → growth ≈ 1.5 y p50 ≈ 150 para dic-2026);
  `test_quantiles_are_monotonic_non_negative_ints`;
  `test_all_zero_history_returns_zeros_without_error` (p10 == p50 == p90 == 0);
  `test_raises_insufficient_history_without_prior_same_month` (historial de 6 meses → `InsufficientHistory`);
  `test_year_wrap_target_january_uses_oct_to_dec_window` (target `date(2027, 1, 1)`, as_of `date(2026, 12, 1)` con serie que sube solo en oct-nov 2026 → `growth > 1`);
  `test_add_months_handles_year_boundaries` (`add_months(date(2026,11,1), 3) == date(2027,2,1)`, `-12`, `0`);
  `test_beats_naive_on_seasonal_growing_series` (serie estacional con +8 % anual y ruido determinista → `mae < naive_mae`).
- [ ] **Step 2: Run** `uv run pytest tests/test_forecast_model.py -q` → FAIL (módulo no existe).
- [ ] **Step 3: Implement** `forecast/model.py` con `statistics`/`math` de la biblioteca estándar y el algoritmo de arriba.
- [ ] **Step 4: Run** `uv run pytest tests/test_forecast_model.py -q` → PASS.
- [ ] **Step 5: Commit** `git add src/form_agent/forecast tests/test_forecast_model.py && git commit -m "feat: modelo de forecast P10/P50/P90 en Python puro"`.

### Task 3: Plan de pre-booking

**Files:**
- Create: `src/form_agent/forecast/plan.py`
- Modify: `src/form_agent/freight/models.py` (`Quote.free_teu: int | None = None`), `src/form_agent/freight/carriers/mockdb.py` (`MockDBRateProvider.quote` rellena `free_teu`)
- Test: `tests/test_forecast_plan.py` (y una aserción de `free_teu` en `tests/test_mockdb.py`)

**Interfaces:**
- Consumes: `Forecast` (Task 2), `ScheduleProvider`, `RateProvider`, `ShipmentRequest`, `Sailing`, `Quote`.
- Produces:
  `@dataclass(frozen=True) class Recommendation`: `tier: str` ("buy"|"prepare"|"watch"), `origin, destination: str`, `ref: str | None`, `vessel_name: str`, `voyage: str | None`, `etd: date`, `containers: int`, `price_per_container: float`, `currency: str`, `vs_avg_pct: float`;
  `@dataclass(frozen=True) class Unplaced`: `tier, origin, destination: str`, `containers: int`, `reason: str`;
  `@dataclass(frozen=True) class Plan`: `recommendations: list[Recommendation]`, `unplaced: list[Unplaced]`;
  `month_sailings(origin: str, destination: str, month: date, schedules, rates, container_type: str) -> list[tuple[Sailing, Quote]]`;
  `build_plan(forecasts: list[Forecast], schedules, rates, container_type: str = "40HC", max_share: float = 0.5) -> Plan`.

Decisiones: `month_sailings` llama `schedules.search` con `ShipmentRequest(container_count=1, departure_date=d)` para `d` = día 1, 8, 15, 22, 29 del mes (los proveedores devuelven ventanas de 21 días), descarta salidas fuera del mes, quita duplicados por `(vessel_name, voyage, etd)` y descarta las que `rates.quote` devuelve `None`. Cantidades por ruta: `buy = p10`, `prepare = p50 - p10`, `watch = p90 - p50`. Orden de salidas: `(price_per_container, etd)`. Cada nivel, en orden buy → prepare → watch, asigna a las salidas en ese orden hasta `ceil(max_share × cantidad_del_nivel)` por salida (mínimo 1), sin pasar de `free_teu // teu_por_contenedor` restante de esa salida (compartido entre niveles; `None` = sin límite) con `teu_por_contenedor = {"20DRY":1,"40DRY":2,"40HC":2,"45HC":3}`. Lo que no cabe va a `unplaced` con motivo ("sin salidas en el mes" o "capacidad libre insuficiente"). `vs_avg_pct = (precio / promedio de precios de las salidas del mes en esa ruta − 1) × 100`.

- [ ] **Step 1: Write the failing tests** con proveedores falsos de ~3 salidas controladas (precios 100/120/140, `free_teu` configurable) y `Forecast` armados a mano (p10=10, p50=30, p90=50):
  `test_buy_tier_goes_to_cheapest_sailing_first_up_to_max_share` (buy 10 con max_share 0.5 → ≤ 5 en la más barata, resto en la siguiente);
  `test_tiers_split_p10_p50_p90_amounts` (suma por nivel = 10, 20, 20 si hay capacidad);
  `test_never_exceeds_free_capacity_shared_across_tiers` (free_teu=8 en todas, 40HC → ≤ 4 contenedores por salida entre todos los niveles);
  `test_no_sailings_in_month_goes_to_unplaced_with_reason` (reason contiene "sin salidas");
  `test_insufficient_capacity_reports_remainder_as_unplaced` (reason contiene "capacidad");
  `test_zero_forecast_yields_no_recommendations_and_no_unplaced`;
  `test_vs_avg_pct_is_negative_for_cheapest_sailing`;
  `test_month_sailings_dedupes_and_stays_inside_target_month` (con `MockDBScheduleProvider`/`MockDBRateProvider` reales y `tmp_path`, todas las `etd` en el mes y sin repetidos).
- [ ] **Step 2: Run** `uv run pytest tests/test_forecast_plan.py -q` → FAIL.
- [ ] **Step 3: Implement** `Quote.free_teu`, su relleno en `MockDBRateProvider.quote` (y la aserción de `free_teu` en `tests/test_mockdb.py::test_quote_uses_the_price_for_the_container_type_and_reports_free_capacity`), y `forecast/plan.py` según las decisiones de arriba.
- [ ] **Step 4: Run** `uv run pytest tests/test_forecast_plan.py tests/test_mockdb.py -q` → PASS.
- [ ] **Step 5: Commit** `git add src/form_agent/forecast/plan.py src/form_agent/freight tests/test_forecast_plan.py tests/test_mockdb.py && git commit -m "feat: plan de pre-booking por niveles P10/P50/P90"`.

### Task 4: Generador de PDF

**Files:**
- Modify: `pyproject.toml` (agregar `fpdf2` con `uv add fpdf2`)
- Create: `src/form_agent/report/__init__.py`, `src/form_agent/report/pdf.py`
- Test: `tests/test_report_pdf.py`

**Interfaces:**
- Consumes: `Plan`, `Recommendation`, `Unplaced` (Task 3), `Forecast` (Task 2).
- Produces: `build_pdf(plan: Plan, forecasts: list[Forecast], narrative: str, as_of: date, target: date, path: Path, compress: bool = True) -> Path` y `latin1(text: str) -> str` (reemplaza lo que no cabe en Latin-1 por un equivalente ASCII o `?`).

Contenido: página 1 con título, fecha, mes objetivo, el `narrative` y un resumen (contenedores por nivel); tablas por nivel (`buy` = comprar, `prepare` = preparar, `watch` = vigilar) con ruta, buque (viaje), fecha de salida, contenedores, precio y `vs_avg_pct`; tabla de forecast por ruta (P10/P50/P90, crecimiento, `mae` vs `naive_mae`); sección «No colocado» con `unplaced`; nota final de supuestos (P10 = volumen superado el 90 % de las veces; datos simulados).

- [ ] **Step 1: Write the failing tests** (con `compress=False` los textos de Helvetica quedan legibles en los bytes):
  `test_creates_a_valid_pdf_file` (empieza con `b"%PDF"`, tamaño > 2000 bytes);
  `test_contains_vessel_route_and_tier_headings` (`b"MOCK FJORD"`, `b"CLSAI"`, `b"COMPRAR"` en el contenido);
  `test_empty_plan_still_renders` (plan y forecasts vacíos);
  `test_non_latin1_text_does_not_crash` (`narrative="Subir → 2.5 «bien» ≥ 10"` y un `vessel_name` con `"→"`);
  `test_unplaced_section_is_listed` (`b"No colocado"` y el motivo);
  `test_latin1_replaces_unencodable_characters`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `report/pdf.py` con `fpdf2` (`FPDF`, `Helvetica`, `pdf.table()` o `cell`), pasando todo texto por `latin1`.
- [ ] **Step 4: Run** `uv run pytest tests/test_report_pdf.py -q` → PASS.
- [ ] **Step 5: Commit** `git add pyproject.toml uv.lock src/form_agent/report tests/test_report_pdf.py && git commit -m "feat: PDF del informe mensual"`.

### Task 5: Resumen en palabras

**Files:**
- Create: `src/form_agent/report/narrative.py`
- Test: `tests/test_report_narrative.py`

**Interfaces:**
- Consumes: `Plan`, `Forecast`.
- Produces: `facts_from(plan: Plan, forecasts: list[Forecast], as_of: date, target: date) -> dict` (solo números y nombres: contenedores por nivel, top rutas por volumen P50, rutas omitidas, no colocado, ahorro medio `vs_avg_pct` ponderado por contenedores); `template_narrative(facts: dict) -> str`; `write_narrative(facts: dict, model=None) -> str` (con `model`: `model.invoke` con un prompt que pide 3 a 5 frases en español usando solo las cifras dadas; si `model` es `None`, está vacío o lanza excepción → `template_narrative`).

- [ ] **Step 1: Write the failing tests:**
  `test_facts_count_containers_per_tier`;
  `test_template_mentions_tier_totals_and_target_month` (el texto contiene los totales de `buy`, `prepare` y `watch`);
  `test_write_narrative_uses_model_text_when_available` (modelo falso `GenericFakeChatModel` de `tests/conftest.py` devuelve «Resumen del modelo» → se devuelve tal cual);
  `test_write_narrative_prompt_contains_the_numbers` (el prompt capturado incluye el total de `buy`);
  `test_write_narrative_falls_back_when_model_raises`;
  `test_write_narrative_without_model_uses_template`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `report/narrative.py`; el contenido del modelo se extrae como texto con el patrón de `handler._text`.
- [ ] **Step 4: Run** `uv run pytest tests/test_report_narrative.py -q` → PASS.
- [ ] **Step 5: Commit** `git add src/form_agent/report/narrative.py tests/test_report_narrative.py && git commit -m "feat: resumen del informe con plantilla de respaldo"`.

### Task 6: Orquestador, CLI y documentación

**Files:**
- Create: `src/form_agent/report/monthly.py`
- Modify: `README.md` (sección «Informe mensual»), `.env.example` (`HISTORY_DB_PATH`, `REPORT_DIR`)
- Test: `tests/test_report_monthly.py`

**Interfaces:**
- Consumes: todo lo anterior; `build_providers(settings)` de `freight/providers.py`; `send_message(settings, subject, html_body, attachments, to=None)` de `email.py`.
- Produces: `run_monthly_report(settings: Settings, today: date | None = None, target: date | None = None, send: bool = True, model=None, schedules=None, rates=None) -> Path` (ruta del PDF) y `main(argv: list[str] | None = None) -> int` con `--target YYYY-MM`, `--no-email`, `--no-llm`.

Flujo: `as_of = primer día del mes de today`; `target` por defecto = `add_months(as_of, 1)`; `ensure_history_db`; por cada ruta de `list_lanes` → `forecast_lane`, las que lanzan `InsufficientHistory` se omiten y se listan en `facts["skipped"]`; `build_plan`; `write_narrative`; `build_pdf` en `settings.report_dir/monthly-YYYY-MM.pdf` (se crea el directorio); si `send` y hay `resend_api_key`/`email_to`, `send_message` con asunto «Informe de pre-booking {mes}» y el PDF adjunto. Si el envío falla, el PDF queda en disco y `main` devuelve código 1 con el error en stderr.

- [ ] **Step 1: Write the failing tests** (`send_message` y proveedores reales con `tmp_path`; `Settings(_env_file=None, history_db_path=..., mock_db_path=..., report_dir=..., resend_api_key="x", email_to="a@b.c")`):
  `test_run_creates_pdf_named_after_target_month` (con `today=date(2026,11,16)` el archivo es `monthly-2026-12.pdf` y existe);
  `test_run_sends_one_email_with_pdf_attached_to_email_to` (un solo envío, adjunto = el PDF, `to` es `None`);
  `test_run_with_send_false_does_not_email`;
  `test_run_keeps_pdf_and_main_returns_1_when_resend_fails` (`send_message` lanza → PDF existe, `main([...]) == 1`);
  `test_lanes_without_history_are_skipped_not_fatal` (BD con una ruta de solo 6 meses → el informe se genera y `skipped` la menciona);
  `test_target_flag_overrides_default` (`--target 2027-01`);
  `test_no_llm_flag_uses_template` (sin llamar a ningún modelo).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `report/monthly.py` (`argparse` con `main`, `if __name__ == "__main__": raise SystemExit(main())`); sin `--no-llm` y con `ANTHROPIC_API_KEY` usa `ChatAnthropic(model=settings.model, api_key=...)`; `load_dotenv()` al inicio de `main` como en `main.py`. Documentar en README el comando `uv run python -m form_agent.report.monthly`, qué significa cada nivel y cómo programarlo el día 1 (cron de ejemplo, sin instalarlo).
- [ ] **Step 4: Run** `uv run pytest -q` (suite completa) → todo PASS; luego, una corrida real sin correo: `uv run python -m form_agent.report.monthly --no-email --no-llm` y comprobar que existe `artifacts/reports/monthly-2026-12.pdf`.
- [ ] **Step 5: Commit** `git add src/form_agent/report/monthly.py README.md .env.example tests/test_report_monthly.py && git commit -m "feat: comando del informe mensual con envío por correo"`.
