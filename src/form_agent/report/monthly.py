"""Informe mensual de pre-booking:  uv run python -m form_agent.report.monthly [--target YYYY-MM] [--no-email] [--no-llm]"""
from __future__ import annotations

import argparse
import html
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

from ..config import Settings
from ..dates import add_months
from ..email import send_message
from ..forecast.model import InsufficientHistory, forecast_lane
from ..forecast.plan import build_plan
from ..freight.providers import build_providers
from ..history.mockdb import ensure_history_db, list_lanes, load_history
from ..ports import route_label
from . import brand as B
from .narrative import facts_from, write_narrative
from .pdf import build_pdf


def _email_html(narrative: str, forecasts, target: date) -> str:
    """Cuerpo del correo con la marca de Interworld (HTML con estilos en línea: los clientes de correo ignoran las hojas de estilo)."""
    month = f"{B.MONTHS_ES[target.month - 1].capitalize()} {target.year}"
    lanes = ""
    for f in forecasts:
        cells = "".join(
            f'<td style="width:33%;padding:12px;background:#F4F6F9;border-top:3px solid {B.TIER_COLORS[t]};vertical-align:top">'
            f'<div style="font-size:10px;letter-spacing:1px;color:#3D4D66"><b>{B.TIER_LABELS[t]} · {B.TIER_PCT[t]}</b></div>'
            f'<div style="font-size:26px;font-weight:bold;color:#0C2440">{"" if t == "buy" else "+"}{n}</div>'
            f'<div style="font-size:11px;color:#737E8C">contenedores</div></td>'
            for t, n in (("buy", f.p10), ("prepare", f.p50 - f.p10), ("watch", f.p90 - f.p50)))
        lanes += (f'<p style="margin:18px 0 6px;font-size:15px;font-weight:bold;color:#0C2440">{html.escape(route_label(f.origin, f.destination))}</p>'
                  f'<table width="100%" cellspacing="6" cellpadding="0" style="border-collapse:separate"><tr>{cells}</tr></table>')
    return (f'<div style="font-family:Arial,Helvetica,sans-serif;max-width:620px;margin:0 auto;color:#3D4D66">'
            f'<div style="background:#0C2440;padding:22px 26px;border-bottom:4px solid #E86028">'
            f'<div style="color:#9DB6D9;font-size:11px;letter-spacing:2px">INFORME DE PRE-BOOKING</div>'
            f'<div style="color:#FFFFFF;font-size:26px;font-weight:bold">{month}</div>'
            f'<div style="color:#FFFFFF;font-size:13px;margin-top:4px">{B.BRAND_NAME}</div></div>'
            f'<div style="padding:8px 26px 22px">{lanes}'
            f'<p style="font-size:14px;line-height:1.5;margin:20px 0">{html.escape(narrative)}</p>'
            f'<p style="font-size:12px;color:#737E8C;border-top:1px solid #E9EDF1;padding-top:12px">'
            f'Adjunto el PDF con las salidas recomendadas y el gráfico. Datos simulados; no se reserva nada.</p></div></div>')


def run_monthly_report(settings: Settings, today: date | None = None, target: date | None = None, send: bool = True,
                       model=None, schedules=None, rates=None) -> Path:
    today = today or date.today()
    as_of = today.replace(day=1)
    target = (target or add_months(as_of, 1)).replace(day=1)
    horizon = (target.year - as_of.year) * 12 + target.month - as_of.month
    if not 1 <= horizon <= 6:
        raise ValueError(f"el mes objetivo ({target:%m/%Y}) debe estar entre 1 y 6 meses despues del informe ({as_of:%m/%Y})")
    ensure_history_db(settings.history_db_path, today)
    if schedules is None or rates is None:
        schedules, rates = build_providers(settings, today=today)

    forecasts, skipped, histories = [], [], {}
    for origin, dest in list_lanes(settings.history_db_path):
        histories[(origin, dest)] = load_history(settings.history_db_path, origin, dest)
        try:
            forecasts.append(forecast_lane(histories[(origin, dest)], origin, dest, target, as_of))
        except InsufficientHistory:
            skipped.append(f"{origin}-{dest}")
    plan = build_plan(forecasts, schedules, rates)
    narrative = write_narrative(facts_from(plan, forecasts, today, target, skipped), model)  # se muestra la fecha real de la corrida
    path = build_pdf(plan, forecasts, narrative, today, target, Path(settings.report_dir) / f"monthly-{target:%Y-%m}.pdf",
                     skipped=skipped, histories=histories)

    if send and not (settings.resend_api_key and settings.email_to):
        print(f"AVISO: correo no configurado (RESEND_API_KEY / EMAIL_TO); no se envio. PDF guardado en {path}", file=sys.stderr)
    if send and settings.resend_api_key and settings.email_to:
        body = _email_html(narrative, forecasts, target)
        try:
            send_message(settings, f"Informe de pre-booking {B.MONTHS_ES[target.month - 1].capitalize()} {target.year} - {B.BRAND_NAME}", body, [path])
        except Exception as e:  # el PDF ya existe: se conserva y se avisa dónde
            raise RuntimeError(f"PDF guardado en {path} pero el correo fallo: {e}") from e
    return path


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    ap = argparse.ArgumentParser(description="Informe mensual de pre-booking (forecast P10/P50/P90)")
    ap.add_argument("--target", help="mes objetivo YYYY-MM (por defecto, el mes siguiente)")
    ap.add_argument("--today", help="fecha del informe YYYY-MM-DD (por defecto, hoy)")
    ap.add_argument("--no-email", action="store_true", help="solo genera el PDF")
    ap.add_argument("--no-llm", action="store_true", help="resumen con plantilla, sin llamar al modelo")
    args = ap.parse_args(argv)
    if settings is None:
        load_dotenv()  # exporta LANGSMITH_* a os.environ (pydantic-settings no lo hace)
        settings = Settings()
    try:
        target = date.fromisoformat(args.target + "-01") if args.target else None
        today = date.fromisoformat(args.today) if args.today else None
        model = None if args.no_llm or not settings.anthropic_api_key else ChatAnthropic(
            model=settings.model, api_key=settings.anthropic_api_key, max_tokens=1024)
        path = run_monthly_report(settings, today=today, target=target, send=not args.no_email, model=model)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
