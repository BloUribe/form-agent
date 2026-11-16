from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from conftest import call, scripted
from form_agent.config import Settings
from form_agent.freight import tools as ftools
from form_agent.freight.carriers.mock import MockRateProvider, MockScheduleProvider
from form_agent.freight.handler import make_handler

SEARCH = dict(origin_port="CLSAI", destination_port="CNSHA", container_count=2, container_type="40HC",
              weight_kg=24000, departure_date="2026-12-01")
SENDER, SUBJECT = "cliente@empresa.com", "Cotización CLSAI-CNSHA"


def settings():
    return Settings(_env_file=None, resend_api_key="x", email_to="owner@x.com")


def setup(monkeypatch, *script):
    sent = []
    monkeypatch.setattr(ftools, "send_message",
                        lambda s, subject, body, files=None, to=None: sent.append(dict(to=to, subject=subject, body=body)) or "id")
    handler = make_handler(settings(), MockScheduleProvider(), MockRateProvider(), MemorySaver(), model=scripted(*script))
    return handler, sent


def tool_msgs(result):
    return [m.content for m in result["messages"] if m.type == "tool"]


def test_reply_subject_is_fixed_to_re_original_regardless_of_what_the_model_writes(monkeypatch):
    handler, sent = setup(monkeypatch, call("send_options_email", subject="OTRO ASUNTO", body="hola"), AIMessage(content="fin"))
    handler(sender=SENDER, subject=SUBJECT, body="cotiza", thread_id="t1")
    assert sent == [dict(to=SENDER, subject=f"Re: {SUBJECT}", body="<p>hola</p>")]


def test_subject_does_not_stack_re_prefixes(monkeypatch):
    handler, sent = setup(monkeypatch, call("send_options_email", subject="x", body="hola"), AIMessage(content="fin"))
    handler(sender=SENDER, subject=f"RE: Re: {SUBJECT}", body="la segunda", thread_id="t1")
    assert sent[0]["subject"] == f"Re: {SUBJECT}"


def test_falls_back_to_emailing_final_text_when_model_forgot_to_send(monkeypatch):
    handler, sent = setup(monkeypatch, AIMessage(content="Necesito la fecha de salida."))
    handler(sender=SENDER, subject=SUBJECT, body="cotiza", thread_id="t1")
    assert len(sent) == 1 and sent[0]["to"] == SENDER and "Necesito la fecha" in sent[0]["body"]


def test_no_fallback_when_model_already_emailed(monkeypatch):
    handler, sent = setup(monkeypatch, call("send_options_email", subject="s", body="listo"), AIMessage(content="resumen interno"))
    handler(sender=SENDER, subject=SUBJECT, body="cotiza", thread_id="t1")
    assert len(sent) == 1


def test_options_found_in_one_email_can_be_booked_from_the_next_reply(monkeypatch):
    handler, _ = setup(monkeypatch,
                       call("search_sailings", **SEARCH), call("send_options_email", subject="s", body="opciones"), AIMessage(content="ok"),
                       call("book_option", option_id=2), call("send_options_email", subject="s", body="reservado"), AIMessage(content="ok"))
    handler(sender=SENDER, subject=SUBJECT, body="cotiza 2x40HC", thread_id="t1")
    r = handler(sender=SENDER, subject=f"Re: {SUBJECT}", body="sí, confirmo la 2", thread_id="t1")
    assert any("RESERVA SIMULADA" in c and "MOCK BOREAL" in c for c in tool_msgs(r))


def test_approval_works_when_reply_carries_quoted_history_and_signature(monkeypatch):
    handler, _ = setup(monkeypatch,
                       call("search_sailings", **SEARCH), AIMessage(content="ok"),
                       call("book_option", option_id=2), AIMessage(content="ok"))
    handler(sender=SENDER, subject=SUBJECT, body="cotiza 2x40HC", thread_id="t1")
    reply = ("sí, confirmo la 2\n\nEl lun, 16 nov 2026 a las 10:00, Agente <a@x.com> escribió:\n> | 1 | MOCK ATLAS |\n"
             "> ¿Cuál opción quieres reservar?\n-- \nJuan Pérez | Gerente de Logística | Empresa SA")
    r = handler(sender=SENDER, subject=f"Re: {SUBJECT}", body=reply, thread_id="t1")
    assert any("RESERVA SIMULADA" in c for c in tool_msgs(r))


def test_only_the_first_email_of_a_thread_carries_the_sender_and_subject_header(monkeypatch):
    handler, _ = setup(monkeypatch, AIMessage(content="a"), AIMessage(content="b"))
    handler(sender=SENDER, subject=SUBJECT, body="cotiza", thread_id="t1")
    r = handler(sender=SENDER, subject=f"Re: {SUBJECT}", body="sí, la 2", thread_id="t1")
    humans = [m.content for m in r["messages"] if m.type == "human"]
    assert humans[0].startswith("De: cliente@empresa.com\nAsunto: " + SUBJECT)
    assert humans[1] == "sí, la 2"


def test_threads_do_not_share_search_results(monkeypatch):
    handler, _ = setup(monkeypatch,
                       call("search_sailings", **SEARCH), AIMessage(content="ok"),
                       AIMessage(content="hola"),
                       call("book_option", option_id=2), AIMessage(content="ok"))
    handler(sender=SENDER, subject=SUBJECT, body="cotiza", thread_id="t1")  # busca en t1
    handler(sender="otro@empresa.com", subject="Otra cosa", body="hola", thread_id="t2")  # t2 nunca buscó
    r = handler(sender="otro@empresa.com", subject="Re: Otra cosa", body="sí, la 2", thread_id="t2")
    assert any(c.startswith("ERROR") and "2" in c for c in tool_msgs(r))
