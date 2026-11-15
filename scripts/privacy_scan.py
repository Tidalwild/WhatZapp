#!/usr/bin/env python3
"""Fail if tracked files contain personal or credential markers.

Prints file and rule name only. It does not print the matching text.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = (
    ("personal-name", re.compile("And" + "y|" + "Jar" + "vis", re.IGNORECASE)),
    ("home-path", re.compile("/ho" + "me/|/" + "Users/")),
    ("bearer", re.compile("Bear" + r"er\s+[A-Za-z0-9._\-]{8,}")),
    ("private-key", re.compile("sk_" + "live_|sk-" + "[A-Za-z0-9]{20,}")),
    ("calibration-marker", re.compile("JAR" + "VIS-" + "CALIBRATION")),
)
URL = re.compile("https:" + r"//[^\s)>\"`]+")
ALLOWED_HOSTS = (
    "github.com",
    "opensource.org",
    "web.whatsapp.com",
    "developer.chrome.com",
    "docs.github.com",
    "registry.npmjs.org",
    "opencollective.com",
    "tidelift.com",
    "example.com",
    "user.example",
    "routine.example",
    "fixture.invalid",
    "evil.invalid",
)


def tracked() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def allowed_url(value: str) -> bool:
    rest = value[len("https://"):].strip("`.,);]")
    host = rest.split("/")[0].split("@")[-1]
    if host == "":
        return True
    return host in ALLOWED_HOSTS or host.endswith(".example") or host.endswith(".invalid")


def main() -> int:
    failures = []
    for relative in tracked():
        path = ROOT / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            failures.append((relative, "binary-or-non-utf8"))
            continue
        for name, pattern in RULES:
            sample = text.replace("Andy Yeung", "") if name == "personal-name" else text
            if pattern.search(sample):
                failures.append((relative, name))
                break
        else:
            for match in URL.finditer(text):
                if match.group(0).rstrip("/") == "https:":
                    continue
                if not allowed_url(match.group(0)):
                    failures.append((relative, "unexpected-url"))
                    break
    if failures:
        for relative, rule in failures:
            print(f"{rule}\t{relative}")
        return 1
    print(f"privacy-scan: ok {len(tracked())} tracked files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
