# form-agent

Agente que abre una URL, llena un formulario web con los datos que le des en lenguaje natural y te avisa por correo
(avance, ayuda, éxito o fallo). Se opera desde **LangGraph Studio**, que además sirve para depurar cada paso.

## Cómo correrlo
```bash
uv sync && uv run playwright install chromium   # en WSL/Linux: playwright install-deps chromium
cp .env.example .env                            # ANTHROPIC_API_KEY, RESEND_API_KEY, EMAIL_TO, LANGSMITH_API_KEY
uv run langgraph dev                            # abre Studio (cuenta personal de LangSmith)
```
En el chat de Studio: «Ve a https://www.selenium.dev/selenium/web/web-form.html, llena nombre Ana, elige Two y envíalo».
Studio pausa antes de enviar (aprobar/rechazar) y cuando el agente pide ayuda (`ask_human`).

CLI alternativo: `uv run form-agent --url <url> --data data/profile.json [--dry-run] [--headed] [--auto-approve]`.

## Arquitectura
```
Studio (chat, trazas, aprobaciones) → grafo Deep Agents (src/form_agent/graph.py)
   tools.py: goto, snapshot, click, type_text, select_option, press, screenshot, page_text,
             submit_form (aprobación humana), ask_human (interrupt), send_email (avance / ayuda)
   browser.py: Playwright en un hilo dedicado (el sync API está atado a su hilo)
   agent.py: prompt + middleware que envía el reporte final por Resend (en hilo, sin bloquear el loop)
```
El agente lee la página con un *snapshot* de elementos interactivos con `ref` (más barato y fiable que screenshots).

## Seguridad y límites
- Lista blanca de dominios (`ALLOWED_DOMAINS`, `["*"]` para abrir); el envío del formulario siempre pide aprobación.
- Claves solo en `.env` (ignorado por git). `--dry-run`/`DRY_RUN=true` llena sin enviar.
- Resend sin dominio propio solo envía a tu correo registrado, desde `onboarding@resend.dev`.
- Un solo navegador compartido por servidor: no ejecutar tareas en paralelo. No maneja captchas, iframes ni subida de archivos.
- El costo mostrado en el correo es una estimación con precios configurables.

## Tests
`uv run pytest`: navegador, tools, correo y el agente con un modelo falso contra un formulario local.
