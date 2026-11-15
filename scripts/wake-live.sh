#!/bin/sh
# Connectivity probe for a machine where the user has already configured
# the routine URL and Authorization outside this repository.
# With no configuration, this exits 2 and does not send.
set -eu
cd "$(dirname "$0")/.."
exec python3 -m wake probe
