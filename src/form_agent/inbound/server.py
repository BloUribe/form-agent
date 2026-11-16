"""Webhook de Resend (email.received): verifica la firma, filtra remitentes y dispara el agente."""
from __future__ import annotations

import hashlib
import json
from email.utils import parseaddr
from typing import Callable

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from svix.webhooks import Webhook

from ..config import Settings
from ..subject import strip_reply_prefix
from .store import SeenStore


def thread_key(sender: str, subject: str) -> str:
    """Un hilo de conversación = remitente + asunto sin 'Re:'. Así la respuesta del cliente cae en la misma
    conversación sin depender de los headers In-Reply-To (cuyo nombre exacto en Resend no está verificado)."""
    norm = " ".join(strip_reply_prefix(subject).casefold().split())
    return hashlib.sha1(f"{sender.strip().lower()}|{norm}".encode()).hexdigest()[:16]


def create_app(settings: Settings, fetch_email: Callable[[str], dict], handle_email: Callable[..., None],
               seen: SeenStore) -> FastAPI:
    app = FastAPI()
    allowed = {a.strip().lower() for a in settings.allowed_senders}

    @app.post("/webhooks/resend")
    async def resend_webhook(request: Request, background: BackgroundTasks):
        raw = await request.body()
        try:
            Webhook(settings.resend_webhook_secret).verify(raw, dict(request.headers))
        except Exception:  # svix lanza WebhookVerificationError, pero una firma mal formada llega como binascii.Error
            raise HTTPException(status_code=401, detail="firma inválida")
        event = json.loads(raw)
        if event.get("type") != "email.received":
            return {"status": "ignored"}
        try:
            email = fetch_email(event["data"]["email_id"])
        except Exception as e:
            print(f"[inbound] no se pudo leer el correo: {e}")
            raise HTTPException(status_code=500, detail="no se pudo leer el correo")  # Resend reintenta
        if not seen.add(event["data"]["email_id"]):
            return {"status": "duplicate"}
        sender = parseaddr(email.get("from", ""))[1].lower()
        if sender not in allowed:
            return {"status": "ignored"}  # sin pistas para quien escribe desde fuera
        subject = email.get("subject") or ""
        background.add_task(handle_email, sender=sender, subject=subject,
                            body=email.get("text") or email.get("html") or "", thread_id=thread_key(sender, subject))
        return {"status": "accepted"}

    return app
