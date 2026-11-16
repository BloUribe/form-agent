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
Todo es conversación en lenguaje natural (sin JSON):
1. El agente te muestra una **tabla markdown** con los campos encontrados y el valor que propone.
2. Tú respondes: «cambia el password por X», «omite el textarea», «así está bien».
3. Llena, te muestra la tabla final y pregunta «¿lo envío?». Solo con un «sí» claro (`approval.py`) envía.
4. Tras enviar llega **un correo** con los campos usados y el screenshot del éxito o error. Charlas o formularios sin enviar no mandan correo.

CLI alternativo (chat por terminal): `uv run form-agent --url <url> --data data/profile.json [--dry-run] [--headed] [--auto-approve]`.

## Arquitectura
```
Studio (chat, trazas, aprobaciones) → grafo Deep Agents (src/form_agent/graph.py)
   tools.py: goto, snapshot, click, type_text, select_option, press, screenshot, page_text,
             submit_form (bloqueado hasta que tu último mensaje lo apruebe), send_email (solo si lo pides)
   browser.py: Playwright en un hilo dedicado (el sync API está atado a su hilo)
   agent.py: prompt + middleware que envía el reporte tras cada envío de formulario (en hilo, sin bloquear el loop)
```
El agente lee la página con un *snapshot* de elementos interactivos con `ref` (más barato y fiable que screenshots).

## Seguridad y límites
- Lista blanca de dominios (`ALLOWED_DOMAINS`, `["*"]` para abrir); `submit_form` rechaza el envío si el último mensaje del usuario no es una aprobación clara (corregido por tests; «sí pero cambia…» no cuenta).
- Claves solo en `.env` (ignorado por git). `--dry-run`/`DRY_RUN=true` llena sin enviar.
- Resend sin dominio propio solo envía a tu correo registrado, desde `onboarding@resend.dev`.
- Un solo navegador compartido por servidor: no ejecutar tareas en paralelo. No maneja captchas, iframes ni subida de archivos.
- El costo mostrado en el correo es una estimación con precios configurables.

## Tests
`uv run pytest`: navegador, tools, correo y el agente con un modelo falso contra un formulario local.

## Agente de cotización de fletes (por correo)

Un correo con los datos del envío (puertos, contenedores, peso, fecha de salida) dispara un agente que busca salidas de buques y
responde por correo con las opciones y la pregunta de cuál reservar. Corre en paralelo al agente de formularios.

```
Resend (email.received) → POST /webhooks/resend → firma Svix + lista de remitentes + dedupe
  → freight_agent (un turno por correo, hilo = remitente + asunto) → send_options_email → cliente
cliente responde «sí, confirmo la 2» → mismo hilo → book_option (simulada, solo tras aprobación)
```

**Fuentes de datos.** Por defecto todo sale de una base SQLite simulada (`artifacts/mock_freight.sqlite`, `freight/carriers/mockdb.py`):
~520 salidas semanales en 20 rutas (10 pares de puertos, ambos sentidos: Chile, Perú, Brasil ↔ China, EE. UU., Europa), de hoy
hasta 6 meses adelante, con buque ficticio, capacidad libre en TEU y precio por tipo de contenedor. Es determinista y se
regenera sola cada día. Para verla: `sqlite3 artifacts/mock_freight.sqlite 'select * from sailings limit 10'`.
Si defines `HAPAG_*`, los horarios pasan a ser reales (Hapag-Lloyd, estándar DCSA, `freight/carriers/hapag.py`) con precios
genéricos simulados: ninguna naviera grande publica una API de precios. La reserva (`book_option`) siempre es simulada.

**Puesta en marcha**
1. Rellena en `.env`: `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `ALLOWED_SENDERS=["tu@correo.com"]` (vacío = nadie puede disparar al agente) y, opcionalmente, `HAPAG_*`.
2. `uv run uvicorn form_agent.inbound.run:app --port 8000`
3. Expón el puerto (`cloudflared tunnel --url http://localhost:8000` o `ngrok http 8000`) y registra `https://<túnel>/webhooks/resend`
   como webhook del evento `email.received` en Resend. Escribe a tu dirección `*@<id>.resend.app`.
4. Studio: `uv run langgraph dev` expone también el grafo `freight_agent` (las respuestas van a `EMAIL_TO`).

**Seguridad.** El correo es entrada no confiable: el destinatario de las respuestas lo fija el código (el remitente verificado),
no el modelo; la firma se verifica; la reserva exige un «sí» corto y explícito en el último mensaje (se descarta el historial citado y la firma).

**Pendiente de verificar con el sandbox real de Hapag-Lloyd:** ruta y versión de la API, nombres de los headers de autenticación
y forma exacta de la respuesta (el cliente sigue el estándar DCSA; ver el docstring de `hapag.py`).

## Informe mensual de pre-booking (forecast P10 / P50 / P90)

Un comando genera un PDF con el pronóstico de contenedores de la ruta del cliente para el mes siguiente y recomienda
qué salidas reservar, y lo envía por correo (Resend).

```bash
uv run python -m form_agent.report.monthly              # genera el PDF y lo envía a EMAIL_TO
uv run python -m form_agent.report.monthly --no-email   # solo el PDF (artifacts/reports/)
uv run python -m form_agent.report.monthly --no-llm     # resumen con plantilla, sin llamar al modelo
uv run python -m form_agent.report.monthly --target 2027-01   # otro mes (de 1 a 6 meses adelante)
```

- **Niveles:** *Comprar* (P10: el volumen que se supera el 90 % de las veces, poco riesgo de quedar sin usar), *Preparar*
  (de P10 a P50: opciones listas sin comprar) y *Vigilar* (de P50 a P90: escenario alto).
- **Modelo** (`forecast/model.py`, Python puro, sin numpy ni scikit-learn): mezcla «el mismo mes de años previos × crecimiento reciente»
  con «el promedio de los últimos 12 meses», eligiendo la mezcla por backtest; los percentiles salen de los errores de ese backtest.
- **Reparto** (`forecast/plan.py`): coloca cada nivel en las salidas del mes más baratas y cercanas, sin pasar de la capacidad libre
  ni poner más del 50 % de un nivel en una sola salida. Lo que no cabe aparece como «Sin colocar», con el motivo.
- **Datos simulados:** historial del cliente (`history/mockdb.py`, ~77 contenedores/mes de Miami a San Antonio, Chile) y salidas
  (`freight/carriers/mockdb.py`). Se regeneran solos al cambiar el día, el mes o la versión del generador.
- **PDF** (`report/pdf.py`): una página con la marca de Interworld Freight (`report/brand.py`, logos en `report/assets/`).
  El resumen lo redacta Claude con las cifras ya calculadas; si falla o no hay clave, se usa una plantilla.
- Programarlo el día 1 de cada mes: `0 8 1 * * cd /ruta/al/repo && uv run python -m form_agent.report.monthly`.
