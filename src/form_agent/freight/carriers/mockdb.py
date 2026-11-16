"""Base de datos SQLite simulada: salidas semanales por ruta desde hoy hasta 6 meses adelante, con capacidad libre y precios.

Es determinista (mismos datos para el mismo día) y se regenera sola cuando cambia el día, así la ventana
«hoy → +6 meses» siempre está vigente. Buques e IMO son ficticios. NO son datos de ninguna naviera.
Inspeccionar:  sqlite3 artifacts/mock_freight.sqlite 'select * from sailings limit 10'
"""
from __future__ import annotations

import math
import random
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from ...dates import add_months
from ..models import Quote, Sailing, ShipmentRequest

CARRIER = "MOCK-DB"
_VERSION = 2  # subir al cambiar el generador (rutas, precios...): fuerza a rehacer las BD ya guardadas en disco
WINDOW_DAYS = 21  # cuántos días después de la fecha deseada se buscan salidas
MAX_RESULTS = 6

# (origen, destino, días de tránsito, trasbordos). Cada ruta existe en ambos sentidos.
_BASE_LANES = [
    ("CLSAI", "CNSHA", 38, 0), ("CLVAP", "CNSHA", 39, 0), ("CLSAI", "CNNGB", 40, 0), ("CLVAP", "USLAX", 21, 0),
    ("CLSAI", "NLRTM", 32, 1), ("CLVAP", "ESVLC", 30, 1), ("PECLL", "CNSHA", 36, 1), ("BRSSZ", "CNSHA", 35, 1),
    ("BRSSZ", "NLRTM", 18, 0), ("CLSAI", "USNYC", 24, 1),
    ("USMIA", "CLSAI", 18, 0), ("USMIA", "CLVAP", 19, 0),  # Miami → Chile
]
_LANES = [(o, d, t, x, "E") for o, d, t, x in _BASE_LANES] + [(d, o, t, x, "W") for o, d, t, x in _BASE_LANES]

_VESSELS = [("MOCK ATLAS", 8200), ("MOCK BOREAL", 11000), ("MOCK CORAL", 6500), ("MOCK DELTA", 14000),
            ("MOCK ESTRELLA", 9400), ("MOCK FJORD", 7800), ("MOCK GALENA", 12500), ("MOCK HORIZONTE", 5200),
            ("MOCK ISLAS", 10100), ("MOCK JADE", 13300), ("MOCK KALMAR", 4800), ("MOCK LITORAL", 8900)]

_PRICE_COL = {"20DRY": "price_20dry", "40DRY": "price_40dry", "40HC": "price_40hc", "45HC": "price_45hc"}
_TEU = {"20DRY": 1, "40DRY": 2, "40HC": 2, "45HC": 3}


def lane_pairs() -> list[tuple[str, str]]:
    """Las rutas (origen, destino) de la BD simulada; el historial de envíos usa las mismas."""
    return [(o, d) for o, d, _t, _x, _dir in _LANES]


def _connect(path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(path))


def ensure_mock_db(path, today: date | None = None) -> None:
    """Crea la BD o la regenera si se construyó otro día. No hace nada si ya está vigente."""
    today = today or date.today()
    with closing(_connect(path)) as con:
        con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        row = con.execute("SELECT value FROM meta WHERE key='built_on'").fetchone()
        stamp = f"{today.isoformat()}|v{_VERSION}"
        if row and row[0] == stamp:
            return
        con.executescript("""
            DROP TABLE IF EXISTS sailings; DROP TABLE IF EXISTS vessels;
            CREATE TABLE vessels (imo TEXT PRIMARY KEY, name TEXT NOT NULL, teu_capacity INTEGER NOT NULL);
            CREATE TABLE sailings (
              id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE NOT NULL, vessel_imo TEXT NOT NULL REFERENCES vessels(imo),
              voyage TEXT NOT NULL, origin TEXT NOT NULL, destination TEXT NOT NULL, etd TEXT NOT NULL, eta TEXT NOT NULL,
              transshipments INTEGER NOT NULL, free_teu INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'USD',
              price_20dry REAL NOT NULL, price_40dry REAL NOT NULL, price_40hc REAL NOT NULL, price_45hc REAL NOT NULL);
            CREATE INDEX idx_lane ON sailings (origin, destination, etd);""")
        imos = [f"999{i + 1:04d}" for i in range(len(_VESSELS))]
        con.executemany("INSERT INTO vessels VALUES (?,?,?)", [(imo, n, c) for imo, (n, c) in zip(imos, _VESSELS)])
        horizon = add_months(today, 6)
        for lane_idx, (origin, dest, transit, tranship, direction) in enumerate(_LANES):
            etd = today + timedelta(days=(lane_idx % 7 - today.weekday()) % 7)  # salida semanal en un día fijo por ruta
            k = 0
            while etd <= horizon:
                rng = random.Random(f"{origin}-{dest}-{etd}")  # determinista por ruta y fecha
                season = 0.12 * math.sin(2 * math.pi * etd.timetuple().tm_yday / 365)
                p40 = (55 * transit + 300) * (1 + season + rng.uniform(-0.04, 0.04))
                free = rng.randint(0, 30) if rng.random() < 0.15 else rng.randint(40, 900)
                con.execute(
                    "INSERT INTO sailings (ref, vessel_imo, voyage, origin, destination, etd, eta, transshipments, free_teu,"
                    " price_20dry, price_40dry, price_40hc, price_45hc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"{origin}{dest}-{etd:%Y%m%d}", imos[(lane_idx * 5 + k) % len(imos)],
                     f"{(lane_idx * 7 + k) % 900 + 100}{direction}", origin, dest, etd.isoformat(),
                     (etd + timedelta(days=transit)).isoformat(), tranship, free,
                     round(p40 * 0.62), round(p40), round(p40 * 1.06), round(p40 * 1.18)))
                etd += timedelta(days=7)
                k += 1
        con.execute("INSERT OR REPLACE INTO meta VALUES ('built_on', ?)", (stamp,))
        con.commit()


class MockDBScheduleProvider:
    def __init__(self, path, today: date | None = None):
        self._path, self._today = path, today
        ensure_mock_db(path, today)

    def search(self, request: ShipmentRequest) -> list[Sailing]:
        ensure_mock_db(self._path, self._today)  # si el servidor lleva días arriba, se renueva la ventana
        start = request.departure_date
        with closing(_connect(self._path)) as con:
            found = con.execute(
                "SELECT s.ref, v.name, s.vessel_imo, s.voyage, s.etd, s.eta, s.transshipments FROM sailings s"
                " JOIN vessels v ON v.imo = s.vessel_imo WHERE s.origin=? AND s.destination=? AND s.etd BETWEEN ? AND ?"
                " ORDER BY s.etd LIMIT ?",
                (request.origin_port, request.destination_port, start.isoformat(),
                 (start + timedelta(days=WINDOW_DAYS)).isoformat(), MAX_RESULTS)).fetchall()
        return [Sailing(carrier=CARRIER, vessel_name=name, vessel_imo=imo, voyage=voyage, etd=etd, eta=eta,
                        transshipments=ts, ref=ref) for ref, name, imo, voyage, etd, eta, ts in found]


class MockDBRateProvider:
    def __init__(self, path):
        self._path = path

    def quote(self, request: ShipmentRequest, sailing: Sailing) -> Quote | None:
        col = _PRICE_COL.get(request.container_type, "price_40hc")  # nombre de columna de una lista fija
        with closing(_connect(self._path)) as con:
            row = con.execute(f"SELECT {col}, currency, free_teu FROM sailings WHERE ref=?", (sailing.ref,)).fetchone()
        if row is None:
            return None
        price, currency, free = row
        need = _TEU.get(request.container_type, 2) * request.container_count
        avail = (f"{free} TEU libres" if free >= need
                 else f"SIN CAPACIDAD SUFICIENTE: {free} TEU libres, se necesitan {need}")
        return Quote(price_per_container=price, currency=currency, availability=avail, source=CARRIER,
                     free_teu=free)
