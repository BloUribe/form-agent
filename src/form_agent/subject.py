import re

_PREFIX = re.compile(r"^\s*((re|rv|fwd|fw)\s*:\s*)+", re.I)


def strip_reply_prefix(subject: str) -> str:
    """'RE: Re: Cotización' → 'Cotización'."""
    return _PREFIX.sub("", subject).strip()
