"""Punto de entrada para LangGraph Studio (`uv run langgraph dev`)."""
import time
from pathlib import Path

from form_agent.agent import build_agent
from form_agent.browser import get_shared_browser
from form_agent.config import Settings

settings = Settings()
_run_dir = Path(settings.artifacts_dir) / f"studio-{time.strftime('%Y%m%d-%H%M%S')}"
_run_dir.mkdir(parents=True, exist_ok=True)

graph = build_agent(
    settings,
    browser=lambda: get_shared_browser(settings),
    run_dir=_run_dir,
    dry_run=settings.dry_run,
    use_checkpointer=False,  # LangGraph Server inyecta el checkpointer
    final_report=True,
)
