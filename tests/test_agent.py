import json

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from conftest import call, scripted
from form_agent.agent import build_agent, run_agent
from form_agent.config import Settings

FINAL = AIMessage(content='```json\n{"filled": {"name": "Ana"}, "skipped": [], "submitted": true, "confirmation": "Received!"}\n```')
ASK = AIMessage(content="| Campo | Valor |\n|---|---|\n| Name | Ana |\n\n¿Envío?")


def fill_script(url):
    return [call("goto", url=url), call("snapshot"), call("type_text", ref="e1", text="Ana"),
            call("select_option", ref="e2", value="Blue"), call("click", ref="e3"),
            call("submit_form", ref="e4"), ASK, call("submit_form", ref="e4"), FINAL]


def settings():
    return Settings(_env_file=None, allowed_domains=["127.0.0.1"], max_steps=60)


def say(agent, text, tid="t"):
    return agent.invoke({"messages": [{"role": "user", "content": text}]}, config={"configurable": {"thread_id": tid}, "recursion_limit": 60})


def tool_msgs(r):
    return [m.content for m in r["messages"] if m.type == "tool"]


def test_submit_blocked_until_user_approves_in_natural_language(browser, tmp_path, form_url):
    agent = build_agent(settings(), browser, tmp_path, model=scripted(*fill_script(form_url)))
    r = say(agent, "llena el form")
    assert any(c.startswith("BLOQUEADO") for c in tool_msgs(r))
    assert "Received!" not in browser.page_text()  # sin aprobación no se envía
    r = say(agent, "sí, envíalo")
    assert "Received!" in browser.page_text()


def test_edit_request_is_not_approval(browser, tmp_path, form_url):
    agent = build_agent(settings(), browser, tmp_path, model=scripted(*fill_script(form_url), AIMessage(content="ok")))
    say(agent, "llena el form")
    r = say(agent, "sí pero cambia el nombre")
    assert "Received!" not in browser.page_text()
    assert sum(c.startswith("BLOQUEADO") for c in tool_msgs(r)) == 2


def test_run_agent_conversation_loop(browser, tmp_path, form_url):
    agent = build_agent(settings(), browser, tmp_path, model=scripted(*fill_script(form_url)))
    replies = []
    res = run_agent(agent, form_url, {"name": "Ana"}, settings(), tmp_path, reply=lambda t: replies.append(t) or "sí, envíalo")
    assert len(replies) == 1 and "¿Envío?" in replies[0]
    assert res["submitted"] and "Received!" in browser.page_text()


def test_run_agent_stops_when_user_gives_no_reply(browser, tmp_path, form_url):
    agent = build_agent(settings(), browser, tmp_path, model=scripted(*fill_script(form_url)))
    res = run_agent(agent, form_url, {"name": "Ana"}, settings(), tmp_path, reply=lambda t: "")
    assert not res["submitted"] and "Received!" not in browser.page_text()


def test_dry_run_never_submits(browser, tmp_path, form_url):
    script = fill_script(form_url)
    agent = build_agent(settings(), browser, tmp_path, model=scripted(*script[:6], FINAL), dry_run=True, auto_approve=True)
    r = say(agent, "x")
    assert "Received!" not in browser.page_text()
    assert any(c.startswith("DRY-RUN") for c in tool_msgs(r))


def test_blocked_domain_tells_agent_how_to_proceed(browser, tmp_path):
    model = scripted(call("goto", url="https://evil.test/"), AIMessage(content="no puedo"))
    agent = build_agent(settings(), browser, tmp_path, model=model, auto_approve=True)
    assert any("ALLOWED_DOMAINS" in c for c in tool_msgs(say(agent, "ve")))


def _reports(monkeypatch):
    import threading

    from form_agent import agent as agent_mod

    calls = []
    monkeypatch.setattr(agent_mod, "send_report", lambda *a, **k: calls.append(threading.current_thread()))
    return calls


def _with_email():
    return Settings(_env_file=None, resend_api_key="x", email_to="a@b.c", allowed_domains=["127.0.0.1"], max_steps=60)


def test_no_email_for_small_talk(browser, tmp_path, monkeypatch):
    calls = _reports(monkeypatch)
    agent = build_agent(_with_email(), browser, tmp_path, model=scripted(AIMessage(content="Hola, lleno formularios.")), final_report=True)
    say(agent, "hola, ¿qué haces?")
    assert calls == []


def test_no_email_before_submit(browser, tmp_path, form_url, monkeypatch):
    calls = _reports(monkeypatch)
    agent = build_agent(_with_email(), browser, tmp_path, model=scripted(*fill_script(form_url)[:7]), final_report=True)
    say(agent, "llena el form")  # termina pidiendo aprobación, sin enviar
    assert calls == []


def test_email_once_after_submit_off_event_loop(browser, tmp_path, form_url, monkeypatch):
    import asyncio
    import threading

    calls = _reports(monkeypatch)
    agent = build_agent(_with_email(), browser, tmp_path, final_report=True,
                        model=scripted(*fill_script(form_url), AIMessage(content="de nada")))

    async def go():
        cfg = {"configurable": {"thread_id": "t9"}, "recursion_limit": 60}
        for text in ("llena el form", "sí, envíalo", "gracias"):
            await agent.ainvoke({"messages": [{"role": "user", "content": text}]}, config=cfg)
        return threading.current_thread()

    loop_thread = asyncio.run(go())
    assert len(calls) == 1  # un correo por envío, no por turno
    assert calls[0] is not loop_thread  # y sin bloquear el event loop
