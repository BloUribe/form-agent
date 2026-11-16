"""Aprobación en lenguaje natural: el envío solo procede si el ÚLTIMO mensaje del usuario es un 'sí' claro."""
from __future__ import annotations

import re
import unicodedata

YES = {"si", "ok", "okay", "dale", "yes", "vale", "adelante", "listo", "confirmo", "apruebo", "aprobado",
       "perfecto", "correcto", "envialo", "enviala", "mandalo", "hazlo", "procede", "claro"}
NO = {"no", "nunca", "cambia", "cambiar", "edita", "editar", "pero", "espera", "antes", "omite", "omitir",
      "cancela", "cancelar", "detente", "para", "excepto", "menos", "sin", "corrige", "llena", "llenar", "llenalo", "rellena"}


def _tokens(text: str) -> list[str]:
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+", t)


def is_affirmative(text: str) -> bool:
    """'sí', 'ok, envíalo' → True. Cualquier corrección ('sí pero cambia…'), negación o texto largo → False."""
    toks = _tokens(text)
    return bool(toks) and len(toks) <= 8 and not (set(toks) & NO) and bool(set(toks) & YES)


def last_user_text(messages) -> str:
    for m in reversed(messages):
        if getattr(m, "type", None) == "human":
            c = m.content
            return c if isinstance(c, str) else "".join(b.get("text", "") for b in c if isinstance(b, dict))
    return ""
