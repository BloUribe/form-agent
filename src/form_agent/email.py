"""Reporte por correo con Resend. Se llama desde main.py (no es tool del agente)."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import resend

from .config import Settings


def parse_final(text: str) -> dict:
    """Extrae el JSON final del agente (con o sin ```json). Si falla, devuelve el texto crudo."""
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S) or re.search(r"(\{.*\})", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return {"raw": text}


def estimate_cost(res: dict, s: Settings) -> float:
    return (res.get("input_tokens", 0) * s.price_in_per_mtok + res.get("output_tokens", 0) * s.price_out_per_mtok) / 1e6


def build_html(report: dict, res: dict, url: str, cost: float, dry_run: bool) -> str:
    e = html.escape
    filled = report.get("filled", {})
    rows = "".join(f"<tr><td>{e(str(k))}</td><td>{e(str(v))}</td></tr>" for k, v in filled.items()) or "<tr><td colspan=2>—</td></tr>"
    skipped = ", ".join(map(str, report.get("skipped", []))) or "—"
    status = "DRY-RUN (no enviado)" if dry_run else ("Enviado" if report.get("submitted") else "NO enviado")
    raw = f"<pre>{e(report['raw'])}</pre>" if "raw" in report else ""
    return f"""<h2>Reporte form-agent</h2>
<p><b>URL:</b> {e(url)}<br><b>Estado:</b> {status}</p>
<h3>Campos llenados</h3><table border=1 cellpadding=4 cellspacing=0>{rows}</table>
<p><b>Omitidos:</b> {e(skipped)}</p>
<h3>Confirmación de la página</h3><p>{e(str(report.get('confirmation', '—')))}</p>{raw}
<h3>Ejecución</h3><p>{res.get('steps', '?')} mensajes · {res.get('seconds', '?')} s ·
{res.get('input_tokens', 0)} tokens in / {res.get('output_tokens', 0)} out · costo estimado ≈ USD {cost:.3f}</p>
<p>Screenshot final adjunto.</p>"""


def send_message(s: Settings, subject: str, html_body: str, attachments: list[Path] | None = None) -> str:
    resend.api_key = s.resend_api_key
    files = [{"filename": p.name, "content": list(p.read_bytes())} for p in (attachments or []) if p.exists()]
    out = resend.Emails.send({"from": s.email_from, "to": [s.email_to], "subject": subject,
                              "html": html_body, "attachments": files})
    return out["id"]


def send_report(s: Settings, report: dict, res: dict, url: str, screenshot: Path, dry_run: bool) -> str:
    subject = f"form-agent: {'dry-run' if dry_run else ('enviado' if report.get('submitted') else 'no enviado')} · {url}"
    return send_message(s, subject, build_html(report, res, url, estimate_cost(res, s), dry_run), [screenshot])
