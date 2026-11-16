#!/usr/bin/env python3
"""Build a draft-only candidate archive and its checksum.

The archive is the tracked tree. It is not a published release and it does
not prove a WhatsApp session. Sending stays off.
"""

import hashlib
import importlib.util
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_scan():
    path = ROOT / "scripts" / "privacy_scan.py"
    spec = importlib.util.spec_from_file_location("privacy_scan", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("privacy scan missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scan_archive(archive: Path, scan) -> list[str]:
    failures = []
    with tarfile.open(archive, "r") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            raw = extracted.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeError:
                failures.append(f"binary-or-non-utf8\t{member.name}")
                continue
            sample = text.replace("Andy Yeung", "")
            for name, pattern in scan.RULES:
                if pattern.search(sample):
                    failures.append(f"{name}\t{member.name}")
                    break
            else:
                for match in scan.URL.finditer(text):
                    if match.group(0).rstrip("/") == "https:":
                        continue
                    if not scan.allowed_url(match.group(0)):
                        failures.append(f"unexpected-url\t{member.name}")
                        break
    return failures


def package(dest: Path) -> tuple[int, str]:
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / "whatzapp-draft-candidate.tar"
    completed = subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return 1, "candidate: blocked\nreason: archive\n"
    scan = load_scan()
    failures = scan_archive(archive, scan)
    if failures:
        archive.unlink(missing_ok=True)
        return 1, "candidate: blocked\n" + "\n".join(failures) + "\n"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dest / "SHA256SUMS").write_text(f"{digest}  whatzapp-draft-candidate.tar\n", encoding="utf-8")
    lines = [
        "candidate: draft-only",
        "send-enabled: no",
        "live-whatsapp: not-run",
        "live-webhook: not-run",
        f"sha256: {digest}",
        f"archive: {archive}",
        f"checksums: {dest / 'SHA256SUMS'}",
    ]
    return 0, "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    dest = Path(argv[1]) if len(argv) > 1 else Path("/tmp/whatzapp-candidate")
    code, text = package(dest)
    sys.stdout.write(text)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
