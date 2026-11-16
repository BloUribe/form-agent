import json
from pathlib import Path

import pytest

from form_agent.browser import Browser

FIXTURE = (Path(__file__).parent / "fixtures" / "form.html").resolve().as_uri()


@pytest.fixture
def br():
    # file:// no tiene hostname; se prueba la lógica de dominios aparte
    b = Browser(allowed_domains=[""], timeout_ms=3000)
    yield b
    b.close()


def test_fill_and_submit(br):
    assert br.goto(FIXTURE).startswith("ok")
    refs = {e["label"]: e["ref"] for e in json.loads(br.snapshot())}
    assert br.type(refs["Name"], "Ana") == "ok"
    assert br.select(refs["Color"], "Blue") == "ok"
    assert br.click(refs["Agree"]) == "ok"
    assert br.click(refs["Send"]) == "ok"
    assert "Received!" in br.page_text()


def test_domain_blocked():
    b = Browser(allowed_domains=["example.com"], timeout_ms=3000)
    try:
        assert b.goto("https://evil.test/").startswith("ERROR: dominio")
    finally:
        b.close()


def test_bad_ref_returns_error_not_exception(br):
    br.goto(FIXTURE)
    br.snapshot()
    assert br.click("e999").startswith("ERROR")


def test_works_from_another_thread(br):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(1) as ex:
        assert ex.submit(br.goto, FIXTURE).result().startswith("ok")
