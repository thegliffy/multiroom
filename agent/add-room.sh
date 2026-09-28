#!/usr/bin/env bash
# Pair a speaker and start its snapclient room without the web UI.
# Usage: sudo ./add-room.sh <room-slug> <snapcast-host> <hciX> <BT_MAC>
set -euo pipefail

ROOM="${1:-}"
HOST="${2:-}"
HCI="${3:-}"
MAC="${4:-}"

if [[ -z "$ROOM" || -z "$HOST" || -z "$HCI" || -z "$MAC" ]]; then
  echo "Usage: sudo $0 <room-slug> <snapcast-host> <hciX> <BT_MAC>"
  echo "Example: sudo $0 kitchen 10.0.0.10 hci0 AA:BB:CC:DD:EE:FF"
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root (sudo)."
  exit 1
fi

if [[ ! "$ROOM" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "Room slug must be letters, numbers, _ or -."
  exit 1
fi

MAC="$(echo "$MAC" | tr '[:lower:]' '[:upper:]')"
install -d /etc/multiroom/rooms
echo imported >/etc/multiroom/rooms/.legacy-imported

cat >/etc/multiroom/rooms/${ROOM}.env <<EOF
SNAPCAST_HOST=${HOST}
ROOM_NAME=${ROOM}
BT_ADAPTER=${HCI}
BT_MAC=${MAC}
ALSA_DEVICE=bluealsa:DEV=${MAC},PROFILE=a2dp
EOF

/usr/local/bin/multiroom-bt-pair "$MAC" "$HCI" || true
systemctl enable --now "multiroom-room@${ROOM}.service"
echo "Started multiroom-room@${ROOM} -> ${MAC} on ${HCI}"
