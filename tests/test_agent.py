import json

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from conftest import call, scripted
from form_agent.agent import build_agent, run_agent
from form_agent.config import Settings

FINAL = AIMessage(content='```json\n{"filled": {"name": "Ana"}, "skipped": [], "submitted": true, "confirmation": "Received!"}\n```')


def fill_script(url):
    return [call("goto", url=url), call("snapshot"), call("type_text", ref="e1", text="Ana"),
            call("select_option", ref="e2", value="Blue"), call("click", ref="e3"),
            call("submit_form", ref="e4"), FINAL]


def make(browser, tmp_path, url, **kw):
    s = Settings(_env_file=None, allowed_domains=["127.0.0.1"], max_steps=60)
    return s, build_agent(s, browser, tmp_path, model=scripted(*fill_script(url)), **kw)


def test_fills_asks_approval_and_submits(browser, tmp_path, form_url):
    s, agent = make(browser, tmp_path, form_url)
    asked = []
    res = run_agent(agent, form_url, {"name": "Ana"}, s, tmp_path, approve=lambda: asked.append(1) or True)
    assert asked == [1]  # se pidió aprobación antes de enviar
    assert "Received!" in browser.page_text()
    assert json.loads(res["final"].split("```json")[1].split("```")[0])["submitted"] is True


def test_rejected_submit_does_not_submit(browser, tmp_path, form_url):
    s, agent = make(browser, tmp_path, form_url)
    run_agent(agent, form_url, {"name": "Ana"}, s, tmp_path, approve=lambda: False)
    assert "Received!" not in browser.page_text()


def test_dry_run_never_submits(browser, tmp_path, form_url):
    s, agent = make(browser, tmp_path, form_url, dry_run=True, auto_approve=True)
    run_agent(agent, form_url, {"name": "Ana"}, s, tmp_path)
    assert "Received!" not in browser.page_text()


def test_ask_human_pauses_and_resumes(browser, tmp_path, form_url):
    model = scripted(call("ask_human", question="¿Cuál es tu nombre?"), AIMessage(content="gracias"))
    agent = build_agent(Settings(_env_file=None), browser, tmp_path, model=model, auto_approve=True)
    cfg = {"configurable": {"thread_id": "t1"}}
    r = agent.invoke({"messages": [{"role": "user", "content": "hola"}]}, config=cfg)
    assert r["__interrupt__"][0].value == {"question": "¿Cuál es tu nombre?"}
    r = agent.invoke(Command(resume="Ana"), config=cfg)
    tool_msgs = [m.content for m in r["messages"] if m.type == "tool"]
    assert "Ana" in tool_msgs


def test_blocked_domain_tells_agent_how_to_proceed(browser, tmp_path):
    model = scripted(call("goto", url="https://evil.test/"), AIMessage(content="no puedo"))
    agent = build_agent(Settings(_env_file=None), browser, tmp_path, model=model, auto_approve=True)
    r = agent.invoke({"messages": [{"role": "user", "content": "ve"}]}, config={"configurable": {"thread_id": "t2"}})
    assert any("ALLOWED_DOMAINS" in m.content for m in r["messages"] if m.type == "tool")


def test_final_report_sent_off_event_loop(browser, tmp_path, form_url, monkeypatch):
    import asyncio
    import threading

    from form_agent import agent as agent_mod

    calls = []
    monkeypatch.setattr(agent_mod, "send_report", lambda *a, **k: calls.append(threading.current_thread()))
    s = Settings(_env_file=None, resend_api_key="x", email_to="a@b.c")
    model = scripted(call("goto", url=form_url), FINAL)
    agent = build_agent(s, browser, tmp_path, model=model, auto_approve=True, final_report=True)

    async def go():
        await agent.ainvoke({"messages": [{"role": "user", "content": "x"}]}, config={"configurable": {"thread_id": "t3"}})
        return threading.current_thread()

    loop_thread = asyncio.run(go())
    assert len(calls) == 1  # el reporte se envió una vez
    assert calls[0] is not loop_thread  # y no bloqueó el event loop
