#!/bin/sh
# Build the standalone wake test package. The guardrail reads the extension
# manifests, so those two files are included. No credentials are included.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
stage=$(mktemp -d)
dest=${1:-./wake-isolated-tests.zip}
mkdir -p "$stage/wake" "$stage/tests" "$stage/scripts" "$stage/config" "$stage/docs" "$stage/web" "$stage/whatsapp-wake-test"
cp -a "$root/wake/." "$stage/wake/"
cp -a "$root/tests/wake" "$stage/tests/wake"
cp -a "$root/scripts/wake-setup.sh" "$root/scripts/wake-live.sh" "$root/scripts/wake-test.sh" "$root/scripts/install-wake-bridge.sh" "$stage/scripts/"
cp -a "$root/config/wake.env.example" "$stage/config/"
cp -a "$root/docs/WAKE.md" "$root/docs/INTEGRATION.md" "$stage/docs/"
cp -a "$root/web/manifest.json" "$root/web/manifest.test.json" "$stage/web/"
cp -a "$root/whatsapp-wake-test/README.md" "$stage/whatsapp-wake-test/"
find "$stage" -type d -name __pycache__ -exec rm -rf {} +
find "$stage" -name '*.pyc' -delete
cat > "$stage/RUN.txt" <<'EOF'
Isolated wake tests. No live WhatsApp page, no webhook, and no secrets.

  python3 -m unittest discover -s tests/wake -v

Run from this directory. Transmission stays off unless
WHATSAPP_WAKE_ENABLED=1 and a URL and Authorization are supplied from
outside the archive. python3 -m wake probe is a connectivity check only.
python3 -m wake bridge is the continuous page-change receiver.
Chrome starts it through the native host. It is not a live WhatsApp wake.
The archive does not contain a chat or a credential.
web/manifest.json is here because the guardrail checks the extension
permissions. It is not an installed extension.
EOF
rm -f "$dest"
(
  cd "$stage"
  zip -qr "$dest" .
)
rm -rf "$stage"
echo "$dest"
