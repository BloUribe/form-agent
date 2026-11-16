from pathlib import Path

from form_agent import tools as tools_mod
from form_agent.config import Settings
from form_agent.tools import make_tools


def get_tool(name, browser, tmp_path, settings):
    return next(t for t in make_tools(browser, tmp_path, settings=settings) if t.name == name)


def test_send_email_with_screenshot(browser, tmp_path, form_url, monkeypatch):
    sent = {}
    monkeypatch.setattr(tools_mod, "send_message", lambda s, subj, body, files: sent.update(subj=subj, body=body, files=files) or "id1")
    s = Settings(_env_file=None, resend_api_key="x", email_to="a@b.c")
    browser.goto(form_url)
    out = get_tool("send_email", browser, tmp_path, s).invoke({"kind": "help", "subject": "S", "body": "a<b", "attach_screenshot": True})
    assert out.startswith("ok") and "help]" in sent["subj"] and "a&lt;b" in sent["body"]
    assert len(sent["files"]) == 1 and Path(sent["files"][0]).exists()


def test_send_email_without_config_or_bad_kind(browser, tmp_path):
    t = get_tool("send_email", browser, tmp_path, Settings(_env_file=None))
    assert t.invoke({"kind": "help", "subject": "S", "body": "b"}).startswith("ERROR")
    t = get_tool("send_email", browser, tmp_path, Settings(_env_file=None, resend_api_key="x", email_to="a@b.c"))
    assert t.invoke({"kind": "spam", "subject": "S", "body": "b"}).startswith("ERROR")


def test_send_email_failure_is_returned_not_raised(browser, tmp_path, monkeypatch):
    def boom(*a, **k): raise RuntimeError("resend down")
    monkeypatch.setattr(tools_mod, "send_message", boom)
    s = Settings(_env_file=None, resend_api_key="x", email_to="a@b.c")
    assert "resend down" in get_tool("send_email", browser, tmp_path, s).invoke({"kind": "progress", "subject": "S", "body": "b"})
