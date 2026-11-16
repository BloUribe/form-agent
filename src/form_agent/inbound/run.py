"""Servidor de producción/desarrollo:  uv run uvicorn form_agent.inbound.run:app --port 8000
Luego expón el puerto con un túnel y registra https://<túnel>/webhooks/resend en Resend (evento email.received)."""
import sqlite3
from pathlib import Path

import resend
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver

from ..config import Settings
from ..freight.handler import make_handler
from ..freight.providers import build_providers
from .server import create_app
from .store import SeenStore


def create_default_app():
    load_dotenv()  # exporta LANGSMITH_* a os.environ (pydantic-settings no lo hace)
    settings = Settings()
    resend.api_key = settings.resend_api_key
    Path(settings.state_db).parent.mkdir(parents=True, exist_ok=True)
    checkpointer = SqliteSaver(sqlite3.connect(settings.state_db, check_same_thread=False))
    schedules, rates = build_providers(settings)
    return create_app(
        settings,
        fetch_email=lambda email_id: dict(resend.Emails.Receiving.get(email_id)),
        handle_email=make_handler(settings, schedules, rates, checkpointer),
        seen=SeenStore(settings.state_db),
    )


app = create_default_app()
