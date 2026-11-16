import calendar
from datetime import date


def add_months(d: date, n: int) -> date:
    """Suma n meses (puede ser negativo) acotando el día al fin de mes."""
    m = d.month - 1 + n
    year, month = d.year + m // 12, m % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))
