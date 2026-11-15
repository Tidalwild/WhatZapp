import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PrivacyPackagingTests(unittest.TestCase):
    def test_tracked_tree_has_no_personal_or_credential_markers(self):
        result = subprocess.run(["python3", "scripts/privacy_scan.py"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("privacy-scan: ok", result.stdout)

    def test_release_script_is_a_git_archive(self):
        text = (ROOT / "scripts/package_release.sh").read_text(encoding="utf-8")
        self.assertIn("archive --format=tar.gz", text)
        self.assertNotIn("config/wake.env", text)
