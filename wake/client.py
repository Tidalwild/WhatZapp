import json
import urllib.error
import urllib.request

from wake.config import authorization_value, usable_secret
from wake.envelope import EnvelopeError, canonical, validate


class ClientResult:
    def __init__(self, status: str, duplicate: bool = False, classification: str = "none") -> None:
        if status not in ("acked", "retryable", "rejected"):
            raise ValueError("status")
        if classification not in ("none", "transport", "legacy-409", "receipt", "receipt-duplicate"):
            raise ValueError("classification")
        self.status = status
        self.duplicate = bool(duplicate)
        self.classification = classification


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibTransport:
    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirect)

    def __call__(self, url: str, authorization: str, body: bytes, timeout: float):
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("Authorization", authorization)
        request.add_header("Accept", "application/json")
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return int(response.status), response.read(2048)
        except urllib.error.HTTPError as exc:
            try:
                payload = exc.read(2048)
            except Exception:
                payload = b""
            return int(exc.code), payload


class WebhookClient:
    def __init__(self, url: str, authorization: str, transport=None, mode: str = "official") -> None:
        self._url = url
        value, _form = authorization_value(authorization)
        self._authorization = value if usable_secret(value) else ""
        self._transport = transport or UrllibTransport()
        # official matches the deployed webhook: the status code is transport.
        # test-receipt is only the local wake/routine.py body, and it is not the default.
        self._mode = mode if mode == "test-receipt" else "official"

    def post(self, payload: dict) -> ClientResult:
        try:
            validate(payload)
            raw = canonical(payload)
        except EnvelopeError:
            return ClientResult("rejected")
        try:
            status, body = self._transport(self._url, self._authorization, raw, 5)
        except Exception:
            return ClientResult("retryable")
        if self._mode == "test-receipt" and (status == 409 or 200 <= status < 300):
            return _test_receipt(status, body)
        if 200 <= status < 300:
            return ClientResult("acked", False, "transport")
        if status == 409:
            # The live 0.2.10 host treated 409 as a duplicate stop. The official
            # webhook does not document a 409 body, so this label is legacy only.
            return ClientResult("acked", True, "legacy-409")
        if status >= 500:
            return ClientResult("retryable")
        return ClientResult("rejected")


def _test_receipt(status: int, body: bytes) -> ClientResult:
    # Optional local contract. The official webhook does not use this body.
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return ClientResult("rejected")
    if not isinstance(parsed, dict):
        return ClientResult("rejected")
    accepted = parsed.get("accepted") is True
    unique = parsed.get("unique")
    duplicate = parsed.get("duplicate")
    if accepted and unique is False and duplicate is True:
        return ClientResult("acked", True, "receipt-duplicate")
    if status != 409 and accepted and unique is True and duplicate is False:
        return ClientResult("acked", False, "receipt")
    return ClientResult("rejected")
