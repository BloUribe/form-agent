from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .agent import build_agent, run_agent
from .browser import Browser
from .config import Settings
from .email import parse_final, send_report


def main() -> None:
    ap = argparse.ArgumentParser(prog="form-agent")
    ap.add_argument("--url", required=True)
    ap.add_argument("--data", required=True, help="JSON con el perfil a llenar")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="llena pero no envía")
    ap.add_argument("--no-email", action="store_true", help="no enviar el reporte")
    ap.add_argument("--auto-approve", action="store_true", help="no pedir confirmación antes de enviar")
    a = ap.parse_args()

    s = Settings()
    profile = json.loads(Path(a.data).read_text())
    run_dir = Path(s.artifacts_dir) / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True)
    browser = Browser(s.allowed_domains, headed=a.headed, timeout_ms=s.action_timeout_ms)
    try:
        agent = build_agent(s, browser, run_dir, dry_run=a.dry_run, auto_approve=a.auto_approve)
        approve = lambda: input("¿Enviar el formulario? [y/N] ").strip().lower() == "y"
        res = run_agent(agent, a.url, profile, s, run_dir, approve=approve)
        browser.screenshot(str(run_dir / "final.png"))
    finally:
        browser.close()
    print(res["final"])
    if not a.no_email:
        if not (s.resend_api_key and s.email_to):
            print("\n[correo omitido: falta RESEND_API_KEY o EMAIL_TO en .env]")
        else:
            try:
                eid = send_report(s, parse_final(res["final"]), res, a.url, run_dir / "final.png", a.dry_run)
                print(f"\n[correo enviado: {eid}]")
            except Exception as ex:  # el fallo del correo no debe perder el resultado del run
                print(f"\n[ERROR enviando correo: {ex}]")
    print(f"\n[{res['steps']} mensajes, {res['seconds']}s, artifacts: {run_dir}]")


if __name__ == "__main__":
    main()
