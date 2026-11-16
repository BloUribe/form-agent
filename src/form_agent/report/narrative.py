"""Resumen en español del informe. Los números los fija el código (facts); el modelo solo los redacta."""
from __future__ import annotations

import json
import re
from datetime import date

from ..forecast.model import Forecast
from ..forecast.plan import TIERS, Plan

_PROMPT = """Eres analista de logística marítima. Redacta en español un resumen ejecutivo de 3 a 4 frases cortas (máximo 70 palabras) para el informe mensual de
pre-booking, usando EXCLUSIVAMENTE las cifras del JSON (no inventes ni recalcules números, no añadas rutas ni buques).
Explica qué reservar ya («comprar», P10: poco riesgo de quedar sin usar), qué preparar («preparar», P50) y qué vigilar («vigilar», P90),
usando siempre esos tres nombres en español y NUNCA las claves buy, prepare ni watch del JSON,
menciona las rutas principales, el ahorro frente al promedio si existe, y advierte de lo que no se pudo colocar u omitir.
Sin viñetas, títulos ni formato markdown (sin asteriscos).

JSON:
{facts}"""


def facts_from(plan: Plan, forecasts: list[Forecast], as_of: date, target: date, skipped: list[str] | None = None) -> dict:
    tiers = {t: {"containers": sum(r.containers for r in plan.recommendations if r.tier == t),
                 "sailings": sum(1 for r in plan.recommendations if r.tier == t)} for t in TIERS}
    buys = [r for r in plan.recommendations if r.tier == "buy"]
    total = sum(r.containers for r in buys)
    avg_vs = sum(r.vs_avg_pct * r.containers for r in buys) / total if total else None
    top = sorted(forecasts, key=lambda f: -f.p50)[:5]
    return {
        "target_month": f"{target:%m/%Y}", "report_date": f"{as_of:%d/%m/%Y}", "tiers": tiers,
        "top_routes": [{"route": f"{f.origin}-{f.destination}", "p10": f.p10, "p50": f.p50, "p90": f.p90} for f in top],
        "avg_price_vs_route_average_pct": None if avg_vs is None else round(avg_vs, 1),
        "unplaced_containers": sum(u.containers for u in plan.unplaced),
        "skipped": list(skipped or []),
    }


def template_narrative(facts: dict) -> str:
    t = facts["tiers"]
    parts = [f"Para {facts['target_month']} se recomienda reservar {t['buy']['containers']} contenedores ya (P10, en "
             f"{t['buy']['sailings']} salidas), preparar {t['prepare']['containers']} más sin comprar (hasta P50) y "
             f"vigilar {t['watch']['containers']} adicionales (hasta P90)."]
    if facts["top_routes"]:
        parts.append("Rutas con mayor volumen esperado (P50): " + ", ".join(
            f"{r['route']} ({r['p50']})" for r in facts["top_routes"][:3]) + ".")
    if facts["avg_price_vs_route_average_pct"] is not None:
        pct = facts["avg_price_vs_route_average_pct"]
        side = "por debajo" if pct < 0 else "por encima"
        parts.append(f"Las salidas a reservar quedan {abs(pct):.1f}% {side} del precio promedio de la ruta.".replace(".", ",", 1))
    if facts["unplaced_containers"]:
        parts.append(f"{facts['unplaced_containers']} contenedores no se pudieron colocar por falta de salidas o capacidad.")
    if facts["skipped"]:
        parts.append("Rutas omitidas por historial insuficiente: " + ", ".join(facts["skipped"]) + ".")
    return " ".join(parts)


def _text(content) -> str:
    return content if isinstance(content, str) else "".join(b.get("text", "") for b in content if isinstance(b, dict))


def _plain(text: str) -> str:
    """El PDF no renderiza markdown: quita encabezados, negritas y comillas invertidas que el modelo suela añadir."""
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    return re.sub(r"\*\*|__|`", "", text)


def write_narrative(facts: dict, model=None) -> str:
    if model is not None:
        try:
            text = _plain(_text(model.invoke(_PROMPT.format(facts=json.dumps(facts, ensure_ascii=False, indent=1))).content)).strip()
            if text:
                return text
        except Exception as e:  # el informe no depende del modelo de lenguaje
            print(f"[narrative] el modelo fallo, se usa la plantilla: {e}")
    return template_narrative(facts)
