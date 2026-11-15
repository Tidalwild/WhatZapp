import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from wake.policy import valid_label

# A pasted credential sometimes includes the header field name. The value after
# that name is what the receiver compares. The scheme, if any, stays in the value.
_HEADER_PREFIX = re.compile(r"^authorization\s*:\s*", re.IGNORECASE)

KEYS = (
    "WHATSAPP_WAKE_ENABLED",
    "WHATSAPP_WAKE_URL",
    "WHATSAPP_WAKE_AUTHORIZATION",
    "WHATSAPP_WAKE_ALLOWLIST_LABEL",
    "WHATSAPP_WAKE_ROUTINE_AUTHORIZATION",
    "WHATSAPP_WAKE_WIRE",
    "WHATSAPP_WAKE_TRANSPORT",
)


@dataclass(frozen=True)
class Config:
    enabled: bool
    url: str
    authorization: str
    auth_form: str
    label: str
    routine_authorization: str
    wire: str
    transport: str


def default_config_path(env: dict) -> str:
    if "WHATSAPP_WAKE_CONFIG" in env:
        return env.get("WHATSAPP_WAKE_CONFIG") or ""
    base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return str(Path(base) / "draft-bridge" / "wake.env")


def read_env_file(path: str) -> dict:
    if not path:
        return {}
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError:
        return {}
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if key not in KEYS:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def load_config(env: dict | None = None) -> Config:
    source = os.environ if env is None else env
    merged = read_env_file(default_config_path(source))
    for key in KEYS:
        if key in source and source.get(key) is not None:
            merged[key] = str(source.get(key))
    authorization, auth_form = authorization_value(merged.get("WHATSAPP_WAKE_AUTHORIZATION") or "")
    routine, _form = authorization_value(merged.get("WHATSAPP_WAKE_ROUTINE_AUTHORIZATION") or "")
    if not usable_secret(authorization):
        authorization, auth_form = "", "missing"
    if not usable_secret(routine):
        routine = ""
    return Config(
        enabled=merged.get("WHATSAPP_WAKE_ENABLED") == "1",
        url=merged.get("WHATSAPP_WAKE_URL") or "",
        authorization=authorization,
        auth_form=auth_form,
        label=merged.get("WHATSAPP_WAKE_ALLOWLIST_LABEL") or "",
        routine_authorization=routine,
        wire=_wire(merged.get("WHATSAPP_WAKE_WIRE")),
        transport=_transport_mode(merged.get("WHATSAPP_WAKE_TRANSPORT")),
    )


def _transport_mode(value: object) -> str:
    if value == "test-receipt":
        return "test-receipt"
    return "official"


def _wire(value: object) -> str:
    if value == "v2":
        return "v2"
    if value == "list":
        return "list"
    return "v1"


def authorization_value(raw: object) -> tuple:
    """Return the header value and whether a field name was removed.

    ``Authorization: <secret>`` and ``authorization:<secret>`` both become
    ``<secret>``. A value that is already only the secret is unchanged.
    The word before the colon is not sent again, so the wire header is a
    single field. At most two pasted field names are removed.
    """

    if not isinstance(raw, str):
        return "", "missing"
    text = raw.strip()
    if not text:
        return "", "missing"
    form = "value"
    for _ in range(2):
        if _HEADER_PREFIX.match(text) is None:
            break
        text = _HEADER_PREFIX.sub("", text, count=1).strip()
        form = "normalized"
    if not text:
        return "", "missing"
    return text, form


def usable_secret(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 500:
        return False
    if any(ord(char) < 32 for char in value):
        return False
    if "://" in value:
        return False
    return True


def valid_url(url: str) -> bool:
    if not isinstance(url, str) or not url or len(url) > 300:
        return False
    if any(char.isspace() or ord(char) < 32 for char in url):
        return False
    parts = urlsplit(url)
    if parts.username or parts.password or parts.query or parts.fragment:
        return False
    host = parts.hostname
    if not host:
        return False
    if parts.scheme == "https":
        return True
    if parts.scheme == "http" and host in ("127.0.0.1", "localhost") and parts.port:
        return True
    return False


def transmission_ready(config: Config) -> bool:
    return bool(
        config.enabled
        and config.authorization.strip()
        and valid_url(config.url)
        and valid_label(config.label)
    )
