"""Tools del agente de fletes. El destinatario de los correos lo fija el código (remitente verificado), no el modelo."""
from __future__ import annotations

import html

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from pydantic import ValidationError

from ..approval import is_affirmative, last_user_text
from ..config import Settings
from ..email import send_message
from .carriers.base import RateProvider, ScheduleProvider
from .carriers.hapag import ProviderError
from .models import SailingOption, ShipmentRequest
from .service import find_options


def _row(o: SailingOption) -> str:
    s = o.sailing
    price = f"{o.quote.currency} {o.total_price:.0f}" if o.quote and o.total_price is not None else "sin precio"
    avail = o.quote.availability if o.quote else "—"
    return f"| {o.id} | {s.vessel_name} ({s.voyage or '—'}) | {s.etd} | {s.eta or '—'} | {price} | {avail} |"


def make_freight_tools(settings: Settings, schedules: ScheduleProvider, rates: RateProvider, recipient: str,
                       require_approval: bool = True, store: dict | None = None, subject: str | None = None) -> list:
    """`store`: dict por conversación donde se guardan las opciones de la última búsqueda; se comparte entre
    turnos porque el agente se reconstruye en cada correo. Se pierde si el proceso se reinicia (book_option
    pide entonces buscar de nuevo). `subject`: si se da, fija el asunto de todos los correos (hilos del cliente)."""
    last: dict = store if store is not None else {}
    last.setdefault("options", [])
    fixed_subject = subject

    @tool
    def search_sailings(origin_port: str, destination_port: str, container_count: int, departure_date: str,
                        container_type: str = "40HC", weight_kg: float | None = None) -> str:
        """Busca salidas de buques. Puertos en UN/LOCODE (5 letras, ej. CLSAI, CNSHA). departure_date en formato YYYY-MM-DD.
        container_type: 20DRY, 40DRY, 40HC o 45HC. Devuelve una tabla numerada con buque, fechas y precio total."""
        try:
            req = ShipmentRequest(origin_port=origin_port, destination_port=destination_port,
                                  container_count=container_count, container_type=container_type,
                                  weight_kg=weight_kg, departure_date=departure_date)
        except ValidationError as e:
            return f"ERROR: datos inválidos: {e.errors()[0]['loc']} {e.errors()[0]['msg']}"
        try:
            options = find_options(req, schedules, rates)
        except ProviderError as e:
            return f"ERROR: la naviera no respondió: {e}"
        last["options"] = options
        if not options:
            return f"No hay salidas de {req.origin_port} a {req.destination_port} desde {req.departure_date}."
        head = "| # | Buque (viaje) | Salida | Llegada | Precio total | Disponibilidad |\n|---|---|---|---|---|---|\n"
        return head + "\n".join(_row(o) for o in options)

    @tool
    def send_options_email(subject: str, body: str) -> str:
        """Envía un correo al cliente que escribió (siempre a él, no puedes elegir otro destinatario). Úsalo para
        responder: opciones encontradas, preguntas por datos que faltan o confirmación de reserva."""
        if not settings.resend_api_key:
            return "ERROR: correo no configurado (RESEND_API_KEY)."
        try:
            eid = send_message(settings, fixed_subject or subject,
                               f"<p>{html.escape(body).replace(chr(10), '<br>')}</p>", to=recipient)
        except Exception as e:
            return f"ERROR: no se pudo enviar el correo: {str(e)[:200]}"
        return f"ok: correo enviado ({eid})"

    @tool
    def book_option(option_id: int, runtime: ToolRuntime) -> str:
        """Reserva la opción con ese número de la última búsqueda. ACCIÓN IRREVERSIBLE: solo procede si el último
        mensaje del cliente aprueba explícitamente la reserva."""
        if require_approval and not is_affirmative(last_user_text(runtime.state["messages"])):
            return ("BLOQUEADO: el cliente aún no aprobó la reserva en su último mensaje. Resume la opción elegida, "
                    "pregunta si confirmas y TERMINA tu turno. No reintentes hasta que responda.")
        option = next((o for o in last["options"] if o.id == option_id), None)
        if option is None:
            return f"ERROR: no existe la opción {option_id} en la última búsqueda; vuelve a buscar."
        s = option.sailing
        return (f"RESERVA SIMULADA: opción {option.id} · {s.vessel_name} ({s.voyage or '—'}) · salida {s.etd}. "
                "No se contactó a la naviera: la reserva real aún no está integrada.")

    return [search_sailings, send_options_email, book_option]
