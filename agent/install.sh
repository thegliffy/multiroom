#!/usr/bin/env bash
# Install the pairing UI, BlueALSA, and one snapclient unit per room.
# No speaker is started until one is paired in the UI or via add-room.sh.
# Usage: sudo ./install.sh [snapcast-server-ip]
set -euo pipefail

SNAP_HOST="${1:-10.0.0.10}"
AGENT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root (sudo)."
  exit 1
fi

if id gliffy >/dev/null 2>&1; then
  RUN_USER=gliffy
elif id pi >/dev/null 2>&1; then
  RUN_USER=pi
else
  RUN_USER="$(logname 2>/dev/null || echo root)"
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  snapclient \
  bluez \
  bluez-tools \
  bluez-alsa-utils \
  python3 \
  python3-venv \
  python3-pip

install -d /etc/multiroom/rooms /opt/multiroom-agent /usr/local/bin

# Host hint only. Mark it imported so the UI does not turn it into an empty room.
if [[ ! -f /etc/multiroom/room.env ]]; then
  cat >/etc/multiroom/room.env <<EOF
SNAPCAST_HOST=${SNAP_HOST}
ROOM_NAME=$(hostname)
EOF
  echo imported >/etc/multiroom/rooms/.legacy-imported
fi

install -m 0755 "$AGENT_DIR/multiroom-snapclient-room" /usr/local/bin/multiroom-snapclient-room
install -m 0755 "$AGENT_DIR/bt-pair.sh" /usr/local/bin/multiroom-bt-pair
install -m 0755 "$AGENT_DIR/bt-connect.sh" /usr/local/bin/multiroom-bt-connect
sed "s/__MULTIROOM_USER__/${RUN_USER}/g" \
  "$AGENT_DIR/multiroom-room@.service" \
  >/etc/systemd/system/multiroom-room@.service
install -m 0644 "$AGENT_DIR/multiroom-agent.service" /etc/systemd/system/multiroom-agent.service
install -m 0644 "$AGENT_DIR/agent_server.py" /opt/multiroom-agent/agent_server.py
install -m 0644 "$AGENT_DIR/requirements.txt" /opt/multiroom-agent/requirements.txt

if [[ ! -x /opt/multiroom-agent/venv/bin/python ]]; then
  python3 -m venv /opt/multiroom-agent/venv
fi
/opt/multiroom-agent/venv/bin/pip install --upgrade pip
/opt/multiroom-agent/venv/bin/pip install -r /opt/multiroom-agent/requirements.txt

# A previous install started one PulseAudio client before any speaker existed.
systemctl disable --now multiroom-snapclient.service >/dev/null 2>&1 || true

systemctl daemon-reload
systemctl enable --now bluetooth
systemctl enable --now bluealsa
systemctl enable --now multiroom-agent.service

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "Installed (snapclient user: ${RUN_USER})."
echo "  Snapcast server: ${SNAP_HOST}"
echo "  Pair a speaker:  http://${IP:-<pi-ip>}:8190"
echo
