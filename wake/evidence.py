"""Evidence this package can record. Version: wake-evidence-1.

An HTTP acknowledgement, a queued or in-flight wake, and a reference-receiver
stage are not a recorded bot response. The user's own routine may still
inspect the page and draft; this module does not observe that draft.
Coverage is only the reference stage ``covered``, and only because a
finished observation listed the id. This module does not open a socket.
"""

CONTRACT = "wake-evidence-1"

# Machine values stay English. Traditional Chinese is a display label.
LABELS_ZH_HANT = {
    "absent": "不存在",
    "queued": "已排隊",
    "inflight": "處理中",
    "transport-accepted": "傳輸已接受",
    "legacy-409": "舊版停止",
    "retryable": "可再試",
    "rejected": "已拒絕",
    "local-test-receipt": "僅限本機測試回條",
    "pending": "待處理",
    "scheduled": "已排程",
    "covered": "已由完成的觀察列出",
    "unresolved": "未解決",
    "unrecognized": "無法辨識",
    "response-unverified": "尚未證實機器人已完成",
}

HOST_STAGES = (
    "absent",
    "queued",
    "inflight",
    "transport-accepted",
    "legacy-409",
    "retryable",
    "rejected",
    "local-test-receipt",
    "unrecognized",
)

REFERENCE_STAGES = (
    "absent",
    "pending",
    "scheduled",
    "inflight",
    "covered",
    "unresolved",
)

NOT_COVERED = frozenset({"pending", "scheduled", "inflight", "queued", "unresolved", "absent"})


class Evidence:
    def __init__(self, stage: str, source: str, proves: frozenset, mock: bool) -> None:
        self.stage = stage
        self.source = source
        self.proves = proves
        self.mock = bool(mock)

    def proves_incoming(self) -> bool:
        return False

    def proves_bot_response(self) -> bool:
        return False

    def proves_covered(self) -> bool:
        return self.stage == "covered" and "listed-by-observation" in self.proves

    def label(self, language: str = "en") -> str:
        if language == "zh-Hant":
            return LABELS_ZH_HANT[self.stage]
        return self.stage


def stored_reason(classification: str, duplicate: bool) -> str:
    """Same strings the outbox already stores. Official 2xx is not a draft."""

    if classification == "transport":
        return "transport-accepted"
    if classification == "legacy-409":
        return "legacy-409"
    if duplicate:
        return "duplicate"
    return "acked"


def from_client(result, mode: str) -> Evidence:
    """Classify a webhook client result. The body is not consulted here."""

    classification = getattr(result, "classification", "none")
    status = getattr(result, "status", "")
    if status != "acked":
        if status == "retryable":
            return _host("retryable", frozenset())
        return _host("rejected", frozenset())
    if classification == "transport":
        return _host("transport-accepted", frozenset({"http-accepted"}))
    if classification == "legacy-409":
        return _host("legacy-409", frozenset({"legacy-stop"}))
    if mode == "test-receipt" and classification in ("receipt", "receipt-duplicate"):
        return Evidence(
            "local-test-receipt",
            "local-test-routine",
            frozenset({"test-fixture"}),
            True,
        )
    return _host("rejected", frozenset())


def from_outbox(state: str, reason: str) -> Evidence:
    """Map a stored outbox row. Pending and in-flight are not covered."""

    if state == "pending":
        return _host("queued", frozenset({"stored"}))
    if state == "in_flight":
        return _host("inflight", frozenset({"stored"}))
    if state == "retryable":
        return _host("retryable", frozenset({"stored"}))
    if state == "rejected":
        return _host("rejected", frozenset({"stored"}))
    if state == "acked" and reason == "transport-accepted":
        return _host("transport-accepted", frozenset({"http-accepted", "stored"}))
    if state == "acked" and reason == "legacy-409":
        return _host("legacy-409", frozenset({"legacy-stop", "stored"}))
    if state == "acked" and reason in ("acked", "duplicate"):
        return Evidence(
            "local-test-receipt",
            "local-test-routine",
            frozenset({"test-fixture", "stored"}),
            True,
        )
    return _host("unrecognized", frozenset())


def from_reference_state(stage: str) -> Evidence:
    """Interpret one reference-receiver stage. The host does not install it."""

    if stage not in REFERENCE_STAGES:
        return _host("unrecognized", frozenset())
    proves = frozenset()
    if stage == "covered":
        proves = frozenset({"listed-by-observation"})
    return Evidence(stage, "reference-example", proves, False)


def response_blocker(record) -> str:
    """Why this package has not recorded a completed bot response.

    The user's routine may still draft outside this process. A transport
    row, a queue stage, a reference stage, or a caller-supplied dict is
    not that observation. This is not a claim that the routine cannot draft.
    """

    if isinstance(record, Evidence):
        if record.stage == "transport-accepted":
            return "transport-is-not-a-response"
        if record.stage == "local-test-receipt" or record.mock:
            return "local-test-fixture"
        if record.stage == "covered":
            return "coverage-is-not-a-bot-response"
        if record.stage in NOT_COVERED or record.stage in HOST_STAGES:
            return "not-a-bot-response"
    return "no-response-interface"


def labels_cover_contract() -> bool:
    required = set(HOST_STAGES) | set(REFERENCE_STAGES) | {"response-unverified"}
    return required <= set(LABELS_ZH_HANT)


def _host(stage: str, proves: frozenset) -> Evidence:
    return Evidence(stage, "host", proves, False)
