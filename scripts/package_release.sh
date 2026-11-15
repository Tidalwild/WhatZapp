#!/bin/sh
# Source archive of the tracked tree. No dist, no env file, no browser state.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
version=$(git -C "$root" rev-parse --short=12 HEAD)
out=${1:-"$root/release"}
mkdir -p "$out"
archive="$out/whatzapp-$version.tar.gz"
git -C "$root" archive --format=tar.gz --prefix="whatzapp-$version/" HEAD > "$archive"
python3 "$root/scripts/privacy_scan.py"
checksum=$(sha256sum "$archive" | awk '{print $1}')
printf '%s  %s\n' "$checksum" "$(basename "$archive")" > "$archive.sha256"
echo "archive $archive"
echo "sha256 $checksum"
