#!/bin/sh
# Install or remove the least-privilege native messaging host.
# This file does not contain a webhook URL, an extension id, or an Authorization value.
# It does not read or print the wake env file.
set -eu
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
export PYTHONPATH="$repo${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m wake host-install --repo "$repo" "$@"
