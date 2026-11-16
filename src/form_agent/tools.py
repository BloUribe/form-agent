"""Tools del agente (LangChain @tool) sobre Browser. submit_form es la acción irreversible."""
from __future__ import annotations

import html
from pathlib import Path

from langchain_core.tools import tool
from langchain.tools import ToolRuntime

from .approval import is_affirmative, last_user_text
from .browser import Browser
from .config import Settings
from .email import send_message


def make_tools(browser: Browser | callable, run_dir: Path, dry_run: bool = False,
               settings: Settings | None = None, require_approval: bool = False) -> list:
    """`browser` puede ser un Browser o una función que lo crea perezosamente."""
    get = browser if callable(browser) else (lambda: browser)
    shots = run_dir / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    counter = {"n": 0}

    def _shot() -> str:
        counter["n"] += 1
        return get().screenshot(str(shots / f"{counter['n']:03d}.png"))

    @tool
    def goto(url: str) -> str:
        """Abre una URL (solo dominios permitidos)."""
        return get().goto(url)

    @tool
    def snapshot() -> str:
        """Lista JSON de elementos interactivos de la página con su 'ref'. Llámalo antes de actuar y tras cambios."""
        return get().snapshot()

    @tool
    def page_text() -> str:
        """Texto visible de la página (útil para leer confirmaciones o errores)."""
        return get().page_text()

    @tool
    def screenshot() -> str:
        """Guarda un screenshot de la página completa y devuelve su ruta."""
        return _shot()

    @tool
    def click(ref: str) -> str:
        """Click en el elemento con ese ref (checkbox, radio, enlace...). No uses esto para enviar el formulario."""
        return get().click(ref)

    @tool
    def type_text(ref: str, text: str) -> str:
        """Escribe text en el input/textarea con ese ref (reemplaza el contenido)."""
        return get().type(ref, text)

    @tool
    def select_option(ref: str, value: str) -> str:
        """Elige la opción (por su texto visible) en el <select> con ese ref."""
        return get().select(ref, value)

    @tool
    def press(key: str) -> str:
        """Pulsa una tecla (Enter, Tab...)."""
        return get().press(key)

    @tool
    def submit_form(ref: str, runtime: ToolRuntime) -> str:
        """Envía el formulario haciendo click en el botón de envío con ese ref. ACCIÓN IRREVERSIBLE: solo procede si el último mensaje del usuario aprueba el envío."""
        if require_approval and not is_affirmative(last_user_text(runtime.state["messages"])):
            return ("BLOQUEADO: el usuario aún no aprobó el envío en su último mensaje. Muestra la tabla final de valores, "
                    "pregunta si lo envías y TERMINA tu turno. No reintentes submit_form hasta que responda.")
        if dry_run:
            return "DRY-RUN: el formulario NO se envió."
        return get().click(ref)

    @tool
    def send_email(kind: str, subject: str, body: str, attach_screenshot: bool = False) -> str:
        """Envía un correo al usuario. kind: 'progress' (avance) o 'help' (necesitas ayuda). Úsalo SOLO si el usuario pidió explícitamente avisos por correo. El reporte final tras enviar el formulario se envía solo."""
        if kind not in ("progress", "help", "success", "failure"):
            return "ERROR: kind debe ser progress, help, success o failure."
        if not settings or not (settings.resend_api_key and settings.email_to):
            return "ERROR: correo no configurado (RESEND_API_KEY / EMAIL_TO)."
        files = []
        if attach_screenshot:
            path = _shot()
            if not path.startswith("ERROR"):
                files.append(Path(path))
        try:
            eid = send_message(settings, f"[form-agent · {kind}] {subject}",
                               f"<p>{html.escape(body).replace(chr(10), '<br>')}</p>", files)
        except Exception as e:
            return f"ERROR: no se pudo enviar el correo: {str(e)[:200]}"
        return f"ok: correo enviado ({eid})"

    return [goto, snapshot, page_text, screenshot, click, type_text, select_option, press, submit_form, send_email]
