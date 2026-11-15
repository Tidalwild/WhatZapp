#!/bin/sh
# Install the least-privilege native messaging host for one extension id.
# This file does not contain a webhook URL or an Authorization value.
# It does not read or print the wake env file.
set -eu

extension_id=djilkjcfdolfdmeeildoamafheooaalj
home=${HOME:-}
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)

while [ $# -gt 0 ]; do
  case "$1" in
    --extension-id)
      extension_id=${2:-}
      shift 2
      ;;
    --home)
      home=${2:-}
      shift 2
      ;;
    --repo)
      repo=${2:-}
      shift 2
      ;;
    *)
      echo "usage: install-wake-bridge.sh [--extension-id ID] [--home DIR] [--repo DIR]" >&2
      exit 2
      ;;
  esac
done

if ! printf '%s' "$extension_id" | grep -Eq '^[a-p]{32}$'; then
  echo "blocked: extension id must be 32 characters from a-p. Nothing was installed." >&2
  exit 2
fi
if [ -z "$home" ] || [ ! -d "$home" ]; then
  echo "blocked: home directory is missing. Nothing was installed." >&2
  exit 2
fi
if [ ! -d "$repo/wake" ]; then
  echo "blocked: wake package was not found. Nothing was installed." >&2
  exit 2
fi
case "$home" in
  /tmp|/tmp/*|/var/tmp|/var/tmp/*)
    echo "blocked: Chrome ignores a native host under a world-writable directory. Choose a home outside /tmp." >&2
    exit 2
    ;;
esac

python=$(command -v python3)
config_home=${XDG_CONFIG_HOME:-"$home/.config"}
lib="$home/.local/share/draft-bridge"
host="$lib/wake-bridge-host"
mkdir -p "$lib"

cat > "$host" <<EOF
#!/bin/sh
# No webhook address and no credential are stored in this file.
# The env file is copied as literal assignments. It is not executed.
set -eu
export PYTHONPATH='$repo'\${PYTHONPATH:+:\$PYTHONPATH}
envfile="\${WHATSAPP_WAKE_CONFIG:-\${XDG_CONFIG_HOME:-\$HOME/.config}/draft-bridge/wake.env}"
if [ -f "\$envfile" ]; then
  while IFS= read -r line || [ -n "\$line" ]; do
    cr=\$(printf '\\r')
    line=\${line%\$cr}
    line=\${line#"\${line%%[![:space:]]*}"}
    line=\${line%"\${line##*[![:space:]]}"}
    case "\$line" in
      ''|\\#*) continue ;;
    esac
    key=\${line%%=*}
    value=\${line#*=}
    key=\${key#export }
    key=\${key#"\${key%%[![:space:]]*}"}
    key=\${key%"\${key##*[![:space:]]}"}
    case "\$key" in
      WHATSAPP_WAKE_ENABLED|WHATSAPP_WAKE_URL|WHATSAPP_WAKE_AUTHORIZATION|WHATSAPP_WAKE_ALLOWLIST_LABEL|WHATSAPP_WAKE_ROUTINE_AUTHORIZATION|WHATSAPP_WAKE_STORE|WHATSAPP_WAKE_BRIDGE_TRACE|WHATSAPP_WAKE_WIRE|WHATSAPP_WAKE_TRANSPORT)
        ;;
      *) continue ;;
    esac
    value=\${value#"\${value%%[![:space:]]*}"}
    value=\${value%"\${value##*[![:space:]]}"}
    case "\$value" in
      \\"*\\") value=\${value#\\"}; value=\${value%\\"} ;;
      \\'*\\') value=\${value#\\'}; value=\${value%\\'} ;;
    esac
    export "\$key=\$value"
  done < "\$envfile"
fi
exec '$python' -u -m wake bridge
EOF
chmod 755 "$host"

manifest=$(cat <<EOF
{
  "name": "com.draft_bridge.wake",
  "description": "Local page-change wake receiver for one extension. It does not send WhatsApp messages.",
  "path": "$host",
  "type": "stdio",
  "allowed_origins": [
    "chrome-extension://$extension_id/"
  ]
}
EOF
)

for product in google-chrome google-chrome-for-testing chromium; do
  dir="$config_home/$product/NativeMessagingHosts"
  mkdir -p "$dir"
  printf '%s\n' "$manifest" > "$dir/com.draft_bridge.wake.json"
  chmod 644 "$dir/com.draft_bridge.wake.json"
  echo "installed: $dir/com.draft_bridge.wake.json"
done
echo "host: $host"
echo "allowed-origin: chrome-extension://$extension_id/"
echo "sends-whatsapp: no"
