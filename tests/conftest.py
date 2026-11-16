import functools
import http.server
import threading
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

FIXTURES = Path(__file__).parent / "fixtures"


class ScriptedModel(GenericFakeChatModel):
    """Modelo falso determinista que acepta bind_tools (deepagents lo exige)."""

    def bind_tools(self, tools, **kwargs):
        return self


def call(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c-{name}-{len(str(args))}"}])


def scripted(*messages):
    return ScriptedModel(messages=iter(messages))


@pytest.fixture(scope="session")
def form_url():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/form.html"
    srv.shutdown()


@pytest.fixture
def browser():
    from form_agent.browser import Browser
    b = Browser(allowed_domains=["127.0.0.1"], timeout_ms=3000)
    yield b
    b.close()
