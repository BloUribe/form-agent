import pytest

from form_agent.approval import is_affirmative


@pytest.mark.parametrize("text", ["sí", "Sí, envíalo", "ok", "dale, adelante", "Perfecto, envialo!", "yes", "si envía"])
def test_affirmative(text):
    assert is_affirmative(text)


@pytest.mark.parametrize("text", ["no", "sí pero cambia el nombre", "espera, omite el textarea", "cambia password a X",
                                  "", "llena y envía", "ok " + "palabra " * 10])
def test_not_affirmative(text):
    assert not is_affirmative(text)
