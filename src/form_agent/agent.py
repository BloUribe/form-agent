from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

from deepagents import create_deep_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import MemorySaver

from .browser import Browser
from .config import Settings
from .email import parse_final, send_report
from .tools import make_tools

SYSTEM_PROMPT = """Eres un agente que llena formularios web usando un navegador. Hablas con el usuario en español y en chat.
Si el usuario solo saluda o pregunta qué haces, responde breve SIN usar herramientas.

Flujo para una tarea de formulario (la URL y los datos vienen en el chat o como JSON):
1. goto y snapshot para descubrir los campos.
2. PROPUESTA: responde con una tabla markdown `| Campo | Tipo | Valor propuesto | Nota |` con TODOS los campos encontrados.
   Usa los datos del usuario; los que no tienen dato van como `— (omitir)`; los obligatorios sin dato como `❓ falta`.
   Nunca inventes datos. Cierra con: «¿Lo lleno así? Dime qué campos cambiar u omitir.» y TERMINA tu turno (no llenes aún).
3. El usuario responde en lenguaje natural («cambia el password por X», «omite el textarea», «así está bien»).
   Aplica los cambios y llena el formulario con click, type_text, select_option. Si algo falla (ERROR), haz snapshot y reintenta distinto (máx. 2 veces).
   Los checkbox/radio ya marcados no se tocan salvo que el usuario lo pida.
4. Haz snapshot de verificación y muestra la tabla FINAL de valores realmente puestos. Pregunta «¿Lo envío?» y TERMINA tu turno.
5. Solo cuando el usuario apruebe en su mensaje («sí», «envíalo»), llama submit_form. Si responde BLOQUEADO, pide la aprobación y termina el turno.
6. Tras enviar: page_text y screenshot para ver el resultado (éxito o error). Responde con un resumen breve y al final este JSON:
   {"filled": {campo: valor}, "skipped": [...], "submitted": true/false, "confirmation": "texto de la página tras enviar"}.
   El correo con el resumen y el pantallazo se envía solo después de enviar: no lo envíes tú.
- Si hay un bloqueo (captcha, login, dominio no permitido), explícalo al usuario y pregunta cómo seguir.
- send_email solo si el usuario te pide expresamente avisos por correo.
"""


def _submit_results(messages) -> list:
    """ToolMessages de submit_form que sí intentaron enviar (no los BLOQUEADO)."""
    return [m for m in messages if getattr(m, "type", "") == "tool" and getattr(m, "name", "") == "submit_form"
            and not str(m.content).startswith("BLOQUEADO")]


def make_final_report(settings: Settings, get_browser, run_dir: Path, dry_run: bool):
    """Middleware after_agent: un correo (resumen + screenshot) por cada envío de formulario, no por cada turno."""
    reported: set[str] = set()

    def _send(state) -> None:
        if not (settings.resend_api_key and settings.email_to):
            return
        try:
            msgs = state["messages"]
            pending = [m for m in _submit_results(msgs) if m.tool_call_id not in reported]
            if not pending:
                return
            reported.update(m.tool_call_id for m in pending)
            text = msgs[-1].content
            if isinstance(text, list):
                text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
            url = next((c["args"].get("url") for m in msgs for c in (getattr(m, "tool_calls", None) or [])
                        if c["name"] == "goto"), "(sin URL)")
            res = {"steps": len(msgs), "input_tokens": 0, "output_tokens": 0}
            for m in msgs:
                u = getattr(m, "usage_metadata", None) or {}
                res["input_tokens"] += u.get("input_tokens", 0)
                res["output_tokens"] += u.get("output_tokens", 0)
            shot = run_dir / "final.png"
            get_browser().screenshot(str(shot))
            send_report(settings, parse_final(text), res, url, shot, dry_run)
        except Exception as e:  # el correo nunca debe romper la ejecución
            print(f"[final report error: {e}]")

    class FinalReport(AgentMiddleware):
        def after_agent(self, state, runtime):
            _send(state)

        async def aafter_agent(self, state, runtime):
            # Resend es síncrono: en LangGraph Server (loop asíncrono) debe ir en un hilo aparte.
            await asyncio.to_thread(_send, state)

    return FinalReport()


def build_agent(settings: Settings, browser, run_dir: Path, dry_run: bool = False, auto_approve: bool = False,
                model=None, use_checkpointer: bool = True, final_report: bool = False):
    """`browser`: Browser o función que lo crea. Studio pasa use_checkpointer=False (la plataforma pone el suyo)."""
    model = model or ChatAnthropic(model=settings.model, api_key=settings.anthropic_api_key, max_tokens=4096)
    get = browser if callable(browser) else (lambda: browser)
    return create_deep_agent(
        model=model,
        tools=make_tools(browser, run_dir, dry_run=dry_run, settings=settings, require_approval=not auto_approve),
        system_prompt=SYSTEM_PROMPT,
        middleware=[make_final_report(settings, get, run_dir, dry_run)] if final_report else [],
        checkpointer=MemorySaver() if use_checkpointer else None,
    )


def _text(content) -> str:
    return content if isinstance(content, str) else "".join(b.get("text", "") for b in content if isinstance(b, dict))


def run_agent(agent, url: str, profile: dict, settings: Settings, run_dir: Path, reply=None, max_turns: int = 10) -> dict:
    """Conversa con el agente: tras cada turno, si no se envió el form, pide reply(texto_del_agente) al usuario."""
    cfg = {"configurable": {"thread_id": uuid.uuid4().hex}, "recursion_limit": settings.max_steps}
    text = f"URL: {url}\nPerfil a usar:\n{json.dumps(profile, ensure_ascii=False, indent=2)}"
    log = (run_dir / "steps.jsonl").open("a")
    start, seen, submitted = time.time(), 0, False
    for _ in range(max_turns):
        result = agent.invoke({"messages": [{"role": "user", "content": text}]}, config=cfg)
        for m in result["messages"][seen:]:
            log.write(json.dumps({"type": m.type, "content": _text(m.content), "tool_calls": getattr(m, "tool_calls", None)},
                                 ensure_ascii=False, default=str) + "\n")
        seen = len(result["messages"])
        submitted = bool(_submit_results(result["messages"]))
        final = _text(result["messages"][-1].content)
        nxt = None if submitted or reply is None else reply(final)
        if not nxt:
            break
        text = nxt
    log.close()
    usage = {"input_tokens": 0, "output_tokens": 0}
    for m in result["messages"]:
        u = getattr(m, "usage_metadata", None) or {}
        usage["input_tokens"] += u.get("input_tokens", 0)
        usage["output_tokens"] += u.get("output_tokens", 0)
    return {"final": final, "steps": seen, "seconds": round(time.time() - start, 1), "submitted": submitted, **usage}
