# Multiple Bluetooth speakers on one Raspberry Pi

One Bluetooth adapter plays one A2DP speaker. A second speaker needs a second radio, usually a USB dongle.

```text
Pi
├── hci0 (built-in)   → Speaker A → multiroom-room@livingroom
└── hci1 (USB dongle) → Speaker B → multiroom-room@kitchen
```

Each room is its own `snapclient` and its own card in the hub.

## 1. Install once

```bash
sudo ./agent/install.sh 10.0.0.10
```

## 2. See the radios

```bash
bluetoothctl list
hciconfig
```

## 3. Add a room per speaker

From the pairing page at `http://<pi-ip>:8190`, pick the radio, scan, pair, and start. Or from the shell:

```bash
sudo ./agent/add-room.sh livingroom 10.0.0.10 hci0 AA:BB:CC:DD:EE:FF
sudo ./agent/add-room.sh kitchen 10.0.0.10 hci1 CC:DD:EE:FF:00:11
```

Each command writes `/etc/multiroom/rooms/<slug>.env` and enables `multiroom-room@<slug>`.

```env
SNAPCAST_HOST=10.0.0.10
ROOM_NAME=kitchen
BT_ADAPTER=hci1
BT_MAC=CC:DD:EE:FF:00:11
ALSA_DEVICE=bluealsa:DEV=CC:DD:EE:FF:00:11,PROFILE=a2dp
```

`ROOM_NAME` is Snapcast’s host id, so two clients on one Pi stay distinct.

## 4. Radios

- A powered USB hub is safer when several dongles share a Pi 4.
- Short extension cables keep the dongles from sitting on top of each other.
- CSR and Realtek adapters are the ones that usually hold an A2DP source link.
