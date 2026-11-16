"""Un correo entrante = un turno del agente en el hilo del cliente."""
from __future__ import annotations

import html
from collections import defaultdict

from ..config import Settings
from ..replytext import extract_reply
from ..subject import strip_reply_prefix
from . import tools as ftools
from .agent import build_freight_agent
from .carriers.base import RateProvider, ScheduleProvider


def _text(content) -> str:
    return content if isinstance(content, str) else "".join(b.get("text", "") for b in content if isinstance(b, dict))


def _emailed_this_turn(messages) -> bool:
    """¿Hubo un send_options_email exitoso desde el último mensaje del cliente?"""
    for m in reversed(messages):
        if m.type == "human":
            return False
        if m.type == "tool" and m.name == "send_options_email" and str(m.content).startswith("ok"):
            return True
    return False


def make_handler(settings: Settings, schedules: ScheduleProvider, rates: RateProvider, checkpointer, model=None):
    # Opciones de búsqueda por conversación; el agente se reconstruye en cada correo y estas deben persistir.
    stores: dict[str, dict] = defaultdict(dict)

    def handle(sender: str, subject: str, body: str, thread_id: str) -> dict:
        reply_subject = f"Re: {strip_reply_prefix(subject)}"
        agent = build_freight_agent(settings, schedules, rates, recipient=sender, model=model, checkpointer=checkpointer,
                                    store=stores[thread_id], subject=reply_subject)
        cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": settings.max_steps}
        reply = extract_reply(body)
        # Solo el primer correo lleva encabezado: la aprobación (is_affirmative) mira el ÚLTIMO mensaje del cliente
        # y exige que sea corto, así que en las respuestas debe ir únicamente el texto nuevo.
        is_new_thread = not agent.get_state(cfg).values.get("messages")
        text = f"De: {sender}\nAsunto: {subject}\n\n{reply}" if is_new_thread else reply
        result = agent.invoke({"messages": [{"role": "user", "content": text}]}, config=cfg)
        final = _text(result["messages"][-1].content).strip()
        if final and not _emailed_this_turn(result["messages"]):
            # el modelo no respondió por correo: el cliente no debe quedarse sin respuesta
            ftools.send_message(settings, reply_subject, f"<p>{html.escape(final).replace(chr(10), '<br>')}</p>", to=sender)
        return result

    return handle
