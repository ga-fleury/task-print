from datetime import datetime

_DAYS_PT_BR = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
_MONTHS_PT_BR = [
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
]


def format_header(now: datetime | None = None) -> str:
    now = now or datetime.now()
    day = _DAYS_PT_BR[now.weekday()]
    month = _MONTHS_PT_BR[now.month - 1]
    return f"{day} {now.day} {month}, {now.hour:02d}:{now.minute:02d}"
