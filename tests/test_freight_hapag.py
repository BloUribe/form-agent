"""Cliente Hapag-Lloyd (DCSA Commercial Schedules, point-to-point).

OJO: el fixture sigue la forma del estándar DCSA, NO una respuesta real del sandbox. Cuando se capture una
respuesta real hay que reemplazar el fixture y ajustar el parser si difiere.
"""
from datetime import date

import httpx
import pytest

from form_agent.freight.carriers.hapag import HapagScheduleProvider, ProviderError
from form_agent.freight.models import ShipmentRequest

ROUTING = {
    "placeOfReceipt": {"UNLocationCode": "CLSAI"},
    "placeOfDelivery": {"UNLocationCode": "CNSHA"},
    "transitTime": 40,
    "legs": [
        {"sequenceNumber": 1,
         "transport": {"modeOfTransport": "VESSEL", "vesselName": "HAMBURG EXPRESS", "vesselIMONumber": "9123456",
                       "carrierExportVoyageNumber": "012E"},
         "departure": {"dateTime": "2026-12-03T10:00:00-03:00"},
         "arrival": {"dateTime": "2026-12-20T08:00:00+08:00"}},
        {"sequenceNumber": 2,
         "transport": {"modeOfTransport": "VESSEL", "vesselName": "FEEDER TWO", "vesselIMONumber": "9999999",
                       "carrierExportVoyageNumber": "044W"},
         "departure": {"dateTime": "2026-12-22T10:00:00+08:00"},
         "arrival": {"dateTime": "2027-01-12T08:00:00+08:00"}},
    ],
}


def make_request():
    return ShipmentRequest(origin_port="CLSAI", destination_port="CNSHA", container_count=1,
                           container_type="40HC", departure_date=date(2026, 12, 1))


def provider(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://sandbox.example/api")
    return HapagScheduleProvider(client=client, client_id="id-123", client_secret="sec-456", window_days=14)


def test_search_sends_dcsa_query_and_credentials():
    seen = {}

    def handler(req: httpx.Request):
        seen["path"], seen["params"], seen["headers"] = req.url.path, dict(req.url.params), req.headers
        return httpx.Response(200, json=[ROUTING])

    provider(handler).search(make_request())
    assert seen["path"].endswith("/point-to-point-routes")
    assert seen["params"]["placeOfReceipt"] == "CLSAI"
    assert seen["params"]["placeOfDelivery"] == "CNSHA"
    assert seen["params"]["departureStartDate"] == "2026-12-01"
    assert seen["params"]["departureEndDate"] == "2026-12-15"  # ventana de 14 días
    assert seen["headers"]["x-ibm-client-id"] == "id-123"
    assert seen["headers"]["x-ibm-client-secret"] == "sec-456"


def test_search_maps_first_leg_to_sailing_and_counts_transshipments():
    sailings = provider(lambda r: httpx.Response(200, json=[ROUTING])).search(make_request())
    assert len(sailings) == 1
    s = sailings[0]
    assert (s.carrier, s.vessel_name, s.vessel_imo, s.voyage) == ("HAPAG-LLOYD", "HAMBURG EXPRESS", "9123456", "012E")
    assert s.etd == date(2026, 12, 3)  # fecha local del puerto de salida, sin convertir a UTC
    assert s.eta == date(2027, 1, 12)  # llegada del último tramo
    assert s.transshipments == 1


def test_search_returns_empty_list_when_no_routes():
    assert provider(lambda r: httpx.Response(200, json=[])).search(make_request()) == []


def test_search_skips_routings_without_a_vessel_leg():
    truck_only = {"legs": [{"transport": {"modeOfTransport": "TRUCK"}, "departure": {"dateTime": "2026-12-02T08:00:00Z"}}]}
    assert provider(lambda r: httpx.Response(200, json=[truck_only])).search(make_request()) == []


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_search_raises_provider_error_on_http_failure(status):
    with pytest.raises(ProviderError) as exc:
        provider(lambda r: httpx.Response(status, text="nope")).search(make_request())
    assert str(status) in str(exc.value)
