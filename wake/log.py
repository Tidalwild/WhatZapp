import json

ALLOWED = frozenset(
    {"event", "eventId", "state", "reason", "attempt", "source", "unique", "disposition"}
)


class Log:
    def __init__(self) -> None:
        self.lines = []

    def event(self, name: str, **fields) -> None:
        row = {"event": name}
        for key, value in fields.items():
            if key not in ALLOWED or key == "event":
                continue
            safe = _safe(value)
            if safe is not None:
                row[key] = safe
        self.lines.append(row)

    def text(self) -> str:
        return json.dumps(self.lines, sort_keys=True)


def _safe(value):
    if isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, str) and len(value) <= 80 and "://" not in value and "\n" not in value and "\r" not in value:
        return value
    return None
