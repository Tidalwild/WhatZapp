#!/bin/sh
# Print the setup path. This script does not read or print credentials.
set -eu
cat <<'EOF'
Wake setup

The routine URL and Authorization stay outside this repository. These
commands do not print them and do not send WhatsApp messages. A
manual-connectivity-probe only checks that the saved routine accepts one
metadata envelope. It does not read a chat.

1. Confirm the parent environment without printing secrets:
   python3 -m wake status
   auth is "value" or "normalized". sends-whatsapp stays no.
   chat-read stays no. A full "Authorization:" line in the credential is
   reduced to its value before a request.
2. Set the switch and one local label. The label is not a verified recipient
   and it is not a FreeDesktop app name:
   export WHATSAPP_WAKE_ENABLED=1
   export WHATSAPP_WAKE_ALLOWLIST_LABEL=contact-a
3. Connectivity, only when you want another probe event:
   python3 -m wake probe
   source is manual-connectivity-probe. It does not authorize a chat read.
4. Finite scoped observer, on a machine whose status shows a session bus:
   python3 -m wake observe --once --seconds 180
   It asks for Notify summaries equal to the allowlist token. It does not
   filter on app name. If the browser never emits Notify, it sees nothing.
   The process exits after one settled match, after 180 seconds, or when
   another shell runs:
   python3 -m wake stop
   Resume capture with python3 -m wake resume. Transmission still requires
   the enabled switch. Exit records a reconnect gap and does not backfill.
5. Retry deliveries already stored, without creating a wake:
   python3 -m wake flush --seconds 45
6. Android metadata, without installing the phone app and without a body:
   python3 -m wake ingest --package com.whatsapp \
     --notification-key '<listener key>' --title '<exact allowlist token>'
   com.whatsapp.w4b is the other accepted package. The phone app still talks
   only to a loopback mock. This command does not change that.
7. Continuous page-change wake. Quit Chrome, install the host, then start Chrome.
   scripts/install-wake-bridge.sh
   python3 -m wake bind --header 'contact-a' --self '<exact self label>'
   The extension sends only the bound row's list signal. The host posts
   only when unread goes from absent to present, matches is 1, and
   otherChanges is 0. Preview text and other chats are not accepted.
   A locale clock such as 凌晨3:16 (a Traditional Chinese time of day) does not prove an inbound row.
   The live list reader fail-closes until the contact-a row's accessible
   structure is known. The fixture marker is not WhatsApp markup.
8. One bound chat, after a real wake has been acknowledged.
   The first snapshot is a baseline and does not draft:
   python3 -m wake bind --header '<visible open-chat label>' --self '<own label>'
   python3 -m wake read --snapshot baseline.json
   python3 -m wake read --snapshot next.json
   next.json must be the probe-contract snapshot of that same open chat.
   Exactly one unambiguous new inbound row is recorded. On the default
   official transport that record is a transport acknowledgement, not a
   mock reply. Duplicate clocks, weekday clocks, and a connectivity probe
   do not record one. The extension is not installed by these commands.
   A page mutation is not a notification.

Sending to WhatsApp stays off. This package does not include a bot.
local-mock-handler is only python3 -m wake routine and the export switch.
EOF
