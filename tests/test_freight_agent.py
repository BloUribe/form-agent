from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from conftest import call, scripted
from form_agent.config import Settings
from form_agent.freight import tools as ftools
from form_agent.freight.agent import build_freight_agent
from form_agent.freight.carriers.base import ScheduleProvider
from form_agent.freight.carriers.hapag import ProviderError
from form_agent.freight.carriers.mock import MockRateProvider, MockScheduleProvider
from form_agent.freight.tools import make_freight_tools

SEARCH = dict(origin_port="CLSAI", destination_port="CNSHA", container_count=2, container_type="40HC",
              weight_kg=24000, departure_date="2026-12-01")


def settings():
    return Settings(_env_file=None, resend_api_key="x", email_to="owner@x.com")


def tools(schedules=None, recipient="cliente@empresa.com", **kw):
    ts = make_freight_tools(settings(), schedules or MockScheduleProvider(), MockRateProvider(), recipient, **kw)
    return {t.name: t for t in ts}


def test_search_sailings_lists_numbered_options_with_vessel_and_total_price():
    out = tools()["search_sailings"].invoke(SEARCH)
    assert "MOCK ATLAS" in out and "2026-12-01" in out
    assert out.count("\n") >= 3 and "| 1 |" in out
    assert "USD 6200" in out  # 2 contenedores × 3100


def test_search_sailings_returns_error_string_on_bad_input():
    out = tools()["search_sailings"].invoke({**SEARCH, "departure_date": "mañana"})
    assert out.startswith("ERROR")


def test_search_sailings_returns_error_string_when_carrier_fails():
    class Down:
        def search(self, request):
            raise ProviderError("HTTP 500")

    out = tools(schedules=Down())["search_sailings"].invoke(SEARCH)
    assert out.startswith("ERROR") and "500" in out


def test_search_sailings_says_so_when_there_are_no_departures():
    class Empty:
        def search(self, request):
            return []

    assert "no hay salidas" in tools(schedules=Empty())["search_sailings"].invoke(SEARCH).lower()


def test_send_options_email_goes_only_to_the_fixed_recipient(monkeypatch):
    sent = {}
    monkeypatch.setattr(ftools, "send_message", lambda s, subject, body, files=None, to=None: sent.update(to=to, body=body, subject=subject) or "id1")
    out = tools()["send_options_email"].invoke({"subject": "Opciones", "body": "a<b\nlínea 2"})
    assert out.startswith("ok")
    assert sent["to"] == "cliente@empresa.com"
    assert "a&lt;b<br>" in sent["body"] and sent["subject"] == "Opciones"


def test_send_options_email_without_config_returns_error():
    ts = make_freight_tools(Settings(_env_file=None), MockScheduleProvider(), MockRateProvider(), "c@e.com")
    out = next(t for t in ts if t.name == "send_options_email").invoke({"subject": "s", "body": "b"})
    assert out.startswith("ERROR")


def run(agent, text, tid="t"):
    return agent.invoke({"messages": [{"role": "user", "content": text}]},
                        config={"configurable": {"thread_id": tid}, "recursion_limit": 40})


def tool_msgs(r):
    return [m.content for m in r["messages"] if m.type == "tool"]


def agent_with(*script):
    return build_freight_agent(settings(), MockScheduleProvider(), MockRateProvider(), "cliente@empresa.com",
                               model=scripted(*script), checkpointer=MemorySaver())


def test_book_option_is_blocked_until_user_approves():
    ag = agent_with(call("search_sailings", **SEARCH), call("book_option", option_id=2), AIMessage(content="¿Confirmas?"))
    r = run(ag, "cotiza")
    assert any(c.startswith("BLOQUEADO") for c in tool_msgs(r))
    assert not any("RESERVA SIMULADA" in c for c in tool_msgs(r))


def test_book_option_proceeds_after_natural_language_yes():
    ag = agent_with(call("search_sailings", **SEARCH), call("book_option", option_id=99), AIMessage(content="pregunto"),
                    call("book_option", option_id=2), AIMessage(content="listo"))
    run(ag, "cotiza")  # búsqueda + intento bloqueado
    r = run(ag, "sí, confirmo la 2")
    assert any("RESERVA SIMULADA" in c and "MOCK BOREAL" in c for c in tool_msgs(r))


def test_book_option_with_unknown_id_returns_error_even_when_approved():
    ag = agent_with(call("search_sailings", **SEARCH), AIMessage(content="ok"), call("book_option", option_id=99), AIMessage(content="x"))
    run(ag, "cotiza")
    r = run(ag, "sí")
    assert any(c.startswith("ERROR") and "99" in c for c in tool_msgs(r))
