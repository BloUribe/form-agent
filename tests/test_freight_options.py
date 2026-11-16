from datetime import date

import pytest
from pydantic import ValidationError

from form_agent.freight.carriers.mock import MockRateProvider, MockScheduleProvider
from form_agent.freight.models import ShipmentRequest
from form_agent.freight.service import find_options


def make_request(**over):
    base = dict(origin_port="CLSAI", destination_port="CNSHA", container_count=2,
                container_type="40HC", weight_kg=24000, departure_date=date(2026, 12, 1))
    return ShipmentRequest(**{**base, **over})


def test_request_rejects_zero_containers():
    with pytest.raises(ValidationError):
        make_request(container_count=0)


def test_request_normalizes_port_codes_to_uppercase():
    assert make_request(origin_port="clsai").origin_port == "CLSAI"


def test_find_options_departures_are_on_or_after_requested_date():
    opts = find_options(make_request(), MockScheduleProvider(), MockRateProvider())
    assert opts, "el proveedor simulado debe devolver al menos una salida"
    assert all(o.etd >= date(2026, 12, 1) for o in opts)


def test_find_options_are_sorted_by_departure_and_priced_for_all_containers():
    req = make_request(container_count=3)
    opts = find_options(req, MockScheduleProvider(), MockRateProvider())
    assert [o.etd for o in opts] == sorted(o.etd for o in opts)
    one = find_options(make_request(container_count=1), MockScheduleProvider(), MockRateProvider())
    assert opts[0].total_price == pytest.approx(one[0].total_price * 3)


def test_find_options_assigns_stable_ids_starting_at_one():
    opts = find_options(make_request(), MockScheduleProvider(), MockRateProvider())
    assert [o.id for o in opts] == list(range(1, len(opts) + 1))


def test_options_without_price_are_kept_with_none_when_rate_provider_has_no_quote():
    class NoQuote:
        def quote(self, request, sailing):
            return None

    opts = find_options(make_request(), MockScheduleProvider(), NoQuote())
    assert opts and all(o.total_price is None for o in opts)
