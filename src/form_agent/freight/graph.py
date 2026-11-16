"""Punto de entrada de Studio para el agente de fletes (`uv run langgraph dev`).
En Studio no hay correo entrante: las respuestas se envían a EMAIL_TO."""
from form_agent.config import Settings
from form_agent.freight.agent import build_freight_agent
from form_agent.freight.providers import build_providers

settings = Settings()
_schedules, _rates = build_providers(settings)

graph = build_freight_agent(settings, _schedules, _rates, recipient=settings.email_to,
                            checkpointer=None)  # LangGraph Server inyecta el checkpointer
