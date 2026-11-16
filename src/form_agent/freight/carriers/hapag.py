"""Hapag-Lloyd: horarios por el estándar DCSA Commercial Schedules (point-to-point).

SUPUESTOS SIN VERIFICAR contra el sandbox real (el portal no es accesible sin registro):
  - la ruta es `<base_url>/point-to-point-routes` y la versión va incluida en base_url;
  - la autenticación son los headers X-IBM-Client-Id / X-IBM-Client-Secret;
  - la respuesta es una lista de routings con `legs[].transport` y `legs[].departure/arrival.dateTime`.
Al tener una respuesta real del sandbox, ajustar aquí y en tests/test_freight_hapag.py.
"""
from __future__ import annotations

from datetime import date, timedelta

import httpx

from ..models import Sailing, ShipmentRequest

CARRIER = "HAPAG-LLOYD"


class ProviderError(RuntimeError):
    """La naviera respondió con error o con algo que no entendemos."""


def _local_date(dt: str) -> date:
    # DCSA entrega la hora local del puerto con su offset: la fecha local son los 10 primeros caracteres.
    return date.fromisoformat(dt[:10])


class HapagScheduleProvider:
    def __init__(self, client: httpx.Client, client_id: str, client_secret: str, window_days: int = 14):
        self._client = client
        self._headers = {"X-IBM-Client-Id": client_id, "X-IBM-Client-Secret": client_secret}
        self._window = window_days

    def search(self, request: ShipmentRequest) -> list[Sailing]:
        params = {
            "placeOfReceipt": request.origin_port,
            "placeOfDelivery": request.destination_port,
            "departureStartDate": request.departure_date.isoformat(),
            "departureEndDate": (request.departure_date + timedelta(days=self._window)).isoformat(),
        }
        try:
            resp = self._client.get("point-to-point-routes", params=params, headers=self._headers)
        except httpx.HTTPError as e:
            raise ProviderError(f"Hapag-Lloyd no respondió: {e}") from e
        if resp.status_code != 200:
            raise ProviderError(f"Hapag-Lloyd respondió HTTP {resp.status_code}: {resp.text[:200]}")
        sailings = (self._to_sailing(r) for r in resp.json())
        return [s for s in sailings if s is not None]

    @staticmethod
    def _to_sailing(routing: dict) -> Sailing | None:
        vessel_legs = [leg for leg in routing.get("legs", [])
                       if leg.get("transport", {}).get("modeOfTransport") == "VESSEL"]
        if not vessel_legs:
            return None
        first, last = vessel_legs[0], vessel_legs[-1]
        t = first["transport"]
        arrival = last.get("arrival", {}).get("dateTime")
        return Sailing(carrier=CARRIER, vessel_name=t.get("vesselName", "?"), vessel_imo=t.get("vesselIMONumber"),
                       voyage=t.get("carrierExportVoyageNumber"),
                       etd=_local_date(first["departure"]["dateTime"]),
                       eta=_local_date(arrival) if arrival else None,
                       transshipments=len(vessel_legs) - 1)
