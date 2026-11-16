"""Identidad visual del informe: Interworld Freight (colores del logo y del sitio interwf.com)."""
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"
LOGO_WHITE = ASSETS / "interworld-logo-white.svg"  # sobre fondo azul marino
BRAND_NAME = "Interworld Freight"


def rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


NAVY_DARK = "#0C2440"   # fondo de cabecera y texto principal
NAVY = "#15385E"        # azul marino del logo
ORANGE = "#E86028"      # acento de marca
SLATE = "#3D4D66"       # texto secundario
MUTED = "#737E8C"       # texto terciario y ejes
LINE = "#E9EDF1"        # rejilla y filetes
PANEL = "#F4F6F9"       # fondo de tarjetas
BAR_HISTORY = "#B8C4D2" # histórico: gris azulado neutro (el pronóstico es lo que destaca)
# Niveles: una sola tonalidad azul, de más oscuro (comprar) a más claro (vigilar); validada con la skill dataviz.
TIER_COLORS = {"buy": "#15385E", "prepare": "#3F6BA8", "watch": "#7C9DCB"}
TIER_TEXT = {"buy": "#FFFFFF", "prepare": "#FFFFFF", "watch": "#0C2440"}  # texto sobre el chip de cada nivel
TIER_LABELS = {"buy": "COMPRAR", "prepare": "PREPARAR", "watch": "VIGILAR"}
TIER_PCT = {"buy": "P10", "prepare": "P50", "watch": "P90"}

MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre"]
MONTHS_SHORT = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
