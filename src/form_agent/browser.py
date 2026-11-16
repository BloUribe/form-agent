"""Wrapper fino sobre Playwright. Todas las acciones devuelven texto (nunca lanzan hacia el modelo)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from playwright.sync_api import Page, sync_playwright

# Marca los elementos interactivos con data-ref y devuelve una lista compacta (más barata que un screenshot).
_SNAPSHOT_JS = """
() => {
  const sel = 'a[href],button,input,select,textarea,[role=button],[role=checkbox],[role=radio]';
  let n = 0; const out = [];
  document.querySelectorAll(sel).forEach(el => {
    const r = el.getBoundingClientRect();
    if (el.type === 'hidden' || (r.width === 0 && r.height === 0)) return;
    const ref = 'e' + (++n);
    el.setAttribute('data-ref', ref);
    const label = (el.labels && el.labels[0] && el.labels[0].innerText) || el.getAttribute('aria-label')
      || el.placeholder || el.innerText || el.name || el.id || '';
    const d = { ref, tag: el.tagName.toLowerCase(), type: el.type || '', label: label.trim().slice(0, 80) };
    if (el.name) d.name = el.name;
    if (el.tagName === 'SELECT') d.options = [...el.options].map(o => o.text);
    if (el.type === 'checkbox' || el.type === 'radio') d.checked = el.checked;
    else if (el.value !== undefined && el.tagName !== 'BUTTON') d.value = String(el.value).slice(0, 80);
    if (el.disabled) d.disabled = true;
    out.push(d);
  });
  return out;
}
"""


class Browser:
    def __init__(self, allowed_domains: list[str], headed: bool = False, timeout_ms: int = 10_000):
        self.allowed = allowed_domains
        # Playwright sync está atado al hilo que lo crea; LangGraph ejecuta tools en otros hilos.
        # Todo pasa por un único hilo dedicado.
        self._ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playwright")
        self._ex.submit(self._start, headed, timeout_ms).result()

    def _start(self, headed: bool, timeout_ms: int) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=not headed)
        self.page: Page = self._browser.new_page(viewport={"width": 1280, "height": 900})
        self.page.set_default_timeout(timeout_ms)

    def _stop(self) -> None:
        self._browser.close()
        self._pw.stop()

    def close(self) -> None:
        self._ex.submit(self._stop).result()
        self._ex.shutdown()

    def _loc(self, ref: str):
        return self.page.locator(f'[data-ref="{ref}"]')

    def _safe(self, fn) -> str:
        try:
            r = self._ex.submit(fn).result()
            return r if isinstance(r, str) and r else "ok"
        except Exception as e:  # el modelo debe poder recuperarse
            return f"ERROR: {str(e).splitlines()[0][:200]}"

    def goto(self, url: str) -> str:
        host = urlparse(url).hostname or ""
        if host not in self.allowed:
            return f"ERROR: dominio '{host}' no permitido. Permitidos: {self.allowed}"
        return self._safe(lambda: f"ok: {self.page.goto(url).status} {self.page.title()}")

    def snapshot(self) -> str:
        import json
        return self._safe(lambda: json.dumps(self.page.evaluate(_SNAPSHOT_JS), ensure_ascii=False))

    def page_text(self) -> str:
        return self._safe(lambda: self.page.inner_text("body")[:3000])

    def screenshot(self, path: str) -> str:
        return self._safe(lambda: (self.page.screenshot(path=path, full_page=True), path)[1])

    def click(self, ref: str) -> str:
        return self._safe(lambda: self._loc(ref).click())

    def type(self, ref: str, text: str) -> str:
        return self._safe(lambda: self._loc(ref).fill(text))

    def select(self, ref: str, value: str) -> str:
        return self._safe(lambda: self._loc(ref).select_option(label=value))

    def press(self, key: str) -> str:
        return self._safe(lambda: self.page.keyboard.press(key))
