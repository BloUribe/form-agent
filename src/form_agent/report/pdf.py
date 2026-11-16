"""PDF del informe mensual con la marca de Interworld Freight (fpdf2, fuentes base: todo el texto pasa por latin1())."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fpdf import FPDF

from ..dates import add_months
from ..forecast.model import Forecast
from ..forecast.plan import TIERS, Plan, Recommendation, Unplaced
from ..ports import port_label
from . import brand as B

_REPLACE = {"→": "->", "←": "<-", "≥": ">=", "≤": "<=", "“": '"', "”": '"', "‘": "'",
            "’": "'", "–": "-", "—": "-", "…": "...", "•": "-", "€": "EUR"}
_MARGIN = 14
_W = 210 - 2 * _MARGIN  # ancho útil
_CAPTION = {"buy": "Reservar ya. Se supera el 90% de las veces.", "prepare": "Tener opciones listas, sin comprar todavía.",
            "watch": "Escenario alto: solo vigilar disponibilidad."}


def latin1(text: str) -> str:
    for src, dst in _REPLACE.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")


def _money(v: float, currency: str = "USD") -> str:
    return f"{currency} {v:,.0f}".replace(",", ".")


def _num(v: float) -> str:
    return f"{v:,.0f}".replace(",", ".")


class _Doc(FPDF):
    month_label = ""

    def _fill(self, hex_color: str) -> None:
        self.set_fill_color(*B.rgb(hex_color))

    def _ink(self, hex_color: str) -> None:
        self.set_text_color(*B.rgb(hex_color))

    def _draw(self, hex_color: str) -> None:
        self.set_draw_color(*B.rgb(hex_color))

    def header(self) -> None:
        first = self.page_no() == 1
        band = 36 if first else 14
        self._fill(B.NAVY_DARK)
        self.rect(0, 0, 210, band, style="F")
        self._fill(B.ORANGE)
        self.rect(0, band, 210, 1.2, style="F")
        if first:
            self.image(str(B.LOGO_WHITE), x=_MARGIN, y=10, w=54)
            self.set_font("Helvetica", "B", 7)
            self._ink("#9DB6D9")
            self.set_char_spacing(0.8)
            self.set_xy(_MARGIN, 11)
            self.cell(_W, 4, latin1("INFORME DE PRE-BOOKING"), align="R")
            self.set_char_spacing(0)
            self.set_font("Helvetica", "B", 21)
            self._ink("#FFFFFF")
            self.set_xy(_MARGIN, 16)
            self.cell(_W, 10, latin1(self.month_label), align="R")
            self.set_y(band + 8)
        else:
            self.image(str(B.LOGO_WHITE), x=_MARGIN, y=3.6, w=30)
            self.set_font("Helvetica", size=8)
            self._ink("#9DB6D9")
            self.set_xy(_MARGIN, 4.6)
            self.cell(_W, 5, latin1(f"Informe de pre-booking - {self.month_label}"), align="R")
            self.set_y(band + 7)

    def footer(self) -> None:
        self.set_y(-13)
        self._draw(B.LINE)
        self.line(_MARGIN, self.get_y(), 210 - _MARGIN, self.get_y())
        self.set_font("Helvetica", size=7)
        self._ink(B.MUTED)
        self.set_y(-11)
        self.set_x(_MARGIN)
        self.cell(_W / 2, 4, latin1(f"{B.BRAND_NAME} - Informe de pre-booking - Datos simulados"))
        self.cell(_W / 2, 4, f"Página {self.page_no()} de {{nb}}", align="R")


def _label(pdf: _Doc, text: str, x: float, y: float, w: float = 0, align: str = "L") -> None:
    pdf.set_font("Helvetica", "B", 6.8)
    pdf._ink(B.MUTED)
    pdf.set_char_spacing(0.7)
    pdf.set_xy(x, y)
    pdf.cell(w or _W, 3.5, latin1(text), align=align)
    pdf.set_char_spacing(0)


def _lane_title(pdf: _Doc, origin: str, dest: str, subtitle: str) -> None:
    _label(pdf, "RUTA", _MARGIN, pdf.get_y())
    y = pdf.get_y() + 4.5
    pdf.set_font("Helvetica", "B", 15)
    pdf._ink(B.NAVY_DARK)
    a, b = latin1(port_label(origin)), latin1(port_label(dest))
    wa = pdf.get_string_width(a)
    pdf.set_xy(_MARGIN, y)
    pdf.cell(wa, 8, a)
    ax = _MARGIN + wa + 3
    pdf._draw(B.ORANGE)
    pdf._fill(B.ORANGE)
    pdf.set_line_width(0.6)
    pdf.line(ax, y + 4.1, ax + 8, y + 4.1)
    pdf.polygon([(ax + 8, y + 2.2), (ax + 11, y + 4.1), (ax + 8, y + 6)], style="F")
    pdf.set_line_width(0.2)
    pdf.set_xy(ax + 14, y)
    pdf.cell(pdf.get_string_width(b) + 2, 8, b)
    pdf.set_font("Helvetica", size=8.5)
    pdf._ink(B.SLATE)
    pdf.set_xy(_MARGIN, y + 9)
    pdf.cell(_W, 5, latin1(subtitle))
    pdf.set_y(y + 18)


def _tiles(pdf: _Doc, f: Forecast) -> None:
    gap, h = 5, 29
    w = (_W - 2 * gap) / 3
    y = pdf.get_y()
    amounts = {"buy": f.p10, "prepare": f.p50 - f.p10, "watch": f.p90 - f.p50}
    totals = {"buy": f.p10, "prepare": f.p50, "watch": f.p90}
    for i, t in enumerate(TIERS):
        x = _MARGIN + i * (w + gap)
        pdf._fill(B.PANEL)
        pdf.rect(x, y, w, h, style="F", round_corners=True, corner_radius=1.6)
        pdf._fill(B.TIER_COLORS[t])
        pdf.rect(x, y, w, 1.8, style="F")
        _label(pdf, f"{B.TIER_LABELS[t]} \u00b7 {B.TIER_PCT[t]}", x + 4, y + 5, w - 8)
        number = _num(amounts[t]) if t == "buy" else "+" + _num(amounts[t])
        pdf.set_font("Helvetica", "B", 26)
        pdf._ink(B.NAVY_DARK)
        number_w = pdf.get_string_width(number)
        pdf.set_xy(x + 4, y + 9.5)
        pdf.cell(number_w + 1, 11, number)
        pdf.set_font("Helvetica", size=8)
        pdf._ink(B.MUTED)
        pdf.set_xy(x + 4 + number_w + 3, y + 14.5)
        pdf.cell(25, 5, "contenedores")
        pdf.set_font("Helvetica", size=7.2)
        pdf._ink(B.SLATE)
        pdf.set_xy(x + 4, y + 21)
        extra = "" if t == "buy" else f" Total hasta {B.TIER_PCT[t]}: {_num(totals[t])}."
        pdf.multi_cell(w - 8, 3.4, latin1(_CAPTION[t] + extra), new_x="LEFT", new_y="NEXT", align="L")
    pdf.set_y(y + h + 6)


def _callout(pdf: _Doc, title: str, text: str, color: str = B.NAVY) -> None:
    pdf.set_font("Helvetica", size=8)
    lines = pdf.multi_cell(_W - 9, 4, latin1(text), dry_run=True, output="LINES", align="L")
    h = 7 + 4 * len(lines) + 1.5
    if pdf.get_y() + h > pdf.h - 20:
        pdf.add_page()
    y = pdf.get_y()
    pdf._fill(B.PANEL)
    pdf.rect(_MARGIN, y, _W, h, style="F")
    pdf._fill(color)
    pdf.rect(_MARGIN, y, 1.4, h, style="F")
    pdf.set_font("Helvetica", "B", 8)
    pdf._ink(B.NAVY_DARK)
    pdf.set_xy(_MARGIN + 5, y + 2)
    pdf.cell(_W - 9, 4, latin1(title))
    pdf.set_font("Helvetica", size=8)
    pdf._ink(B.SLATE)
    pdf.set_xy(_MARGIN + 5, y + 6.5)
    pdf.multi_cell(_W - 9, 4, latin1(text), new_x="LEFT", new_y="NEXT", align="L")
    pdf.set_y(y + h + 4)


def _footnote(pdf: _Doc, text: str) -> None:
    pdf.set_font("Helvetica", size=6.8)
    pdf._ink(B.MUTED)
    pdf.set_x(_MARGIN)
    pdf.multi_cell(_W, 3.3, latin1(text), new_x="LEFT", new_y="NEXT", align="L")


def _nice_step(top: float) -> float:
    for step in (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000):
        if top / step <= 5:
            return step
    return 5000


def _chart(pdf: _Doc, history: dict[date, int], f: Forecast) -> None:
    h = 54
    if pdf.get_y() + h + 14 > pdf.h - 20:
        pdf.add_page()
    y0 = pdf.get_y()
    pdf.set_font("Helvetica", "B", 10)
    pdf._ink(B.NAVY_DARK)
    pdf.set_xy(_MARGIN, y0)
    pdf.cell(_W, 5, latin1("Contenedores por mes: últimos 12 meses y pronóstico"))
    months = sorted(history)[-12:]
    values = [history[m] for m in months]
    step = _nice_step(max(values + [f.p90, 1]) * 1.05)
    ymax = step * (-(-max(values + [f.p90, 1]) // step))
    left, right = _MARGIN + 9, _MARGIN + _W - 30
    top, bottom = y0 + 9, y0 + h - 9
    scale = (bottom - top) / ymax
    ypos = lambda v: bottom - v * scale  # noqa: E731
    pdf.set_font("Helvetica", size=6.5)
    for g in range(0, int(ymax) + 1, int(step)):
        pdf._draw(B.LINE if g else "#B7C1CE")
        pdf.set_line_width(0.2)
        pdf.line(left, ypos(g), right, ypos(g))
        pdf._ink(B.MUTED)
        pdf.set_xy(_MARGIN, ypos(g) - 1.8)
        pdf.cell(7, 3.6, _num(g), align="R")
    slots = len(months) + 1
    slot = (right - left) / slots
    # histórico: gris azulado neutro
    for i, (m, v) in enumerate(zip(months, values)):
        bw = slot * 0.56
        x = left + i * slot + (slot - bw) / 2
        pdf._fill(B.BAR_HISTORY)
        if v > 0:
            pdf.rect(x, ypos(v), bw, v * scale, style="F")
    # pronóstico: columna apilada por nivel, con 0.5 mm de separación entre bloques
    fw = slot * 0.78
    fx = left + len(months) * slot + (slot - fw) / 2
    for t, lo, hi in (("buy", 0, f.p10), ("prepare", f.p10, f.p50), ("watch", f.p50, f.p90)):
        if hi > lo:
            pdf._fill(B.TIER_COLORS[t])
            pdf.rect(fx, ypos(hi) + 0.25, fw, (hi - lo) * scale - 0.5, style="F")
    # separador y etiqueta del pronóstico
    sx = left + len(months) * slot
    pdf._draw(B.ORANGE)
    pdf.set_dash_pattern(dash=1, gap=1)
    pdf.line(sx, top - 2, sx, bottom)
    pdf.set_dash_pattern()
    pdf.set_font("Helvetica", "B", 6)
    pdf._ink(B.ORANGE)
    pdf.set_char_spacing(0.5)
    pdf.set_xy(sx + 1.5, top - 5)
    pdf.cell(22, 3, "PRONÓSTICO")
    pdf.set_char_spacing(0)
    # etiquetas directas P90 / P50 / P10 (sin solaparse)
    pos = sorted([(ypos(f.p90), "P90", f.p90, "watch"), (ypos(f.p50), "P50", f.p50, "prepare"), (ypos(f.p10), "P10", f.p10, "buy")])
    last = -99.0
    for yy, name, val, t in pos:
        yy = max(yy, last + 4)
        last = yy
        pdf._fill(B.TIER_COLORS[t])
        pdf.rect(fx + fw + 2, yy - 1, 2, 2, style="F")
        pdf.set_font("Helvetica", "B", 7)
        pdf._ink(B.NAVY_DARK)
        pdf.set_xy(fx + fw + 5.5, yy - 2)
        pdf.cell(20, 4, f"{name}  {_num(val)}")
    # etiquetas del eje x: mes, y año en el primero, en enero y en el pronóstico
    labels = months + [f.target]
    for i, m in enumerate(labels):
        is_fc = i == len(months)
        x = left + i * slot
        pdf.set_font("Helvetica", "B" if is_fc else "", 6.5)
        pdf._ink(B.NAVY_DARK if is_fc else B.MUTED)
        pdf.set_xy(x, bottom + 1.2)
        pdf.cell(slot, 3.4, B.MONTHS_SHORT[m.month - 1], align="C")
        if i == 0 or m.month == 1 or is_fc:
            pdf.set_font("Helvetica", size=6)
            pdf.set_xy(x, bottom + 4.4)
            pdf.cell(slot, 3, str(m.year), align="C")
    pdf.set_font("Helvetica", size=7)
    pdf._ink(B.MUTED)
    pdf.set_xy(_MARGIN, y0 + h - 1)
    pdf.cell(_W, 4, latin1("Gris: envíos reales. Azules: pronóstico del mes, por nivel (P10 / P50 / P90)."))
    pdf.set_y(y0 + h + 7)


_COLS = (24, 24, 58, 18, 28, 30)


def _table_header(pdf: _Doc) -> None:
    y = pdf.get_y()
    pdf._fill(B.NAVY_DARK)
    pdf.rect(_MARGIN, y, _W, 6.4, style="F")
    pdf.set_font("Helvetica", "B", 7)
    pdf._ink("#FFFFFF")
    x = _MARGIN
    for title, w, align in zip(("Nivel", "Salida", "Buque (viaje)", "Cont.", "Precio/cont.", "Total"), _COLS,
                               ("L", "L", "L", "R", "R", "R")):
        pdf.set_xy(x + 2, y + 1.3)
        pdf.cell(w - 4, 4, title, align=align)
        x += w
    pdf.set_y(y + 6.4)


def _table(pdf: _Doc, recs: list[Recommendation]) -> None:
    pdf.set_font("Helvetica", "B", 10)
    pdf._ink(B.NAVY_DARK)
    pdf.set_x(_MARGIN)
    pdf.cell(_W, 6, "Salidas recomendadas", new_x="LMARGIN", new_y="NEXT")
    if not recs:
        _callout(pdf, "Sin salidas recomendadas", "No hay salidas en el mes objetivo para esta ruta.", B.ORANGE)
        return
    _table_header(pdf)
    ordered = sorted(recs, key=lambda r: (TIERS.index(r.tier), r.etd))
    for n, r in enumerate(ordered):
        if pdf.get_y() + 6.6 > pdf.h - 20:
            pdf.add_page()
            _table_header(pdf)
        y = pdf.get_y()
        if n % 2 == 0:
            pdf._fill(B.PANEL)
            pdf.rect(_MARGIN, y, _W, 6.4, style="F")
        pdf._fill(B.TIER_COLORS[r.tier])
        pdf.rect(_MARGIN + 2, y + 1.2, 20, 4, style="F", round_corners=True, corner_radius=1)
        pdf.set_font("Helvetica", "B", 6.2)
        pdf._ink(B.TIER_TEXT[r.tier])
        pdf.set_xy(_MARGIN + 2, y + 1.6)
        pdf.cell(20, 3.2, B.TIER_LABELS[r.tier], align="C")
        pdf.set_font("Helvetica", size=7.8)
        pdf._ink(B.NAVY_DARK)
        cells = (f"{r.etd:%d/%m/%Y}", f"{r.vessel_name} ({r.voyage or '-'})", _num(r.containers),
                 _money(r.price_per_container, r.currency), _money(r.price_per_container * r.containers, r.currency))
        x = _MARGIN + _COLS[0]
        for text, w, align in zip(cells, _COLS[1:], ("L", "L", "R", "R", "R")):
            pdf.set_xy(x + 2, y + 1.4)
            pdf.cell(w - 4, 4, latin1(text), align=align)
            x += w
        pdf.set_y(y + 6.4)
    buy = [r for r in recs if r.tier == "buy"]
    if buy:
        total = sum(r.price_per_container * r.containers for r in buy)
        pdf.ln(1.5)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf._ink(B.NAVY_DARK)
        pdf.set_x(_MARGIN)
        pdf.cell(_W, 5, latin1(f"Compromiso si compra el nivel COMPRAR: {_num(sum(r.containers for r in buy))} contenedores, "
                               f"aprox. {_money(total, buy[0].currency)}"), align="R")
        pdf.ln(7)


def build_pdf(plan: Plan, forecasts: list[Forecast], narrative: str, as_of: date, target: date, path: Path,
              compress: bool = True, skipped: list[str] | None = None,
              histories: dict[tuple[str, str], dict[date, int]] | None = None) -> Path:
    histories = histories or {}
    pdf = _Doc(format="A4")
    pdf.month_label = f"{B.MONTHS_ES[target.month - 1].capitalize()} {target.year}"
    pdf.alias_nb_pages()
    pdf.set_compression(compress)
    pdf.set_margins(_MARGIN, _MARGIN, _MARGIN)
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()

    if not forecasts:
        _callout(pdf, "Sin pronóstico disponible", "No hubo historial suficiente para pronosticar el mes objetivo.", B.ORANGE)
    for i, f in enumerate(forecasts):
        if i:
            pdf.add_page()
        hist = histories.get((f.origin, f.destination), {})
        recent = list(hist.values())[-12:]
        avg = f" - promedio de los últimos 12 meses: {sum(recent) / len(recent):.0f} contenedores" if recent else ""
        _lane_title(pdf, f.origin, f.destination, f"Informe del {as_of:%d/%m/%Y}{avg}")
        _tiles(pdf, f)
        if i == 0 and narrative:
            _callout(pdf, "Resumen", narrative)
        if hist:
            _chart(pdf, hist, f)
        _table(pdf, [r for r in plan.recommendations if (r.origin, r.destination) == (f.origin, f.destination)])

    if plan.unplaced:
        _callout(pdf, "Sin colocar", "\n".join(
            f"{B.TIER_LABELS[u.tier].capitalize()}: {u.containers} contenedores ({u.origin}-{u.destination}) - {u.reason}"
            for u in plan.unplaced), B.ORANGE)
    if skipped:
        _callout(pdf, "Rutas omitidas (historial insuficiente)",
                 "No se pronosticaron por falta del mismo mes en años previos: " + ", ".join(skipped) + ".", B.MUTED)
    _footnote(pdf, "Cómo leer este informe: P10 es el volumen que se supera el 90% de las veces (reservarlo tiene poco riesgo de quedar sin "
                   "usar); P50 es la mediana (tener opciones listas); P90 es el escenario alto (solo vigilar). Los percentiles salen de los errores "
                   "del mismo cálculo sobre cada mes histórico. Historial, salidas, capacidad y precios son simulados; no se reserva nada.")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path
