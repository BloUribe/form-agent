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
from langgraph.types import Command

from .browser import Browser
from .config import Settings
from .email import parse_final, send_report
from .tools import make_tools

SYSTEM_PROMPT = """Eres un agente que llena formularios web usando un navegador. El usuario te da en lenguaje natural
la URL y los datos a usar (en el chat o como JSON).
Reglas:
- Usa solo los datos que el usuario te dio. Nunca inventes datos. Si falta un dato obligatorio o hay un bloqueo
  (captcha, login, dominio no permitido), manda send_email(kind="help") y pregunta con ask_human; espera la respuesta.
- Llama a snapshot antes de actuar y después de cambios grandes; usa los 'ref' que devuelve.
- Si una acción devuelve ERROR, vuelve a hacer snapshot y reintenta distinto. No repitas lo mismo más de 2 veces.
- Los checkbox/radio ya marcados no se tocan salvo que el usuario lo pida (un click los desmarca).
- Cuando todo esté lleno, haz un snapshot para verificar y envía con submit_form (único modo de enviar).
- Tras enviar, usa page_text y screenshot para confirmar el resultado.
- Si la tarea es larga, puedes mandar send_email(kind="progress") con un avance breve. El reporte final por correo
  (éxito o fallo, con screenshot) se envía automáticamente al terminar: no lo envíes tú.
- Termina con un resumen JSON: {"filled": {campo: valor}, "skipped": [...], "submitted": bool, "confirmation": "texto de la página"}.
"""


def make_final_report(settings: Settings, get_browser, run_dir: Path, dry_run: bool):
    """Middleware after_agent: garantiza el correo final sin depender de que el modelo lo recuerde."""

    def _send(state) -> None:
        if not (settings.resend_api_key and settings.email_to):
            return
        try:
            msgs = state["messages"]
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
        except Exception as e:  # el correo final nunca debe romper la ejecución
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
        tools=make_tools(browser, run_dir, dry_run=dry_run, settings=settings),
        system_prompt=SYSTEM_PROMPT,
        middleware=[make_final_report(settings, get, run_dir, dry_run)] if final_report else [],
        interrupt_on=None if auto_approve else {"submit_form": True},
        checkpointer=MemorySaver() if use_checkpointer else None,
    )


def run_agent(agent, url: str, profile: dict, settings: Settings, run_dir: Path, approve=None) -> dict:
    """Ejecuta el agente, resuelve interrupts HITL con approve() y registra cada mensaje en JSONL."""
    cfg = {"configurable": {"thread_id": uuid.uuid4().hex}, "recursion_limit": settings.max_steps}
    task = f"URL: {url}\nPerfil a usar:\n{json.dumps(profile, ensure_ascii=False, indent=2)}"
    inp: object = {"messages": [{"role": "user", "content": task}]}
    log = (run_dir / "steps.jsonl").open("a")
    start, seen = time.time(), 0
    while True:
        result = agent.invoke(inp, config=cfg)
        for m in result["messages"][seen:]:
            log.write(json.dumps({"type": m.type, "content": m.content if isinstance(m.content, str) else str(m.content),
                                  "tool_calls": getattr(m, "tool_calls", None)}, ensure_ascii=False, default=str) + "\n")
        seen = len(result["messages"])
        if not result.get("__interrupt__"):
            break
        ok = approve() if approve else False
        inp = Command(resume={"decisions": [{"type": "approve"} if ok else {"type": "reject", "message": "El usuario rechazó el envío."}]})
    log.close()
    usage = {"input_tokens": 0, "output_tokens": 0}
    for m in result["messages"]:
        u = getattr(m, "usage_metadata", None) or {}
        usage["input_tokens"] += u.get("input_tokens", 0)
        usage["output_tokens"] += u.get("output_tokens", 0)
    final = result["messages"][-1].content
    if isinstance(final, list):
        final = "".join(b.get("text", "") for b in final if isinstance(b, dict))
    return {"final": final, "steps": seen, "seconds": round(time.time() - start, 1), **usage}
