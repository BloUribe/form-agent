"""Tools del agente (LangChain @tool) sobre Browser. submit_form es la acción irreversible."""
from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from .browser import Browser


def make_tools(browser: Browser, run_dir: Path, dry_run: bool = False) -> list:
    shots = run_dir / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    counter = {"n": 0}

    @tool
    def goto(url: str) -> str:
        """Abre una URL (solo dominios permitidos)."""
        return browser.goto(url)

    @tool
    def snapshot() -> str:
        """Lista JSON de elementos interactivos de la página con su 'ref'. Llámalo antes de actuar y tras cambios."""
        return browser.snapshot()

    @tool
    def page_text() -> str:
        """Texto visible de la página (útil para leer confirmaciones o errores)."""
        return browser.page_text()

    @tool
    def screenshot() -> str:
        """Guarda un screenshot de la página completa y devuelve su ruta."""
        counter["n"] += 1
        return browser.screenshot(str(shots / f"{counter['n']:03d}.png"))

    @tool
    def click(ref: str) -> str:
        """Click en el elemento con ese ref (checkbox, radio, enlace...). No uses esto para enviar el formulario."""
        return browser.click(ref)

    @tool
    def type_text(ref: str, text: str) -> str:
        """Escribe text en el input/textarea con ese ref (reemplaza el contenido)."""
        return browser.type(ref, text)

    @tool
    def select_option(ref: str, value: str) -> str:
        """Elige la opción (por su texto visible) en el <select> con ese ref."""
        return browser.select(ref, value)

    @tool
    def press(key: str) -> str:
        """Pulsa una tecla (Enter, Tab...)."""
        return browser.press(key)

    @tool
    def submit_form(ref: str) -> str:
        """Envía el formulario haciendo click en el botón de envío con ese ref. ACCIÓN IRREVERSIBLE: requiere aprobación."""
        if dry_run:
            return "DRY-RUN: el formulario NO se envió."
        return browser.click(ref)

    return [goto, snapshot, page_text, screenshot, click, type_text, select_option, press, submit_form]
