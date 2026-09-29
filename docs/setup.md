# Setup guide

## 1. Hub host (Linux + Docker)

`network_mode: host` is required so Snapcast clients on the LAN can reach ports **1704** (stream) and **1705** (control), and so the hub can feed PCM to **4953**.

1. Clone/copy this repo onto the hub machine.
2. Copy env and point at Navidrome:

   ```bash
   cp .env.example .env
   ```

   ```env
   NAVIDROME_URL=http://192.168.1.10:4533
   NAVIDROME_USER=youruser
   NAVIDROME_PASSWORD=yourpassword
   SNAPCAST_HOST=127.0.0.1
   ```

3. Start:

   ```bash
   docker compose up -d --build
   ```

4. Check health: `http://<hub-ip>:8188/api/health`  
   You want `"navidrome": "ok"` and `"snapcast": "ok"`.

### Firewall

Allow inbound TCP **8188** (UI), **1704**, **1705** from your LAN. Port **4953** only needs to be reachable from the hub container (localhost with host networking).

### Windows / macOS Docker Desktop

Host networking is not equivalent to Linux. Run the hub stack on a Linux box on the same LAN as the Pis (recommended: same machine as Navidrome, or a dedicated Pi 5).

## 2. Raspberry Pi

```bash
sudo ./agent/install.sh 10.0.0.10
```

That installs Snapcast’s client, BlueALSA (the Pi plays as a Bluetooth source), and the pairing page. It does not start a room until a speaker is paired.

Open **`http://<pi-ip>:8190`**:

1. Put the speaker in pairing mode (hold its Bluetooth button until it blinks).
2. Pick the radio. `hci0` is the first, `hci1` the second.
3. **Scan for speakers**, then **Pair**.
4. Name the room and **Start this speaker**.

Each room is `/etc/multiroom/rooms/<slug>.env` plus `multiroom-room@<slug>.service`. Audio goes out as:

```text
bluealsa:DEV=AA:BB:CC:DD:EE:FF,PROFILE=a2dp
```

The room should show as live in the hub (`http://10.0.0.10:8188` or `https://multiroom.gliffy.tv`). **Away** means that snapclient is not connected.

Shell equivalent:

```bash
sudo ./agent/add-room.sh livingroom 10.0.0.10 hci0 AA:BB:CC:DD:EE:FF
```

`multiroom-bt-connect` reconnects a speaker that is already trusted. The room service restarts snapclient; BlueALSA reconnects the speaker when the room starts.

## 3. Sync / latency (Bluetooth delay)

Bluetooth A2DP adds delay. In the web UI, raise **Latency ms** on a room until it matches the others (often 50–200+ ms). Snapcast applies this as buffer compensation so rooms stay aligned.

## 4. Using the UI

1. Open `http://<hub-ip>:8188`
2. Confirm rooms show as **live** (away means the Pi client is not connected)
3. Check the rooms that should play together (sync group)
4. Browse/search Navidrome and hit **Play**
5. Adjust per-room volume / mute / latency

### Services panel

Open **Services** in the hub top bar to see the hub stack (Hub, Snapcast, Navidrome) and every registered Pi.

1. Add each Pi pairing UI (`http://<pi-ip>:8190`), or click a Snapcast suggestion when a client is already connected.
2. From there you can **start / stop / restart** BlueALSA, Bluetooth, room snapclients, and the pairing UI.
3. You can also set `MULTIROOM_AGENTS=Living|http://10.0.0.20:8190` in `.env` so agents are registered at boot.

Hub-side Docker services are shown as health only (restart them with `docker compose`).

## 5. Troubleshooting

| Symptom | Check |
|---------|--------|
| Snapcast error in health | `docker compose logs snapcast` — is port 1705 listening? |
| Navidrome error | URL reachable from hub host? User/pass correct? |
| Play does nothing | `docker compose logs hub` — ffmpeg errors? Is TCP 4953 open in snapserver? |
| Room missing | `systemctl status multiroom-room@<slug>` and `journalctl -u multiroom-room@<slug> -f` — or use **Services** in the hub |
| Pi unreachable in Services | Can you open `http://<pi-ip>:8190` from the hub host? Firewall / wrong URL? |
| No sound | Speaker paired on that radio? `ALSA_DEVICE` in `/etc/multiroom/rooms/<slug>.env` should be `bluealsa:DEV=<MAC>,PROFILE=a2dp` |
| Rooms out of sync | Increase latency on the early room(s) |

## 6. One radio = one speaker

Do not expect two A2DP sinks on the built-in Pi Bluetooth adapter. For a second speaker on the same Pi, add a USB dongle and follow [multi-adapter.md](multi-adapter.md).
