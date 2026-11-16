import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import unittest

from tests.wake.test_bridge import FIXTURE_EXTENSION, REPO, _private_dir, _remove

SECRET = "local-test-only-auth-install-884"
OTHER_EXTENSION = "b" * 32


class HostInstallTests(unittest.TestCase):
    def test_repeat_upgrade_uninstall_and_independent_copy(self):
        home = _private_dir()
        self.addCleanup(lambda: _remove(home))
        stage = _private_dir()
        self.addCleanup(lambda: _remove(stage))
        _stage_source(stage)
        env = _env(home)
        secret_file = home / ".config" / "draft-bridge" / "wake.env"
        secret_file.parent.mkdir(parents=True)
        secret_file.write_text(f"WHATSAPP_WAKE_AUTHORIZATION={SECRET}\n", encoding="utf-8")
        notes = home / ".local" / "share" / "draft-bridge" / "notes.txt"
        notes.parent.mkdir(parents=True)
        notes.write_text("keep-notes", encoding="utf-8")
        first = _script(home, stage, env, "--extension-id", FIXTURE_EXTENSION)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertNotIn(SECRET, first.stdout + first.stderr)
        self.assertIn("browser-loaded: no\n", first.stdout)
        self.assertIn("template-installed: no\n", first.stdout)
        checked = _check(home, env)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("install-proven: files\n", checked.stdout)
        self.assertIn("install-evidence: installed-copy\n", checked.stdout)
        self.assertIn("host: 0.1.0\n", checked.stdout)
        self.assertIn("extension: 0.2.14\n", checked.stdout)
        self.assertIn("pair: match\n", checked.stdout)
        self.assertIn("credential-file: present\n", checked.stdout)
        self.assertIn("browser-loaded: no\n", checked.stdout)
        self.assertIn("whatsapp-session: not-run\n", checked.stdout)
        self.assertNotIn(str(home), checked.stdout + checked.stderr)
        self.assertNotIn(SECRET, checked.stdout + checked.stderr)
        self.assertNotIn(str(stage), _wrapper_text(home))
        tree = _module("setup-check", env)
        self.assertEqual(tree.returncode, 0, tree.stdout)
        self.assertIn("install-evidence: tree-only\n", tree.stdout)
        self.assertIn("install-proven: no\n", tree.stdout)
        again = _script(home, stage, env, "--extension-id", OTHER_EXTENSION)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(secret_file.read_text(encoding="utf-8"), f"WHATSAPP_WAKE_AUTHORIZATION={SECRET}\n")
        self.assertEqual(notes.read_text(encoding="utf-8"), "keep-notes")
        manifest = json.loads(_manifest(home).read_text(encoding="utf-8"))
        self.assertEqual(manifest["allowed_origins"], [f"chrome-extension://{OTHER_EXTENSION}/"])
        _rewrite(stage / "wake" / "__init__.py", '__version__ = "0.1.0"', '__version__ = "0.1.1"')
        _rewrite_manifest(stage / "web" / "manifest.json", "9.9.9")
        upgraded = _script(home, stage, env, "--extension-id", OTHER_EXTENSION)
        self.assertEqual(upgraded.returncode, 0, upgraded.stderr)
        checked = _check(home, env)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("host: 0.1.1\n", checked.stdout)
        self.assertIn("extension: 9.9.9\n", checked.stdout)
        shutil.rmtree(stage)
        self.assertFalse(stage.exists())
        syntax = subprocess.run(["sh", "-n", str(_wrapper(home))], capture_output=True, text=True, check=False)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        store = home / "store"
        hello = subprocess.run(
            [str(_wrapper(home))],
            input=_frame({"v": 1, "kind": "hello"}),
            capture_output=True,
            timeout=15,
            env={**env, "WHATSAPP_WAKE_STORE": str(store)},
            check=False,
        )
        self.assertEqual(hello.returncode, 0, hello.stderr.decode("utf-8", "replace"))
        self.assertIn(b"READY", hello.stdout)
        self.assertNotIn(SECRET.encode(), hello.stdout + hello.stderr)
        nested = home / ".local" / "share" / "draft-bridge" / "runtime" / "wake" / "notes.py"
        nested.write_text("keep-nested\n", encoding="utf-8")
        removed = _script(home, REPO, env, "--uninstall")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertIn("uninstall: done\n", removed.stdout)
        self.assertIn("credential-file: kept\n", removed.stdout)
        self.assertIn("store: kept\n", removed.stdout)
        self.assertNotIn(SECRET, removed.stdout + removed.stderr)
        self.assertNotIn(str(home), removed.stdout)
        self.assertFalse(_wrapper(home).exists())
        self.assertFalse(_manifest(home).exists())
        self.assertEqual(secret_file.read_text(encoding="utf-8"), f"WHATSAPP_WAKE_AUTHORIZATION={SECRET}\n")
        self.assertEqual(notes.read_text(encoding="utf-8"), "keep-notes")
        self.assertEqual(nested.read_text(encoding="utf-8"), "keep-nested\n")
        self.assertTrue(store.exists())
        second = _script(home, REPO, env, "--uninstall")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("uninstall: absent\n", second.stdout)
        self.assertEqual(notes.read_text(encoding="utf-8"), "keep-notes")

    def test_rejects_missing_id_symlink_and_config_escape(self):
        home = _private_dir()
        self.addCleanup(lambda: _remove(home))
        quoted = home / "wake'id"
        quoted.mkdir(mode=0o700)
        env = _env(quoted)
        missing = _script(quoted, REPO, env)
        self.assertEqual(missing.returncode, 2, missing.stdout)
        self.assertIn("extension id", missing.stderr)
        self.assertFalse(_wrapper(quoted).exists())
        installed = _script(quoted, REPO, env, "--extension-id", FIXTURE_EXTENSION)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        syntax = subprocess.run(["sh", "-n", str(_wrapper(quoted))], capture_output=True, text=True, check=False)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        outside = quoted / "kept.json"
        outside.write_text("keep-target", encoding="utf-8")
        manifest = _manifest(quoted)
        manifest.unlink()
        manifest.symlink_to(outside)
        refused = _script(quoted, REPO, env, "--extension-id", FIXTURE_EXTENSION)
        self.assertEqual(refused.returncode, 2, refused.stdout)
        self.assertIn("symlink", refused.stderr)
        self.assertEqual(outside.read_text(encoding="utf-8"), "keep-target")
        self.assertTrue(manifest.is_symlink())
        escaped = home / "escaped-config"
        escaped.mkdir()
        fled = subprocess.run(
            ["sh", str(REPO / "scripts/install-wake-bridge.sh"), "--home", str(quoted), "--repo", str(REPO), "--extension-id", FIXTURE_EXTENSION],
            cwd=REPO,
            env={**env, "XDG_CONFIG_HOME": str(escaped)},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(fled.returncode, 2, fled.stdout)
        self.assertFalse((escaped / "chromium").exists())
        local = home / "linked-home"
        local.mkdir(mode=0o700)
        redirected = local / ".local"
        redirected.symlink_to(home / "outside-local")
        (home / "outside-local").mkdir()
        linked = _script(local, REPO, _env(local), "--extension-id", FIXTURE_EXTENSION)
        self.assertEqual(linked.returncode, 2, linked.stdout)
        self.assertEqual(list((home / "outside-local").iterdir()), [])

    def test_check_sees_stamp_drift_and_dist_without_a_browser(self):
        home = _private_dir()
        self.addCleanup(lambda: _remove(home))
        env = _env(home)
        absent = _check(home, env)
        self.assertEqual(absent.returncode, 1)
        self.assertIn("install-proven: absent\n", absent.stdout)
        self.assertNotIn(str(home), absent.stdout)
        installed = _script(home, REPO, env, "--extension-id", FIXTURE_EXTENSION)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        init = home / ".local" / "share" / "draft-bridge" / "runtime" / "wake" / "__init__.py"
        _rewrite(init, '__version__ = "0.1.0"', '__version__ = "0.1.9"')
        drifted = _check(home, env)
        self.assertEqual(drifted.returncode, 1)
        self.assertIn("pair: mismatch\n", drifted.stdout)
        self.assertIn("browser-loaded: no\n", drifted.stdout)
        self.assertNotIn("browser: ready", drifted.stdout)
        _rewrite(init, '__version__ = "0.1.9"', '__version__ = "0.1.0"')
        dist = home / "dist"
        dist.mkdir()
        (dist / "manifest.json").write_text(json.dumps({"version": "0.2.14"}) + "\n", encoding="utf-8")
        matched = _check(home, env, "--dist", str(dist))
        self.assertEqual(matched.returncode, 0, matched.stdout + matched.stderr)
        self.assertIn("extension-dist: match\n", matched.stdout)
        (dist / "manifest.json").write_text(json.dumps({"version": "0.0.1"}) + "\n", encoding="utf-8")
        unmatched = _check(home, env, "--dist", str(dist))
        self.assertEqual(unmatched.returncode, 1)
        self.assertIn("extension-dist: mismatch\n", unmatched.stdout)
        mode = _manifest(home).stat().st_mode
        self.assertFalse(mode & stat.S_IXUSR)


def _stage_source(stage: Path) -> None:
    wake = stage / "wake"
    wake.mkdir()
    for path in (REPO / "wake").glob("*.py"):
        if path.is_file() and not path.is_symlink():
            shutil.copy2(path, wake / path.name)
    web = stage / "web"
    web.mkdir()
    shutil.copy2(REPO / "web" / "manifest.json", web / "manifest.json")


def _env(home: Path) -> dict:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _script(home: Path, repo: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", str(REPO / "scripts/install-wake-bridge.sh"), "--home", str(home), "--repo", str(repo), *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _check(home: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return _module("install-check", env, "--home", str(home), *args)


def _module(command: str, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", "-m", "wake", command, *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _wrapper(home: Path) -> Path:
    return home / ".local" / "share" / "draft-bridge" / "wake-bridge-host"


def _wrapper_text(home: Path) -> str:
    return _wrapper(home).read_text(encoding="utf-8")


def _manifest(home: Path) -> Path:
    return home / ".config" / "chromium" / "NativeMessagingHosts" / "com.draft_bridge.wake.json"


def _frame(payload: dict) -> bytes:
    raw = json.dumps(payload).encode("utf-8")
    return len(raw).to_bytes(4, "little") + raw


def _rewrite(path: Path, old: str, new: str) -> None:
    path.write_text(path.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")


def _rewrite_manifest(path: Path, version: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
