"""Nombres legibles de los puertos que usa el informe (UN/LOCODE → ciudad)."""

PORT_NAMES = {
    "USMIA": "Miami", "USNYC": "Nueva York", "USLAX": "Los \u00c1ngeles", "CLSAI": "San Antonio", "CLVAP": "Valpara\u00edso",
    "PECLL": "Callao", "BRSSZ": "Santos", "CNSHA": "Shangh\u00e1i", "CNNGB": "Ningbo", "NLRTM": "R\u00f3terdam", "ESVLC": "Valencia",
}


def port_label(code: str) -> str:
    name = PORT_NAMES.get(code)
    return f"{name} ({code})" if name else code


def route_label(origin: str, destination: str) -> str:
    return f"{port_label(origin)} \u2192 {port_label(destination)}"
