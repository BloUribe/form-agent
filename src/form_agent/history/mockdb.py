"""Historial simulado de un cliente estándar: ~77 contenedores al mes de Miami a San Antonio (Chile), con una
temporada suave, crecimiento leve y mucha variación mes a mes (determinista). 36 meses completos.

Los volúmenes son contenedores por mes y ruta. Se reconstruye al cambiar el mes, para que la ventana siga
siendo «los 36 meses completos anteriores a hoy». NO son datos reales de ningún cliente.
"""
from __future__ import annotations

import random
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

from ..dates import add_months

MONTHS = 36
_VERSION = 2  # subir al cambiar el generador: fuerza a rehacer las BD ya guardadas en disco
CUSTOMER_LANES = [("USMIA", "CLSAI")]  # rutas del cliente; deben existir en la BD de salidas
CUSTOMER_MONTHLY_AVG = 77
_SEASON = {12: 1.25, 11: 1.1, 1: 0.9, 2: 0.8}  # temporada suave de fin de año
_ANNUAL_GROWTH = 1.04
_NOISE = (0.2, 1.8)  # un mes cualquiera puede ser 20 % o 180 % de lo normal (perfil con P10 ~30 y P50 ~77)


def _connect(path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(path))


def ensure_history_db(path, today: date | None = None) -> None:
    today = today or date.today()
    this_month = today.replace(day=1)
    with closing(_connect(path)) as con:
        con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        row = con.execute("SELECT value FROM meta WHERE key='built_on'").fetchone()
        stamp = f"{this_month:%Y-%m}|v{_VERSION}"
        if row and row[0] == stamp:
            return
        con.executescript("""
            DROP TABLE IF EXISTS shipments;
            CREATE TABLE shipments (month TEXT NOT NULL, origin TEXT NOT NULL, destination TEXT NOT NULL,
                                    containers INTEGER NOT NULL, PRIMARY KEY (month, origin, destination));""")
        months = [add_months(this_month, -k) for k in range(MONTHS, 0, -1)]
        rows = []
        for origin, dest in CUSTOMER_LANES:
            for idx, month in enumerate(months):
                rng = random.Random(f"{origin}-{dest}-{month:%Y-%m}")
                volume = (CUSTOMER_MONTHLY_AVG * _SEASON.get(month.month, 1.0) * _ANNUAL_GROWTH ** (idx / 12)
                          * rng.uniform(*_NOISE))
                rows.append((month.isoformat(), origin, dest, max(0, round(volume))))
        con.executemany("INSERT INTO shipments VALUES (?,?,?,?)", rows)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('built_on', ?)", (stamp,))
        con.commit()


def list_lanes(path) -> list[tuple[str, str]]:
    with closing(_connect(path)) as con:
        return con.execute("SELECT DISTINCT origin, destination FROM shipments ORDER BY origin, destination").fetchall()


def load_history(path, origin: str, destination: str) -> dict[date, int]:
    """Contenedores por mes (clave = primer día del mes)."""
    with closing(_connect(path)) as con:
        rows = con.execute("SELECT month, containers FROM shipments WHERE origin=? AND destination=? ORDER BY month",
                           (origin, destination)).fetchall()
    return {date.fromisoformat(m): c for m, c in rows}
