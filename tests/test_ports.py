from form_agent.ports import port_label, route_label


def test_known_ports_get_a_readable_name_with_their_code():
    assert port_label("USMIA") == "Miami (USMIA)"
    assert port_label("CLSAI") == "San Antonio (CLSAI)"


def test_unknown_port_falls_back_to_the_code():
    assert port_label("ZZZZZ") == "ZZZZZ"


def test_route_label_joins_origin_and_destination():
    assert route_label("USMIA", "CLSAI") == "Miami (USMIA) → San Antonio (CLSAI)"
