import base64
import json
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from svix.webhooks import Webhook

from form_agent.config import Settings
from form_agent.inbound.server import create_app, thread_key
from form_agent.inbound.store import SeenStore

SECRET = "whsec_" + base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()


class Harness:
    def __init__(self, tmp_path, allowed=("cliente@empresa.com",), emails=None):
        self.calls = []
        self.emails = emails or {}
        s = Settings(_env_file=None, resend_webhook_secret=SECRET, allowed_senders=list(allowed))
        app = create_app(s, fetch_email=lambda eid: self.emails[eid],
                         handle_email=lambda **kw: self.calls.append(kw), seen=SeenStore(tmp_path / "seen.sqlite"))
        self.client = TestClient(app)

    def post(self, email_id="em_1", event="email.received", sign=True, secret=SECRET):
        body = json.dumps({"type": event, "data": {"email_id": email_id}}).encode()
        ts = str(int(time.time()))
        sig = Webhook(secret).sign("msg_" + email_id, datetime.fromtimestamp(int(ts), tz=timezone.utc), body.decode())
        headers = {"svix-id": "msg_" + email_id, "svix-timestamp": ts, "svix-signature": sig if sign else "v1,bad",
                   "content-type": "application/json"}
        return self.client.post("/webhooks/resend", content=body, headers=headers)


def mail(sender="Cliente <cliente@empresa.com>", subject="Cotización CLSAI-CNSHA", text="2x40HC el 1 dic"):
    return {"from": sender, "subject": subject, "text": text}


def test_invalid_signature_is_rejected_and_nothing_runs(tmp_path):
    h = Harness(tmp_path, emails={"em_1": mail()})
    assert h.post(sign=False).status_code == 401
    assert h.calls == []


def test_other_event_types_are_ignored(tmp_path):
    h = Harness(tmp_path, emails={"em_1": mail()})
    assert h.post(event="email.delivered").status_code == 200
    assert h.calls == []


def test_sender_outside_allow_list_is_ignored_silently(tmp_path):
    h = Harness(tmp_path, emails={"em_1": mail(sender="atacante@evil.com")})
    assert h.post().status_code == 200
    assert h.calls == []


def test_empty_allow_list_accepts_nobody(tmp_path):
    h = Harness(tmp_path, allowed=(), emails={"em_1": mail()})
    h.post()
    assert h.calls == []


def test_allowed_sender_triggers_handler_with_plain_address_and_body(tmp_path):
    h = Harness(tmp_path, emails={"em_1": mail()})
    assert h.post().status_code == 200
    (c,) = h.calls
    assert c["sender"] == "cliente@empresa.com" and c["subject"] == "Cotización CLSAI-CNSHA"
    assert c["body"] == "2x40HC el 1 dic" and c["thread_id"]


def test_sender_match_is_case_insensitive(tmp_path):
    h = Harness(tmp_path, emails={"em_1": mail(sender="CLIENTE@Empresa.com")})
    h.post()
    assert len(h.calls) == 1


def test_duplicate_delivery_runs_handler_once(tmp_path):
    h = Harness(tmp_path, emails={"em_1": mail()})
    h.post()
    h.post()
    assert len(h.calls) == 1


def test_reply_with_re_prefix_reuses_the_same_thread(tmp_path):
    h = Harness(tmp_path, emails={"em_1": mail(), "em_2": mail(subject="RE: Re: Cotización CLSAI-CNSHA", text="la segunda")})
    h.post("em_1")
    h.post("em_2")
    assert h.calls[0]["thread_id"] == h.calls[1]["thread_id"]


@pytest.mark.parametrize("a,b", [
    (("a@x.com", "Cotización 1"), ("b@x.com", "Cotización 1")),
    (("a@x.com", "Cotización 1"), ("a@x.com", "Cotización 2")),
])
def test_different_sender_or_subject_gets_different_thread(a, b):
    assert thread_key(*a) != thread_key(*b)


def test_fetch_failure_returns_5xx_so_resend_retries_and_is_not_marked_seen(tmp_path):
    h = Harness(tmp_path, emails={})  # KeyError al buscar el correo
    assert h.post().status_code == 500
    h.emails["em_1"] = mail()  # en el reintento ya está disponible
    assert h.post().status_code == 200
    assert len(h.calls) == 1
