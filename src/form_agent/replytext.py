"""Deja solo el texto nuevo de una respuesta por correo (sin historial citado ni firma)."""
import re

# Línea que marca el inicio del historial o de la firma: todo lo que sigue se descarta.
_CUT = re.compile(
    r"^\s*(on .{5,200} wrote:|el .{5,200} escribi[óo]:|-{2,}\s*(original message|mensaje original)\s*-{2,}|--)\s*$", re.I)


def extract_reply(body: str) -> str:
    kept = []
    for line in body.splitlines():
        if _CUT.match(line):
            break
        if line.lstrip().startswith(">"):
            continue
        kept.append(line)
    text = "\n".join(kept).strip()
    return text or body  # si todo estaba citado, mejor el cuerpo completo que nada
