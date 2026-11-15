import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from wake.bridge import read_frame, read_handshake, read_host, run_stdio, write_frame
from wake.config import load_config
from wake.lifecycle import clear_stop, request_stop
from wake.page import apply_page
from wake.read import bind_local, bind_metadata
from tests.wake.support import Scripted, pipeline

MARKER = "secret-injected-preview"
OTHER = "secret-sam-preview"
REPO = Path(__file__).resolve().parents[2]


class BridgeTests(unittest.TestCase):
    def test_continuous_frames_post_once_and_drop_extra_fields(self):
        directory = Path("/tmp/wake-bridge-frames")
        _clear(directory)
        made, _clock, log, transport = pipeline(directory)
        env = _env(directory)
        config = load_config(env)
        bind_local(directory, "contact-a", "Me")
        stdout = io.BytesIO()
        stdin = io.BytesIO(_frames(
            {"v": 1, "kind": "hello"},
            _signal(False),
            _signal(True),
            _signal(True),
            dict(_signal(True), preview=MARKER, rows=[{"name": OTHER}]),
        ))
        code = run_stdio(env, stdin, stdout, made)
        self.assertEqual(code, 0)
        self.assertEqual(len(transport.calls), 1)
        payload = json.loads(transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual(payload["source"], "web-page-change")
        self.assertEqual(payload["conversationScope"], "contact-a")
        self.assertNotIn("body", payload)
        blob = _tree(directory) + log.text() + transport.calls[0]["body"].decode("utf-8") + stdout.getvalue().decode("utf-8")
        self.assertNotIn(MARKER, blob)
        self.assertNotIn(OTHER, blob)
        codes = _codes(stdout.getvalue())
        self.assertEqual(codes.count("ONE_UNREAD"), 1)
        self.assertIn("NO_NEW", codes)
        self.assertIn("UNTRUSTED_FIELD", codes)
        again = io.BytesIO()
        run_stdio(env, io.BytesIO(_frames(_signal(True))), again, made)
        self.assertEqual(len(transport.calls), 1)
        self.assertIn("NO_NEW", _codes(again.getvalue()))

    def test_stop_default_off_and_oversize_do_not_post(self):
        directory = Path("/tmp/wake-bridge-gates")
        _clear(directory)
        made, _clock, log, transport = pipeline(directory, enabled=False)
        env = _env(directory, enabled="0")
        bind_local(directory, "contact-a", "Me")
        stdout = io.BytesIO()
        run_stdio(env, io.BytesIO(_frames(_signal(False), _signal(True))), stdout, made)
        self.assertEqual(transport.calls, [])
        self.assertIn("DISABLED", _codes(stdout.getvalue()))
        self.assertNotIn(MARKER, _tree(directory) + log.text())

        made, _clock, log, transport = pipeline(directory)
        env = _env(directory)
        request_stop(directory)
        stdout = io.BytesIO()
        run_stdio(env, io.BytesIO(_frames(_signal(True))), stdout, made)
        self.assertEqual(transport.calls, [])
        self.assertIn("STOPPED", _codes(stdout.getvalue()))
        self.assertTrue(clear_stop(directory))

        padded = json.dumps({"preview": MARKER}).encode("utf-8").ljust(2048, b" ")
        stdin = io.BytesIO(len(padded).to_bytes(4, "little") + padded)
        stdout = io.BytesIO()
        run_stdio(env, stdin, stdout, made)
        self.assertEqual(transport.calls, [])
        self.assertIn("OVERSIZE", _codes(stdout.getvalue()))
        self.assertNotIn(MARKER, _tree(directory) + log.text() + stdout.getvalue().decode("utf-8"))

    def test_subprocess_reaches_a_local_mock_once(self):
        directory = Path("/tmp/wake-bridge-proc")
        _clear(directory)
        bind_local(directory, "contact-a", "Me")
        hits = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or "0")
                hits.append(self.rfile.read(length))
                body = b'{"accepted":true,"unique":true,"duplicate":false}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        port = server.server_address[1]
        env = _env(directory)
        env["WHATSAPP_WAKE_URL"] = f"http://127.0.0.1:{port}/"
        proc = subprocess.Popen(
            [sys.executable, "-m", "wake", "bridge"],
            cwd=REPO,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.addCleanup(proc.kill)
        assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
        scope = read_frame(proc.stdout)["value"]
        self.assertEqual(scope["label"], "contact-a")
        write_frame(proc.stdin, {"v": 1, "kind": "hello"})
        self.assertEqual(read_frame(proc.stdout)["value"]["kind"], "scope")
        self.assertEqual(read_frame(proc.stdout)["value"]["disposition"], "READY")
        write_frame(proc.stdin, _signal(False))
        self.assertEqual(read_frame(proc.stdout)["value"]["disposition"], "BASELINE")
        write_frame(proc.stdin, _signal(True))
        posted = read_frame(proc.stdout)["value"]
        self.assertEqual(posted["disposition"], "ONE_UNREAD")
        self.assertTrue(posted["posted"])
        write_frame(proc.stdin, _signal(True))
        self.assertEqual(read_frame(proc.stdout)["value"]["disposition"], "NO_NEW")
        proc.stdin.close()
        proc.wait(timeout=5)
        stderr = proc.stderr.read().decode("utf-8", "replace")
        proc.stdout.close()
        proc.stderr.close()
        self.assertEqual(len(hits), 1)
        self.assertNotIn(MARKER, hits[0].decode("utf-8") + _tree(directory) + stderr)
        self.assertNotIn("seed-local", hits[0].decode("utf-8"))
        self.assertIn(b"web-page-change", hits[0])

    def test_installer_allows_one_extension_and_stores_no_secret(self):
        home = _private_dir()
        self.addCleanup(lambda: _remove(home))
        completed = subprocess.run(
            ["sh", str(REPO / "scripts/install-wake-bridge.sh"), "--home", str(home), "--repo", str(REPO)],
            cwd=REPO,
            env={"PATH": os.environ.get("PATH", ""), "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        manifest = json.loads((home / ".config/chromium/NativeMessagingHosts/com.draft_bridge.wake.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["allowed_origins"], ["chrome-extension://djilkjcfdolfdmeeildoamafheooaalj/"])
        self.assertEqual(manifest["name"], "com.draft_bridge.wake")
        wrapper = Path(manifest["path"]).read_text(encoding="utf-8")
        blob = wrapper + json.dumps(manifest) + completed.stdout + completed.stderr
        self.assertNotIn("http", blob)
        self.assertNotIn("Authorization:", blob)
        self.assertNotIn("WHATSAPP_WAKE_AUTHORIZATION=", blob)
        self.assertNotIn("Bearer", blob)
        self.assertNotIn('. "$envfile"', wrapper)
        self.assertNotIn("set -a", wrapper)
        self.assertIn("WHATSAPP_WAKE_WIRE", wrapper)
        rejected = subprocess.run(
            ["sh", str(REPO / "scripts/install-wake-bridge.sh"), "--home", str(home), "--extension-id", "not-an-id"],
            cwd=REPO,
            env={"PATH": os.environ.get("PATH", ""), "HOME": str(home)},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertFalse(str(home).startswith("/tmp"))
        self.assertFalse(str(home).startswith("/var/tmp"))

    def test_installer_rejects_a_home_under_tmp(self):
        home = Path("/tmp") / "wake-bridge-reject-home"
        _clear(home)
        self.addCleanup(lambda: _remove(home))
        os.chmod(home, 0o700)
        completed = subprocess.run(
            ["sh", str(REPO / "scripts/install-wake-bridge.sh"), "--home", str(home), "--repo", str(REPO)],
            cwd=REPO,
            env={"PATH": os.environ.get("PATH", ""), "HOME": str(home)},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2, completed.stdout)
        self.assertIn("world-writable", completed.stderr)
        self.assertFalse((home / ".local/share/draft-bridge/wake-bridge-host").exists())

    def test_pasted_header_line_does_not_kill_the_host(self):
        home = _private_dir()
        self.addCleanup(lambda: _remove(home))
        store = home / "store"
        store.mkdir()
        canary = home / "shell-canary"
        completed = subprocess.run(
            ["sh", str(REPO / "scripts/install-wake-bridge.sh"), "--home", str(home), "--repo", str(REPO)],
            cwd=REPO,
            env={"PATH": os.environ.get("PATH", ""), "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        secret = "Authorization: local-test $(touch " + str(canary) + ") $UNSET_WAKE_TOKEN"
        env_file = home / ".config" / "draft-bridge" / "wake.env"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text(
            "\n".join(
                [
                    "WHATSAPP_WAKE_ENABLED=1",
                    "WHATSAPP_WAKE_URL=http://127.0.0.1:9/",
                    "WHATSAPP_WAKE_AUTHORIZATION=" + secret,
                    "WHATSAPP_WAKE_ALLOWLIST_LABEL=contact-a",
                    "WHATSAPP_WAKE_STORE=" + str(store),
                    "",
                ]
            ),
            encoding="utf-8",
        )
        wrapper = Path(json.loads((home / ".config/chromium/NativeMessagingHosts/com.draft_bridge.wake.json").read_text(encoding="utf-8"))["path"])
        unknown = _signal(False)
        unknown["unread"] = None
        unknown["position"] = 1
        proc = subprocess.run(
            [str(wrapper)],
            input=_frames({"v": 1, "kind": "hello"}, {"v": 1, "kind": "scope-offer", "label": "contact-a"}, unknown),
            capture_output=True,
            timeout=10,
            env={"PATH": os.environ.get("PATH", ""), "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")},
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        self.assertFalse(canary.exists())
        codes = _codes(proc.stdout)
        self.assertIn("READY", codes)
        self.assertIn("SCOPE", codes)
        self.assertIn("UNREAD_UNKNOWN", codes)
        self.assertNotIn("ONE_UNREAD", codes)
        handshake = read_handshake(store)
        self.assertEqual(handshake["hello"], "READY")
        self.assertEqual(handshake["scope"], "SCOPE")
        self.assertEqual(handshake["list"], "UNREAD_UNKNOWN")
        self.assertFalse(handshake["posted"])
        host = read_host(store)
        self.assertEqual(host["phase"], "exited")
        self.assertEqual(host["cause"], "none")
        binding = json.loads((store / "binding.json").read_text(encoding="utf-8"))
        self.assertEqual(binding["mode"], "metadata")
        self.assertEqual(binding["selfLabel"], "")
        self.assertEqual(binding["visibleHeader"], "contact-a")
        blob = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace") + _tree(store)
        self.assertNotIn("local-test", blob)
        self.assertNotIn("UNSET_WAKE_TOKEN", blob)
        self.assertNotIn("shell-canary", blob)
        self.assertNotIn(secret, blob)

    def test_closed_stdin_and_relative_store_are_classified(self):
        directory = Path("/tmp/wake-bridge-exit-cause")
        _clear(directory)
        made, _clock, _log, transport = pipeline(directory)
        env = _env(directory)
        code = run_stdio(env, io.BytesIO(b""), io.BytesIO(), made)
        self.assertEqual(code, 0)
        self.assertEqual(read_handshake(directory)["hello"], "pending")
        self.assertEqual(read_handshake(directory)["scope"], "pending")
        self.assertEqual(read_handshake(directory)["list"], "none")
        self.assertFalse(read_handshake(directory)["posted"])
        host = read_host(directory)
        self.assertEqual(host["phase"], "exited")
        self.assertEqual(host["cause"], "HOST_EXITED")
        self.assertEqual(host["detail"], "closed-before-hello")
        from contextlib import redirect_stdout
        from wake.__main__ import status

        printed = io.StringIO()
        with redirect_stdout(printed):
            status(env)
        text = printed.getvalue()
        self.assertIn("hello: pending", text)
        self.assertIn("scope: pending", text)
        self.assertIn("list: none", text)
        self.assertIn("handshake-posted: no", text)
        self.assertIn("host-phase: exited", text)
        self.assertIn("host-cause: HOST_EXITED", text)
        self.assertIn("host-detail: closed-before-hello", text)
        self.assertNotIn(str(directory), text)
        import wake.bridge as bridge_module

        previous = bridge_module.DEFAULT_STORE
        bridge_module.DEFAULT_STORE = directory
        try:
            relative = _env(directory)
            relative["WHATSAPP_WAKE_STORE"] = "not-absolute"
            stdout = io.BytesIO()
            code = run_stdio(relative, io.BytesIO(_frames({"v": 1, "kind": "hello"}, {"v": 1, "kind": "scope-offer", "label": "contact-a"})), stdout, made)
        finally:
            bridge_module.DEFAULT_STORE = previous
        self.assertEqual(code, 0)
        self.assertIn("READY", _codes(stdout.getvalue()))
        self.assertIn("SCOPE", _codes(stdout.getvalue()))
        self.assertEqual(read_host(directory)["cause"], "STORE_IGNORED")
        self.assertNotIn("not-absolute", _tree(directory))
        self.assertEqual(transport.calls, [])

    def test_metadata_handshake_posts_nothing(self):
        directory = Path("/tmp/wake-bridge-metadata")
        _clear(directory)
        made, _clock, log, transport = pipeline(directory)
        env = _env(directory)
        secret = "secret-metadata-body"
        poison = {"v": 1, "kind": "scope-offer", "label": "contact-a", "preview": secret}
        hello = {"v": 1, "kind": "hello"}
        offer = {"v": 1, "kind": "scope-offer", "label": "contact-a"}
        other = {"v": 1, "kind": "scope-offer", "label": "Sam"}
        unknown = _signal(False)
        unknown["unread"] = None
        unknown["position"] = 1
        stdout = io.BytesIO()
        code = run_stdio(env, io.BytesIO(_frames(poison, hello, offer, unknown, other)), stdout, made)
        self.assertEqual(code, 0)
        self.assertEqual(transport.calls, [])
        codes = _codes(stdout.getvalue())
        self.assertEqual(codes[0], "UNTRUSTED_FIELD")
        self.assertIn("READY", codes)
        self.assertIn("SCOPE", codes)
        self.assertIn("UNREAD_UNKNOWN", codes)
        self.assertIn("SCOPE_MISMATCH", codes)
        self.assertNotIn("ONE_UNREAD", codes)
        first = read_handshake(directory)
        self.assertEqual(first["hello"], "READY")
        self.assertEqual(first["scope"], "SCOPE_MISMATCH")
        self.assertEqual(first["list"], "UNREAD_UNKNOWN")
        self.assertFalse(first["posted"])
        binding = json.loads((directory / "binding.json").read_text(encoding="utf-8"))
        self.assertEqual(binding["visibleHeader"], "contact-a")
        self.assertEqual(binding["selfLabel"], "")
        self.assertEqual(binding["mode"], "metadata")
        self.assertFalse((directory / "list-window.json").exists())
        snapshot = {
            "layout": "probe-contract",
            "header": "contact-a",
            "phase": "ready",
            "slots": [{"kind": "message", "sender": "contact-a", "text": secret, "timeText": "09:01"}],
        }
        result = apply_page(directory, snapshot, allowlist="contact-a", pipeline=made)
        self.assertEqual(result["disposition"], "DIRECTION_UNPROVEN")
        self.assertFalse(result["posted"])
        self.assertEqual(transport.calls, [])
        blob = _tree(directory) + log.text() + stdout.getvalue().decode("utf-8")
        self.assertNotIn(secret, blob)
        self.assertNotIn("A+B Academy", blob)
        self.assertNotIn("local-test-only", blob)
        request_stop(directory)
        stopped = io.BytesIO()
        run_stdio(env, io.BytesIO(_frames(unknown)), stopped, made)
        self.assertIn("STOPPED", _codes(stopped.getvalue()))
        self.assertEqual(transport.calls, [])
        self.assertTrue(clear_stop(directory))
        again = io.BytesIO()
        run_stdio(env, io.BytesIO(_frames(hello, unknown)), again, made)
        self.assertEqual(transport.calls, [])
        self.assertIn("READY", _codes(again.getvalue()))
        self.assertIn("UNREAD_UNKNOWN", _codes(again.getvalue()))
        self.assertFalse((directory / "list-window.json").exists())
        empty, reason = bind_local(directory, "contact-a", "")
        self.assertIsNone(empty)
        self.assertEqual(reason, "SELF_LABEL_UNUSABLE")
        profile, profile_reason = bind_metadata(directory, "A+B Academy")
        self.assertIsNone(profile)
        self.assertEqual(profile_reason, "HEADER_UNUSABLE")
        kept = json.loads((directory / "binding.json").read_text(encoding="utf-8"))
        self.assertEqual(kept["mode"], "metadata")
        self.assertEqual(kept["selfLabel"], "")
        handshake = read_handshake(directory)
        self.assertEqual(handshake["hello"], "READY")
        self.assertEqual(handshake["scope"], "pending")
        self.assertIn("SCOPE", codes)
        self.assertEqual(handshake["list"], "UNREAD_UNKNOWN")
        self.assertFalse(handshake["posted"])
        raw = (directory / "handshake.json").read_text(encoding="utf-8")
        self.assertNotIn(secret, raw)
        self.assertNotIn("contact-a", raw)
        self.assertNotIn("http", raw)

    def test_unknown_unread_frame_does_not_post(self):
        directory = Path("/tmp/wake-bridge-unknown")
        _clear(directory)
        made, _clock, log, transport = pipeline(directory)
        env = _env(directory)
        bind_local(directory, "contact-a", "Me")
        signal = _signal(False)
        signal["unread"] = None
        signal["position"] = 1
        stdout = io.BytesIO()
        code = run_stdio(env, io.BytesIO(_frames({"v": 1, "kind": "hello"}, signal)), stdout, made)
        self.assertEqual(code, 0)
        self.assertEqual(transport.calls, [])
        self.assertIn("UNREAD_UNKNOWN", _codes(stdout.getvalue()))
        self.assertFalse((directory / "list-window.json").exists())
        blob = _tree(directory) + log.text() + stdout.getvalue().decode("utf-8")
        self.assertNotIn(MARKER, blob)
        self.assertNotIn(OTHER, blob)

    def test_numbered_count_survives_the_host_frame(self):
        directory = Path("/tmp/wake-bridge-count-frame")
        _clear(directory)
        made, _clock, _log, transport = pipeline(
            directory,
            transport=Scripted([(200, b'{"accepted":true,"unique":true,"duplicate":false}')] * 3),
        )
        env = _env(directory)
        from wake.read import bind_metadata

        bind_metadata(directory, "contact-a")
        absent = _signal(False)
        absent["mark"] = "absent"
        absent["unread"] = False
        absent["count"] = 0
        absent["position"] = 1
        one = dict(absent)
        one["mark"] = "count"
        one["unread"] = None
        one["count"] = 1
        one["otherChanges"] = 2
        repeat = dict(one)
        dot = dict(absent)
        dot["mark"] = "dot"
        dot["unread"] = None
        dot.pop("count")
        stdout = io.BytesIO()
        code = run_stdio(
            env, io.BytesIO(_frames({"v": 1, "kind": "hello"}, absent, one, repeat, dot)), stdout, made
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(transport.calls), 1)
        first = json.loads(transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual(first["source"], "unread-indicator-hint")
        self.assertEqual(first["field"], "whatsapp-wake-test-v1")
        self.assertIs(first["testOnly"], True)
        self.assertEqual(first["conversationScope"], "contact-a")
        self.assertNotIn("count", first)
        codes = _codes(stdout.getvalue())
        self.assertIn("COUNT_BASELINE", codes)
        self.assertIn("COUNT_UP", codes)
        self.assertIn("NO_NEW", codes)
        self.assertIn("UNREAD_DOT", codes)
        self.assertNotIn("ONE_UNREAD", codes)
        from wake.bridge import read_handshake

        handshake = read_handshake(directory)
        self.assertEqual(handshake["list"], "UNREAD_DOT")
        self.assertFalse(handshake["posted"])
        self.assertEqual(handshake["forward"], "none")
        self.assertEqual(handshake["lastEvent"], first["eventId"])
        self.assertEqual(handshake["lastForward"], "accepted")
        self.assertEqual(handshake["stored"], 1)
        self.assertIn("COUNT_UP", handshake["listRecent"])
        self.assertNotIn("個未讀訊息", stdout.getvalue().decode("utf-8", "replace") + _tree(directory))
        self.assertNotIn("ONE_UNREAD", _tree(directory))

    def test_listening_file_with_a_dead_pid_is_stale(self):
        directory = Path("/tmp/wake-host-stale")
        _clear(directory)
        (directory / "host.json").write_text(
            json.dumps({"phase": "listening", "cause": "none", "detail": "none", "pid": 2147483647}),
            encoding="utf-8",
        )
        state = read_host(directory)
        self.assertEqual(state["phase"], "stale")
        self.assertEqual(state["cause"], "HOST_STALE")
        self.assertEqual(state["live"], "no")
        (directory / "host.json").write_text(
            json.dumps({"phase": "listening", "cause": "none", "detail": "none"}),
            encoding="utf-8",
        )
        missing = read_host(directory)
        self.assertEqual(missing["phase"], "listening")
        self.assertEqual(missing["live"], "unverified")


def _signal(unread: bool) -> dict:
    return {
        "v": 1,
        "kind": "list-signal",
        "layout": "chat-list-contract",
        "boundLabel": "contact-a",
        "matches": 1,
        "position": 0 if unread else 2,
        "unread": unread,
        "otherChanges": 0,
    }


def _frames(*messages) -> bytes:
    chunks = []
    for message in messages:
        raw = json.dumps(message, separators=(",", ":")).encode("utf-8")
        chunks.append(len(raw).to_bytes(4, "little") + raw)
    return b"".join(chunks)


def _codes(raw: bytes) -> list:
    stream = io.BytesIO(raw)
    found = []
    while True:
        incoming = read_frame(stream)
        if incoming is None:
            return found
        value = incoming.get("value") or {}
        if "disposition" in value:
            found.append(value["disposition"])
        elif incoming.get("error"):
            found.append(incoming["error"])


def _env(directory: Path, enabled: str = "1") -> dict:
    return {
        "PATH": os.environ.get("PATH", ""),
        "WHATSAPP_WAKE_CONFIG": "",
        "WHATSAPP_WAKE_ENABLED": enabled,
        "WHATSAPP_WAKE_URL": "http://127.0.0.1:9/",
        "WHATSAPP_WAKE_AUTHORIZATION": "local-test-only",
        "WHATSAPP_WAKE_ALLOWLIST_LABEL": "contact-a",
        "WHATSAPP_WAKE_STORE": str(directory),
    }


def _tree(directory: Path) -> str:
    parts = []
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _remove(directory: Path) -> None:
    shutil.rmtree(directory, ignore_errors=True)


def _private_dir() -> Path:
    candidates = []
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        candidates.append(Path(runtime))
    candidates.append(Path(f"/run/user/{os.getuid()}"))
    candidates.append(Path.home())
    candidates.append(REPO)
    seen = set()
    for parent in candidates:
        try:
            resolved = parent.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if not _install_root_ok(resolved):
            continue
        try:
            return Path(tempfile.mkdtemp(prefix="wake-bridge-install-", dir=resolved))
        except OSError:
            continue
    raise AssertionError("no private directory outside /tmp for the native-host install test")


def _install_root_ok(path: Path) -> bool:
    if not path.is_dir() or not os.access(path, os.W_OK):
        return False
    current = path
    while True:
        if str(current) in {"/tmp", "/var/tmp", "/dev/shm"}:
            return False
        try:
            mode = current.stat().st_mode
        except OSError:
            return False
        if mode & stat.S_IWOTH:
            return False
        if current.parent == current:
            return True
        current = current.parent


def _clear(directory: Path) -> None:
    if directory.exists():
        for child in sorted(directory.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
    directory.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    unittest.main()
