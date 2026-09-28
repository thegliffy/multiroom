# Multiroom Audio

Navidrome library → hub → Snapcast → a Raspberry Pi `snapclient` → a Bluetooth speaker.

One speaker uses one Bluetooth radio. A Pi with two radios can run two rooms. Pairing is done in a browser on the Pi.

## Hub

On the Linux host that already runs Navidrome:

```bash
cp .env.example .env
# set NAVIDROME_URL, NAVIDROME_USER, NAVIDROME_PASSWORD

docker compose up -d --build
```

Open **http://\<hub-ip\>:8188** (this stack uses **8188**, not 8080).

## Raspberry Pi

Copy this repo to the Pi, then:

```bash
chmod +x agent/*.sh agent/multiroom-snapclient-room
sudo ./agent/install.sh 10.0.0.10
```

Open **http://\<pi-ip\>:8190**:

1. Put the speaker in pairing mode.
2. Pick the radio and **Scan for speakers**.
3. Tap **Pair**, name the room, then **Start this speaker**.

The room shows up in the hub as live once `snapclient` is connected. Snapcast host defaults to `10.0.0.10` under **Advanced**.

To add a room from the shell instead:

```bash
sudo ./agent/add-room.sh kitchen 10.0.0.10 hci0 AA:BB:CC:DD:EE:FF
```

## Docs

- [docs/setup.md](docs/setup.md) — hub, pairing, latency
- [docs/multi-adapter.md](docs/multi-adapter.md) — one USB dongle per extra speaker

## Dev (without the Docker UI build)

```bash
pip install -r hub/requirements.txt
DATA_DIR=./data uvicorn hub.main:app --reload --port 8188

cd web && npm install && npm run dev
```

## Architecture

| Piece | Role |
|--------|------|
| Navidrome | Library and stream URLs |
| Hub | Browse/play UI, queue, ffmpeg into Snapcast |
| Snapcast | Sample-aligned sync to every client |
| snapclient on the Pi | Receives the stream and plays it through BlueALSA to the speaker |
