import pytest

from form_agent.replytext import extract_reply


def test_plain_reply_is_unchanged():
    assert extract_reply("sí, confirmo la 2") == "sí, confirmo la 2"


@pytest.mark.parametrize("body", [
    "sí, confirmo\n\nEl lun, 16 nov 2026 a las 10:00, Agente <a@x.com> escribió:\n> opciones\n> 1. MOCK ATLAS",
    "sí, confirmo\n\nOn Mon, Nov 16, 2026 at 10:00 AM Agent <a@x.com> wrote:\n> options",
    "sí, confirmo\n\n-----Original Message-----\nFrom: a@x.com\nopciones",
    "sí, confirmo\n\n-----Mensaje original-----\nDe: a@x.com\nopciones",
    "sí, confirmo\n> opciones citadas\n> más citado",
    "sí, confirmo\n-- \nJuan Pérez\nGerente",
])
def test_quoted_history_and_signature_are_removed(body):
    assert extract_reply(body) == "sí, confirmo"


def test_multiline_reply_keeps_all_new_lines():
    assert extract_reply("la 2 por favor\ny avísame cuando esté\n\n> viejo") == "la 2 por favor\ny avísame cuando esté"


def test_falls_back_to_full_body_if_nothing_would_remain():
    body = "> todo está citado"
    assert extract_reply(body) == body
