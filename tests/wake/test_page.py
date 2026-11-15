import json
import unittest
from pathlib import Path

from wake.page import apply_page
from wake.read import bind_local, bind_metadata
from tests.wake.support import Scripted, pipeline

MARKER = "FIXTURE-LIVE-1915"
PREVIEW = "secret-preview-991"
OTHER = "FixtureOther-list-name"


class PageWakeTests(unittest.TestCase):
    def test_open_chat_one_inbound_posts_metadata_and_drafts(self):
        directory = Path("/tmp/wake-page-tail")
        _clear(directory)
        made, _clock, log, transport = pipeline(directory)
        bind_local(directory, "contact-a", "Me")
        first = apply_page(directory, _tail(_SEEDS), allowlist="contact-a", pipeline=made)
        self.assertEqual(first["disposition"], "BASELINE")
        self.assertFalse(first["posted"])
        self.assertEqual(transport.calls, [])
        second = apply_page(
            directory,
            _tail(_SEEDS + (("contact-a", MARKER, "09:02"),)),
            allowlist="contact-a",
            pipeline=made,
        )
        self.assertEqual(second["disposition"], "ONE_INBOUND")
        self.assertEqual(second["signal"], "open-tail")
        self.assertTrue(second["posted"])
        self.assertFalse(second["draft"])
        self.assertEqual(second["ack"], "transport-accepted")
        payload = json.loads(transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual(payload["source"], "web-page-change")
        self.assertEqual(payload["conversationScope"], "contact-a")
        self.assertNotIn("body", payload)
        self.assertEqual(set(payload), {"field", "eventId", "source", "observedAt", "testOnly", "conversationScope"})
        blob = _tree(directory) + log.text() + transport.calls[0]["body"].decode("utf-8")
        self.assertNotIn(MARKER, blob)
        self.assertNotIn("seed-one", blob)
        self.assertNotIn("LOCAL MOCK", blob)
        self.assertNotIn("local-mock-handler", blob)

    def test_open_chat_fail_closed_does_not_post(self):
        directory = Path("/tmp/wake-page-tail-gap")
        _clear(directory)
        made, _clock, _log, transport = pipeline(directory)
        bind_local(directory, "contact-a", "Me")
        apply_page(directory, _tail(_SEEDS), allowlist="contact-a", pipeline=made)
        cases = [
            _tail(_SEEDS + (("contact-a", "one", "09:02"), ("contact-a", "two", "09:03"))),
            _tail(_SEEDS + (("contact-a", MARKER, "凌晨3:16"),)),
            _tail(_SEEDS + (("contact-a", MARKER, "Monday 10:22 PM"),)),
            _tail(_SEEDS + (("contact-a", MARKER, "09:02"), ("contact-a", "other", "09:02"))),
            _tail(_SEEDS + (("", MARKER, "09:02"),)),
            {"layout": "probe-contract", "header": "contact-a", "phase": "loading", "slots": []},
            {"layout": "probe-contract", "header": "Other", "phase": "ready", "slots": []},
        ]
        for snapshot in cases:
            before = len(transport.calls)
            result = apply_page(directory, snapshot, allowlist="contact-a", pipeline=made)
            self.assertFalse(result["posted"], result["disposition"])
            self.assertFalse(result["draft"], result["disposition"])
            self.assertEqual(len(transport.calls), before)
        self.assertNotIn(MARKER, _tree(directory))

    def test_display_name_without_binding_does_not_wake(self):
        directory = Path("/tmp/wake-page-unbound")
        _clear(directory)
        made, _clock, _log, transport = pipeline(directory)
        result = apply_page(directory, _list(unread=True), allowlist="contact-a", pipeline=made)
        self.assertEqual(result["disposition"], "NOT_BOUND")
        self.assertFalse(result["posted"])
        self.assertEqual(transport.calls, [])
        mismatched = Path("/tmp/wake-page-mismatch")
        _clear(mismatched)
        made, _clock, _log, transport = pipeline(mismatched)
        bind_local(mismatched, "fixture chat", "Me")
        result = apply_page(mismatched, _tail([("fixture chat", "seed", "09:00")], header="fixture chat"), allowlist="contact-a", pipeline=made)
        self.assertEqual(result["disposition"], "SCOPE_MISMATCH")
        self.assertEqual(transport.calls, [])

    def test_chat_list_unread_posts_without_preview_or_other_rows(self):
        directory = Path("/tmp/wake-page-list")
        _clear(directory)
        made, _clock, log, transport = pipeline(directory)
        bind_local(directory, "contact-a", "Me")
        base = apply_page(directory, _list(unread=False, position=3), allowlist="contact-a", pipeline=made)
        self.assertEqual(base["disposition"], "BASELINE")
        self.assertFalse(base["posted"])
        reorder = apply_page(directory, _list(unread=False, position=0), allowlist="contact-a", pipeline=made)
        self.assertEqual(reorder["disposition"], "REORDER_ONLY")
        self.assertFalse(reorder["posted"])
        woken = apply_page(directory, _list(unread=True, position=0), allowlist="contact-a", pipeline=made)
        self.assertEqual(woken["disposition"], "ONE_UNREAD")
        self.assertEqual(woken["signal"], "chat-list")
        self.assertTrue(woken["posted"])
        self.assertFalse(woken["draft"])
        self.assertEqual(woken["ack"], "transport-accepted")
        payload = json.loads(transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual(payload["source"], "web-page-change")
        self.assertEqual(payload["conversationScope"], "contact-a")
        self.assertNotIn(PREVIEW, payload.values())
        self.assertFalse((directory / "read-drafts.json").exists())
        item = made.outbox.items[woken["event"]]
        self.assertIsNone(item.draft)
        self.assertEqual(item.reason, "transport-accepted")
        blob = _tree(directory) + log.text()
        self.assertNotIn(PREVIEW, blob)
        self.assertNotIn(OTHER, blob)
        self.assertNotIn("LOCAL MOCK", blob)
        self.assertNotIn("local-mock-handler", blob)
        again = apply_page(directory, _list(unread=True, position=0), allowlist="contact-a", pipeline=made)
        self.assertEqual(again["disposition"], "NO_NEW")
        self.assertEqual(len(transport.calls), 1)

    def test_chat_list_is_fail_closed(self):
        directory = Path("/tmp/wake-page-list-gap")
        _clear(directory)
        made, _clock, _log, transport = pipeline(directory)
        bind_local(directory, "contact-a", "Me")
        apply_page(directory, _list(unread=False), allowlist="contact-a", pipeline=made)
        several = apply_page(directory, _list(unread=True, other=1), allowlist="contact-a", pipeline=made)
        self.assertEqual(several["disposition"], "SEVERAL_CHANGES")
        self.assertFalse(several["posted"])
        planted = dict(_list(unread=True), preview=PREVIEW, rows=[{"name": OTHER}])
        rejected = apply_page(directory, planted, allowlist="contact-a", pipeline=made)
        self.assertEqual(rejected["disposition"], "UNTRUSTED_FIELD")
        duplicate = apply_page(directory, _list(unread=True, matches=2), allowlist="contact-a", pipeline=made)
        self.assertEqual(duplicate["disposition"], "NOT_UNIQUE")
        self.assertEqual(transport.calls, [])
        self.assertNotIn(PREVIEW, _tree(directory))
        self.assertNotIn(OTHER, _tree(directory))
        moved = apply_page(directory, _list(unread=False, position=0), allowlist="contact-a", pipeline=made)
        self.assertEqual(moved["disposition"], "REORDER_ONLY")
        apply_page(directory, _list(unread=True, position=0), allowlist="contact-a", pipeline=made)
        second = apply_page(directory, _list(unread=True, position=4), allowlist="contact-a", pipeline=made)
        self.assertEqual(second["disposition"], "ALREADY_UNREAD")
        self.assertEqual(len(transport.calls), 1)

    def test_numbered_badge_wakes_on_rise_only(self):
        directory = Path("/tmp/wake-page-count")
        _clear(directory)
        made, clock, log, transport = pipeline(
            directory,
            transport=Scripted([(200, b'{"accepted":true,"unique":true,"duplicate":false}')] * 4),
        )
        bind_metadata(directory, "contact-a")
        secret = "secret-count-body"
        visible = apply_page(directory, _count(4), allowlist="contact-a", pipeline=made)
        self.assertEqual(visible["disposition"], "COUNT_BASELINE")
        self.assertEqual(visible["change"], "baseline")
        self.assertEqual(visible["count"], 4)
        self.assertFalse(visible["posted"])
        self.assertEqual(transport.calls, [])
        same = apply_page(directory, _count(4, other=3, position=0), allowlist="contact-a", pipeline=made)
        self.assertEqual(same["disposition"], "NO_NEW")
        self.assertEqual(same["change"], "same")
        self.assertFalse(same["posted"])
        self.assertEqual(transport.calls, [])
        rose = apply_page(directory, _count(5, other=2, position=0), allowlist="contact-a", pipeline=made)
        self.assertEqual(rose["disposition"], "COUNT_UP")
        self.assertEqual(rose["change"], "up")
        self.assertEqual(rose["prior"], 4)
        self.assertEqual(rose["count"], 5)
        self.assertTrue(rose["posted"])
        self.assertEqual(rose["forward"], "accepted")
        self.assertFalse(rose["draft"])
        self.assertRegex(rose["event"], r"^evt-[0-9a-f]{32}$")
        self.assertEqual(len(transport.calls), 1)
        hint = json.loads(transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual(hint["field"], "whatsapp-wake-test-v1")
        self.assertEqual(hint["source"], "unread-indicator-hint")
        self.assertIs(hint["testOnly"], True)
        self.assertEqual(hint["conversationScope"], "contact-a")
        self.assertEqual(hint["eventId"], rose["event"])
        self.assertEqual(set(hint), {"field", "eventId", "source", "observedAt", "testOnly", "conversationScope"})
        self.assertNotIn("count", hint)
        down = apply_page(directory, _count(2), allowlist="contact-a", pipeline=made)
        self.assertEqual(down["disposition"], "COUNT_DOWN")
        self.assertFalse(down["posted"])
        self.assertEqual(len(transport.calls), 1)
        cleared = apply_page(directory, _mark("absent"), allowlist="contact-a", pipeline=made)
        self.assertEqual(cleared["disposition"], "COUNT_CLEARED")
        self.assertEqual(cleared["change"], "clear")
        self.assertFalse(cleared["posted"])
        self.assertEqual(cleared["forward"], "none")
        self.assertEqual(cleared["lastEvent"], rose["event"])
        self.assertEqual(len(transport.calls), 1)
        again = apply_page(directory, _count(1, other=4), allowlist="contact-a", pipeline=made)
        self.assertEqual(again["disposition"], "COUNT_UP")
        self.assertTrue(again["posted"])
        self.assertNotEqual(again["event"], rose["event"])
        self.assertEqual(len(transport.calls), 2)
        ambiguous = apply_page(directory, _mark("ambiguous"), allowlist="contact-a", pipeline=made)
        self.assertEqual(ambiguous["disposition"], "UNREAD_AMBIGUOUS")
        self.assertEqual(ambiguous["change"], "held")
        self.assertEqual(json.loads((directory / "list-window.json").read_text(encoding="utf-8"))["count"], 1)
        self.assertEqual(apply_page(directory, _count(1), allowlist="contact-a", pipeline=made)["disposition"], "NO_NEW")
        self.assertEqual(len(transport.calls), 2)
        dot = apply_page(directory, _mark("dot", other=1), allowlist="contact-a", pipeline=made)
        self.assertEqual(dot["disposition"], "UNREAD_DOT")
        self.assertEqual(dot["forward"], "none")
        self.assertFalse(dot["posted"])
        self.assertEqual(json.loads((directory / "list-window.json").read_text(encoding="utf-8"))["count"], 1)
        unknown = apply_page(directory, _mark("unknown"), allowlist="contact-a", pipeline=made)
        self.assertEqual(unknown["disposition"], "UNREAD_UNKNOWN")
        self.assertEqual(json.loads((directory / "list-window.json").read_text(encoding="utf-8"))["count"], 1)
        boolean = apply_page(directory, _list(unread=True, position=0), allowlist="contact-a", pipeline=made)
        self.assertEqual(boolean["disposition"], "NOT_A_WAKE")
        self.assertFalse(boolean["posted"])
        self.assertFalse((directory / "read-drafts.json").exists())
        self.assertEqual(apply_page(directory, _count(1, matches=2), allowlist="contact-a", pipeline=made)["disposition"], "NOT_UNIQUE")
        bad = _count(1)
        bad["count"] = True
        self.assertEqual(apply_page(directory, bad, allowlist="contact-a", pipeline=made)["disposition"], "UNPARSEABLE")
        self.assertEqual(json.loads((directory / "list-window.json").read_text(encoding="utf-8"))["count"], 1)
        blocked = apply_page(
            directory,
            {
                "layout": "probe-contract",
                "header": "contact-a",
                "phase": "ready",
                "slots": [{"kind": "message", "sender": "contact-a", "text": secret, "timeText": "09:01"}],
            },
            allowlist="contact-a",
            pipeline=made,
        )
        self.assertEqual(blocked["disposition"], "DIRECTION_UNPROVEN")
        self.assertEqual(len(transport.calls), 2)
        clock.advance(2)
        restarted, _clock2, _log2, restarted_transport = pipeline(directory)
        replay = apply_page(directory, _count(1), allowlist="contact-a", pipeline=restarted)
        self.assertEqual(replay["disposition"], "NO_NEW")
        self.assertFalse(replay["posted"])
        self.assertEqual(restarted_transport.calls, [])
        blob = _tree(directory) + log.text()
        self.assertNotIn(secret, blob)
        self.assertNotIn("個未讀訊息", blob)
        self.assertNotIn("未讀", blob)
        self.assertNotIn("icon-unread-count", blob)
        self.assertNotIn("ONE_UNREAD", blob)

    def test_count_retry_migration_and_messages_mode(self):
        directory = Path("/tmp/wake-page-count-retry")
        _clear(directory)
        made, clock, log, transport = pipeline(
            directory,
            transport=Scripted(
                [
                    (503, b"{}"),
                    (200, b'{"accepted":true,"unique":true,"duplicate":false}'),
                    (200, b'{"accepted":true,"unique":true,"duplicate":false}'),
                ]
            ),
        )
        binding, reason = bind_metadata(directory, "contact-a")
        self.assertEqual(reason, "BOUND")
        (directory / "list-window.json").write_text(
            json.dumps(
                {
                    "scopeId": binding["localScopeId"],
                    "baseline": True,
                    "position": 1,
                    "unread": False,
                    "mark": "absent",
                }
            ),
            encoding="utf-8",
        )
        migrated = apply_page(directory, _count(1), allowlist="contact-a", pipeline=made)
        self.assertEqual(migrated["disposition"], "COUNT_BASELINE")
        self.assertFalse(migrated["posted"])
        self.assertEqual(transport.calls, [])
        failed = apply_page(directory, _count(2, other=2), allowlist="contact-a", pipeline=made)
        self.assertEqual(failed["disposition"], "COUNT_UP")
        self.assertEqual(failed["forward"], "attempted")
        self.assertFalse(failed["posted"])
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(json.loads((directory / "list-window.json").read_text(encoding="utf-8"))["count"], 1)
        clock.advance(2)
        cleared = apply_page(directory, _mark("absent"), allowlist="contact-a", pipeline=made)
        self.assertEqual(cleared["disposition"], "COUNT_HELD")
        self.assertFalse(cleared["posted"])
        self.assertEqual(json.loads((directory / "list-window.json").read_text(encoding="utf-8"))["count"], 1)
        retried = apply_page(directory, _count(2, other=1), allowlist="contact-a", pipeline=made)
        self.assertEqual(retried["forward"], "accepted")
        self.assertTrue(retried["posted"])
        self.assertEqual(len(transport.calls), 2)
        first = json.loads(transport.calls[0]["body"].decode("utf-8"))["eventId"]
        second = json.loads(transport.calls[1]["body"].decode("utf-8"))["eventId"]
        self.assertEqual(first, second)
        self.assertEqual(first, failed["event"])
        self.assertEqual(json.loads((directory / "list-window.json").read_text(encoding="utf-8"))["count"], 2)
        clock.advance(2)
        restarted, _clock2, _log2, restarted_transport = pipeline(directory)
        replay = apply_page(directory, _count(2), allowlist="contact-a", pipeline=restarted)
        self.assertEqual(replay["disposition"], "NO_NEW")
        self.assertEqual(replay["forward"], "none")
        self.assertEqual(replay["posted"], False)
        self.assertEqual(replay["lastEvent"], first)
        self.assertEqual(restarted_transport.calls, [])
        plain = Path("/tmp/wake-page-count-messages")
        _clear(plain)
        message_pipe, _c, _l, message_transport = pipeline(plain)
        bind_local(plain, "contact-a", "Me")
        apply_page(plain, _mark("absent"), allowlist="contact-a", pipeline=message_pipe)
        skipped = apply_page(plain, _count(3), allowlist="contact-a", pipeline=message_pipe)
        self.assertEqual(skipped["disposition"], "COUNT_UP")
        self.assertEqual(skipped["forward"], "none")
        self.assertFalse(skipped["posted"])
        self.assertEqual(message_transport.calls, [])
        self.assertEqual(apply_page(plain, _count(3), allowlist="contact-a", pipeline=message_pipe)["disposition"], "NO_NEW")
        blob = _tree(directory) + log.text()
        self.assertNotIn("未讀", blob)
        self.assertNotIn("個未讀訊息", blob)

    def test_unknown_unread_does_not_baseline_or_post(self):
        directory = Path("/tmp/wake-page-unread-unknown")
        _clear(directory)
        made, _clock, log, transport = pipeline(directory)
        bind_local(directory, "contact-a", "Me")
        unknown = _list(unread=False, position=1)
        unknown["unread"] = None
        first = apply_page(directory, unknown, allowlist="contact-a", pipeline=made)
        self.assertEqual(first["disposition"], "UNREAD_UNKNOWN")
        self.assertFalse(first["posted"])
        self.assertFalse(first["draft"])
        self.assertEqual(transport.calls, [])
        self.assertFalse((directory / "list-window.json").exists())
        planted = dict(unknown, preview=PREVIEW, rows=[{"name": OTHER}])
        rejected = apply_page(directory, planted, allowlist="contact-a", pipeline=made)
        self.assertEqual(rejected["disposition"], "UNTRUSTED_FIELD")
        base = apply_page(directory, _list(unread=False, position=1), allowlist="contact-a", pipeline=made)
        self.assertEqual(base["disposition"], "BASELINE")
        self.assertFalse(base["posted"])
        self.assertNotIn(PREVIEW, _tree(directory) + log.text())
        self.assertNotIn(OTHER, _tree(directory) + log.text())

    def test_failed_post_does_not_draft_or_store_text(self):
        directory = Path("/tmp/wake-page-retry")
        _clear(directory)
        transport = Scripted([(503, b"{}")])
        made, _clock, log, transport = pipeline(directory, transport=transport)
        bind_local(directory, "contact-a", "Me")
        apply_page(directory, _tail(_SEEDS), allowlist="contact-a", pipeline=made)
        result = apply_page(
            directory,
            _tail(_SEEDS + (("contact-a", MARKER, "09:02"),)),
            allowlist="contact-a",
            pipeline=made,
        )
        self.assertEqual(result["disposition"], "WAKE_NOT_ACKED")
        self.assertTrue(result["posted"])
        self.assertFalse(result["draft"])
        self.assertFalse((directory / "read-drafts.json").exists())
        self.assertNotIn(MARKER, _tree(directory) + log.text())
        self.assertNotIn("127.0.0.1", log.text())


_SEEDS = (("Me", "seed-one", "09:00"), ("contact-a", "seed-two", "09:01"))


def _tail(rows, header="contact-a"):
    return {
        "layout": "probe-contract",
        "header": header,
        "phase": "ready",
        "slots": [
            {"kind": "message", "sender": sender, "text": text, "timeText": clock}
            for sender, text, clock in rows
        ],
    }


def _mark(mark: str, position: int = 1, matches: int = 1, other: int = 0):
    payload = _list(unread=False, position=position, matches=matches, other=other)
    payload["mark"] = mark
    payload["unread"] = False if mark == "absent" else None
    if mark == "absent":
        payload["count"] = 0
    return payload


def _count(count: int, position: int = 1, matches: int = 1, other: int = 0):
    payload = _list(unread=False, position=position, matches=matches, other=other)
    payload["mark"] = "count"
    payload["unread"] = None
    payload["count"] = count
    return payload


def _list(*, unread: bool, position: int = 2, matches: int = 1, other: int = 0):
    return {
        "layout": "chat-list-contract",
        "boundLabel": "contact-a",
        "matches": matches,
        "position": position,
        "unread": unread,
        "otherChanges": other,
    }


def _tree(directory: Path) -> str:
    parts = []
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _clear(directory: Path) -> None:
    if directory.exists():
        for child in sorted(directory.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
    directory.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    unittest.main()
