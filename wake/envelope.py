import json
import re
import uuid

SCHEMA_FIELD = "whatsapp-wake-test-v1"
SCHEMA_V2 = "whatsapp-wake-test-v2"
SCHEMA_V3 = "whatsapp-wake-test-v3"
CHAT_REF = re.compile(r"^ref-[0-9a-f]{16}$")
SOURCES = frozenset(
    {
        "linux-session-notify",
        "android-listener",
        "web-page-change",
        "unread-indicator-hint",
        "manual-connectivity-probe",
    }
)
MAX_BYTES = 512
EVENT_ID = re.compile(r"^[A-Za-z0-9._:-]{8,80}$")
GENERATED_ID = re.compile(r"^evt-[0-9a-f]{32}$")
OBSERVED_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
REQUIRED = frozenset({"field", "eventId", "source", "observedAt", "testOnly"})
OPTIONAL = frozenset({"conversationScope"})


class EnvelopeError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def new_event_id() -> str:
    return "evt-" + uuid.uuid4().hex


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _clean_text(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if any(ord(char) < 32 for char in value):
        return False
    lowered = value.lower()
    if "://" in value or "http:" in lowered or "https:" in lowered or "http" in lowered:
        return False
    return True


def validate(payload: object) -> dict:
    if isinstance(payload, dict) and payload.get("field") == SCHEMA_V3:
        return _validate_v3(payload)
    if isinstance(payload, dict) and payload.get("field") == SCHEMA_V2:
        return _validate_v2(payload)
    return _validate_v1(payload)


def _validate_v1(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise EnvelopeError("malformed")
    extra = set(payload) - REQUIRED - OPTIONAL
    if extra:
        raise EnvelopeError("malformed")
    if not REQUIRED <= set(payload):
        raise EnvelopeError("malformed")
    if payload.get("field") != SCHEMA_FIELD:
        raise EnvelopeError("malformed")
    if payload.get("testOnly") is not True:
        raise EnvelopeError("malformed")
    event_id = payload.get("eventId")
    if not isinstance(event_id, str) or EVENT_ID.fullmatch(event_id) is None:
        raise EnvelopeError("malformed")
    if not _clean_text(event_id):
        raise EnvelopeError("malformed")
    source = payload.get("source")
    if source not in SOURCES or not _clean_text(source):
        raise EnvelopeError("malformed")
    observed = payload.get("observedAt")
    if not isinstance(observed, str) or OBSERVED_AT.fullmatch(observed) is None:
        raise EnvelopeError("malformed")
    if "conversationScope" in payload:
        scope = payload["conversationScope"]
        if not isinstance(scope, str) or not 1 <= len(scope) <= 40 or not _clean_text(scope):
            raise EnvelopeError("malformed")
        if scope != scope.strip():
            raise EnvelopeError("malformed")
    for value in payload.values():
        if isinstance(value, (dict, list)):
            raise EnvelopeError("malformed")
    raw = canonical(payload)
    if len(raw) > MAX_BYTES:
        raise EnvelopeError("oversize")
    return payload


def _validate_v2(payload: dict) -> dict:
    # A person wake carries an opaque local ref. It does not carry a name,
    # a phone, a digest of either, a count, or the v1 conversation scope.
    allowed = {"field", "eventId", "source", "observedAt", "testOnly", "chatRef"}
    if set(payload) != allowed:
        raise EnvelopeError("malformed")
    if payload.get("field") != SCHEMA_V2 or payload.get("testOnly") is not True:
        raise EnvelopeError("malformed")
    if payload.get("source") != "unread-indicator-hint":
        raise EnvelopeError("malformed")
    event_id = payload.get("eventId")
    if not isinstance(event_id, str) or EVENT_ID.fullmatch(event_id) is None or not _clean_text(event_id):
        raise EnvelopeError("malformed")
    observed = payload.get("observedAt")
    if not isinstance(observed, str) or OBSERVED_AT.fullmatch(observed) is None:
        raise EnvelopeError("malformed")
    chat_ref = payload.get("chatRef")
    if not isinstance(chat_ref, str) or CHAT_REF.fullmatch(chat_ref) is None or not _clean_text(chat_ref):
        raise EnvelopeError("malformed")
    raw = canonical(payload)
    if len(raw) > MAX_BYTES:
        raise EnvelopeError("oversize")
    return payload


def _validate_v3(payload: dict) -> dict:
    # A list-change wake names no chat. The browser chooses the current row.
    allowed = {"field", "eventId", "source", "observedAt", "testOnly"}
    if set(payload) != allowed:
        raise EnvelopeError("malformed")
    if payload.get("field") != SCHEMA_V3 or payload.get("testOnly") is not True:
        raise EnvelopeError("malformed")
    if payload.get("source") != "list-change":
        raise EnvelopeError("malformed")
    event_id = payload.get("eventId")
    if not isinstance(event_id, str) or EVENT_ID.fullmatch(event_id) is None or not _clean_text(event_id):
        raise EnvelopeError("malformed")
    observed = payload.get("observedAt")
    if not isinstance(observed, str) or OBSERVED_AT.fullmatch(observed) is None:
        raise EnvelopeError("malformed")
    raw = canonical(payload)
    if len(raw) > MAX_BYTES:
        raise EnvelopeError("oversize")
    return payload


def build_v3(*, event_id: str, observed_at: str) -> dict:
    return _validate_v3(
        {
            "field": SCHEMA_V3,
            "eventId": event_id,
            "source": "list-change",
            "observedAt": observed_at,
            "testOnly": True,
        }
    )


def build_v2(*, event_id: str, observed_at: str, chat_ref: str) -> dict:
    return _validate_v2(
        {
            "field": SCHEMA_V2,
            "eventId": event_id,
            "source": "unread-indicator-hint",
            "observedAt": observed_at,
            "testOnly": True,
            "chatRef": chat_ref,
        }
    )


def build(
    *,
    event_id: str,
    source: str,
    observed_at: str,
    conversation_scope: str | None = None,
) -> dict:
    payload = {
        "field": SCHEMA_FIELD,
        "eventId": event_id,
        "source": source,
        "observedAt": observed_at,
        "testOnly": True,
    }
    if conversation_scope is not None:
        payload["conversationScope"] = conversation_scope
    return validate(payload)
