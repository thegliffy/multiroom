#!/usr/bin/env bash
# Reconnect a known Bluetooth speaker.
# Usage: sudo multiroom-bt-connect AA:BB:CC:DD:EE:FF [hci0]
set -euo pipefail

MAC="${1:-}"
ADAPTER="${2:-hci0}"

if [[ -z "$MAC" ]]; then
  echo "Usage: $0 <BT_MAC> [adapter]"
  exit 1
fi

MAC="$(echo "$MAC" | tr '[:lower:]' '[:upper:]')"

bluetoothctl <<EOF
select ${ADAPTER}
power on
connect ${MAC}
EOF

echo "Connect requested for ${MAC} on ${ADAPTER}"
