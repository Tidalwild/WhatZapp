import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from wake.envelope import EnvelopeError, validate

MAX_EVENT_IDS = 100
DEFAULT_STORE = Path(__file__).resolve().parents[1] / "whatsapp-wake-test"


class RoutineStore:
    """Dedup store for the local test routine. It does not read a chat or send."""

    def __init__(self, directory, authorization: str, max_ids: int = MAX_EVENT_IDS) -> None:
        if not authorization:
            raise RuntimeError("empty authorization")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.authorization = authorization
        self.max_ids = int(max_ids)
        self.ids = []
        self.ready = False
        self.lock = threading.Lock()
        self.load()

    def load(self) -> None:
        path = self.directory / "event-ids.json"
        if not path.exists():
            self.ids = []
            self.ready = True
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ids = data["ids"]
            if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                raise ValueError("ids")
            if len(ids) > self.max_ids or len(set(ids)) != len(ids):
                raise ValueError("ids")
            self.ids = ids
            self.ready = True
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            self.ready = False
            self.ids = []

    def handle(self, authorization: str | None, body: bytes) -> tuple:
        with self.lock:
            if not self.ready:
                return 503, {"accepted": False, "reason": "corrupt"}
            if not _authorized(self.authorization, authorization or ""):
                return 401, {"accepted": False, "reason": "auth"}
            if len(body) > 512:
                return 400, {"accepted": False, "reason": "oversize"}
            try:
                payload = validate(json.loads(body.decode("utf-8")))
            except (EnvelopeError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                return 400, {"accepted": False, "reason": "malformed"}
            event_id = payload["eventId"]
            if event_id in self.ids:
                count = len(self.ids)
                self._receipt(event_id, unique=False, count=count, source=payload["source"])
                return 200, {
                    "accepted": True,
                    "duplicate": True,
                    "unique": False,
                    "uniqueCount": count,
                }
            if len(self.ids) >= self.max_ids:
                return 429, {"accepted": False, "reason": "cap"}
            self.ids.append(event_id)
            self._write_ids()
            self._draft(event_id)
            self._receipt(event_id, unique=True, count=len(self.ids), source=payload["source"])
            return 200, {
                "accepted": True,
                "duplicate": False,
                "unique": True,
                "uniqueCount": len(self.ids),
            }

    def _write_ids(self) -> None:
        path = self.directory / "event-ids.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"ids": self.ids, "max": self.max_ids}, sort_keys=True), encoding="utf-8")
        temporary.replace(path)

    def _draft(self, event_id: str) -> None:
        path = self.directory / "drafts.json"
        drafts = []
        if path.exists():
            try:
                drafts = json.loads(path.read_text(encoding="utf-8")).get("drafts") or []
            except (OSError, json.JSONDecodeError):
                drafts = []
        drafts.append(
            {
                "eventId": event_id,
                "handler": "local-mock-handler",
                "placeholder": "LOCAL MOCK",
                "sendingEnabled": False,
                "sent": False,
                "verifiedRemoteRecipient": False,
                "readsChat": False,
                "sendsWhatsApp": False,
            }
        )
        path.write_text(json.dumps({"drafts": drafts}, sort_keys=True), encoding="utf-8")

    def _receipt(self, event_id: str, *, unique: bool, count: int, source: str) -> None:
        row = {
            "eventId": event_id,
            "unique": unique,
            "uniqueCount": count,
            "source": source,
            "testOnly": True,
            "readsChat": False,
            "sends": False,
        }
        with (self.directory / "receipts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        text = (
            f"unique={'yes' if unique else 'no'}\n"
            f"eventId={event_id}\n"
            f"uniqueCount={count}\n"
            f"source={source}\n"
            "readsChat=no\n"
            "sends=no\n"
        )
        (self.directory / "latest-receipt.txt").write_text(text, encoding="utf-8")


def _authorized(expected: str, presented: str) -> bool:
    left = expected.encode("utf-8")
    right = presented.encode("utf-8")
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


class RoutineHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        if self.path != "/":
            self._send(404, {"accepted": False, "reason": "path"})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            self._send(400, {"accepted": False, "reason": "malformed"})
            return
        if length < 0 or length > 512:
            # Drain a bounded amount so the socket can finish. The bytes are not stored.
            if length > 0:
                remaining = min(length, 8192)
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 1024))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            self.close_connection = True
            self._send(400, {"accepted": False, "reason": "oversize" if length > 512 else "malformed"})
            return
        body = self.rfile.read(length)
        code, payload = self.server.store.handle(self.headers.get("Authorization"), body)
        self._send(code, payload)

    def do_GET(self) -> None:
        self._send(405, {"accepted": False, "reason": "method"})

    def log_message(self, format, *args) -> None:
        return

    def _send(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)


class RoutineServer(ThreadingHTTPServer):
    def __init__(self, address, store: RoutineStore) -> None:
        self.store = store
        super().__init__(address, RoutineHandler)


def serve(store: RoutineStore, host: str = "127.0.0.1", port: int = 0) -> RoutineServer:
    if host not in ("127.0.0.1", "localhost"):
        raise RuntimeError("refusing non-loopback bind")
    server = RoutineServer((host, port), store)
    server.daemon_threads = True
    return server
