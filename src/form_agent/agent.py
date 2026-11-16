from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from deepagents import create_deep_agent
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from .browser import Browser
from .config import Settings
from .tools import make_tools

SYSTEM_PROMPT = """Eres un agente que llena formularios web usando un navegador.
Objetivo: abrir la URL dada, llenar el formulario con EXACTAMENTE los datos del perfil y enviarlo.
Reglas:
- Usa solo los datos del perfil. Nunca inventes datos; si un campo obligatorio no tiene dato, déjalo y repórtalo.
- Llama a snapshot antes de actuar y después de cambios grandes; usa los 'ref' que devuelve.
- Si una acción devuelve ERROR, vuelve a hacer snapshot y reintenta distinto.
- Cuando todo esté lleno, haz un snapshot para verificar y envía con submit_form (único modo de enviar).
- Tras enviar, usa page_text y screenshot para confirmar el resultado.
- Termina con un resumen JSON: {"filled": {campo: valor}, "skipped": [...], "submitted": bool, "confirmation": "texto de la página"}.
"""


def build_agent(settings: Settings, browser: Browser, run_dir: Path, dry_run: bool = False,
                auto_approve: bool = False, model=None):
    model = model or ChatAnthropic(model=settings.model, api_key=settings.anthropic_api_key, max_tokens=4096)
    return create_deep_agent(
        model=model,
        tools=make_tools(browser, run_dir, dry_run=dry_run),
        system_prompt=SYSTEM_PROMPT,
        interrupt_on=None if auto_approve else {"submit_form": True},
        checkpointer=MemorySaver(),
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
    final = result["messages"][-1].content
    if isinstance(final, list):
        final = "".join(b.get("text", "") for b in final if isinstance(b, dict))
    return {"final": final, "steps": seen, "seconds": round(time.time() - start, 1)}
