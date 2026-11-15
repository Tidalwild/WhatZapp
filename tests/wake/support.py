import subprocess
import time
from pathlib import Path

from wake.client import WebhookClient
from wake.clock import FakeClock
from wake.log import Log
from wake.model import Observation
from wake.outbox import Outbox
from wake.pipeline import Pipeline


class Scripted:
    def __init__(self, results) -> None:
        self.results = list(results)
        self.calls = []

    def __call__(self, url, authorization, body, timeout):
        self.calls.append(
            {"url": url, "authorization": authorization, "body": body, "timeout": timeout}
        )
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def pipeline(directory, *, enabled=True, label="contact-a", limit=8, debounce=1.5, attempts=5, transport=None, client=True, mode="official"):
    clock = FakeClock()
    box = Outbox(
        Path(directory) / "outbox.json",
        clock,
        debounce=debounce,
        rate_limit=limit,
        max_attempts=attempts,
    )
    log = Log()
    transport = Scripted([(200, b'{"accepted":true,"unique":true,"duplicate":false}')]) if transport is None else transport
    webhook = None
    if client:
        webhook = WebhookClient("http://127.0.0.1:9/", "local-test-only", transport, mode=mode)
    made = Pipeline(outbox=box, allowlist=label, enabled=enabled, client=webhook, log=log)
    return made, clock, log, transport


def observation(summary="contact-a", replaces_id=7, origin="session-bus", app_name="WhatsApp"):
    return Observation(app_name, replaces_id, summary, origin)


def start_private_bus(directory: Path):
    sock = directory / "bus"
    proc = subprocess.Popen(
        [
            "dbus-daemon",
            "--session",
            f"--address=unix:path={sock}",
            "--nofork",
            "--nopidfile",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        if sock.exists():
            return proc, f"unix:path={sock}"
        if proc.poll() is not None:
            raise RuntimeError("private dbus-daemon exited")
        time.sleep(0.05)
    raise RuntimeError("private dbus socket did not appear")
