#!/usr/bin/env bash
# Pair and trust a Bluetooth speaker (A2DP sink).
# Usage: sudo multiroom-bt-pair AA:BB:CC:DD:EE:FF [hci0]
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
agent on
default-agent
scan on
EOF

sleep 5

bluetoothctl <<EOF
select ${ADAPTER}
pair ${MAC}
trust ${MAC}
connect ${MAC}
scan off
EOF

echo "Paired/trusted/connected ${MAC} on ${ADAPTER}"
echo "Next: name the room in http://<pi-ip>:8190 or run add-room.sh"
