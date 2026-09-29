#!/usr/bin/env python3
"""Multiroom Pi setup UI — dual Bluetooth adapters + BlueALSA + snapclient rooms."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

HOST = os.environ.get("AGENT_HOST", "0.0.0.0")
PORT = int(os.environ.get("AGENT_PORT", "8190"))
ROOMS_DIR = Path(os.environ.get("MULTIROOM_ROOMS_DIR", "/etc/multiroom/rooms"))
WRAPPER = Path("/usr/local/bin/multiroom-snapclient-room")
UNIT_TEMPLATE = "multiroom-room@.service"

app = FastAPI(title="Multiroom Pi Setup")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def run(cmd: list[str], timeout: float = 30.0, inp: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=inp,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def bt(*args: str, timeout: float = 25.0) -> str:
    proc = run(["bluetoothctl", *args], timeout=timeout)
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


def list_adapters() -> list[dict[str, str]]:
    out = bt("list")
    adapters: list[dict[str, str]] = []
    for line in out.splitlines():
        m = re.search(r"Controller\s+([0-9A-Fa-f:]{17})\s+(.*?)(?:\s+\[default\])?$", line)
        if not m:
            continue
        mac = m.group(1).upper()
        name = m.group(2).strip()
        # Map BDADDR -> hciX via hciconfig
        hci = ""
        hc = run(["hciconfig", "-a"]).stdout or ""
        current = ""
        for hl in hc.splitlines():
            if hl.startswith("hci"):
                current = hl.split(":", 1)[0]
            if "BD Address" in hl and mac.lower() in hl.lower().replace("-", ":"):
                hci = current
        if not hci:
            # fallback order
            hci = f"hci{len(adapters)}"
        adapters.append({"id": hci, "mac": mac, "name": name or hci})
    if not adapters:
        # hciconfig-only fallback
        hc = run(["hciconfig"]).stdout or ""
        for m in re.finditer(r"^(hci\d+):", hc, re.M):
            adapters.append({"id": m.group(1), "mac": "", "name": m.group(1)})
    return adapters


def list_devices() -> list[dict[str, Any]]:
    devices: dict[str, dict[str, Any]] = {}
    for line in bt("devices").splitlines():
        m = re.search(r"Device\s+([0-9A-Fa-f:]{17})\s+(.*)$", line)
        if m:
            mac = m.group(1).upper()
            devices[mac] = {"mac": mac, "name": m.group(2).strip(), "paired": False, "connected": False}
    for line in bt("devices", "Paired").splitlines():
        m = re.search(r"Device\s+([0-9A-Fa-f:]{17})", line)
        if m:
            mac = m.group(1).upper()
            devices.setdefault(mac, {"mac": mac, "name": mac, "paired": False, "connected": False})
            devices[mac]["paired"] = True
    for line in bt("devices", "Connected").splitlines():
        m = re.search(r"Device\s+([0-9A-Fa-f:]{17})", line)
        if m:
            mac = m.group(1).upper()
            devices.setdefault(mac, {"mac": mac, "name": mac, "paired": False, "connected": False})
            devices[mac]["connected"] = True
            devices[mac]["paired"] = True
    # enrich with info
    for mac, d in list(devices.items()):
        info = bt("info", mac)
        if "Audio Sink" in info or "audio-headset" in info or "audio-card" in info:
            d["audio"] = True
        else:
            d["audio"] = "Audio Sink" in info or "Icon: audio" in info
        if re.search(r"Paired:\s*yes", info):
            d["paired"] = True
        if re.search(r"Connected:\s*yes", info):
            d["connected"] = True
        alias = re.search(r"Alias:\s*(.+)", info)
        if alias:
            d["name"] = alias.group(1).strip()
    return sorted(devices.values(), key=lambda x: (not x.get("audio"), x.get("name") or x["mac"]))


def ensure_rooms_dir() -> None:
    ROOMS_DIR.mkdir(parents=True, exist_ok=True)


def read_room(slug: str) -> dict[str, str]:
    path = ROOMS_DIR / f"{slug}.env"
    data: dict[str, str] = {"slug": slug}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    return data


def write_room(slug: str, data: dict[str, str]) -> dict[str, str]:
    ensure_rooms_dir()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", slug):
        raise HTTPException(400, "Invalid room slug")
    path = ROOMS_DIR / f"{slug}.env"
    keys = ["SNAPCAST_HOST", "ROOM_NAME", "BT_ADAPTER", "BT_MAC", "ALSA_DEVICE"]
    lines = [f"{k}={data.get(k, '')}" for k in keys]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return read_room(slug)


def list_rooms() -> list[dict[str, Any]]:
    ensure_rooms_dir()
    rooms = []
    for path in sorted(ROOMS_DIR.glob("*.env")):
        slug = path.stem
        env = read_room(slug)
        svc = f"multiroom-room@{slug}.service"
        active = run(["systemctl", "is-active", svc]).stdout.strip()
        rooms.append({**env, "slug": slug, "service": svc, "snapclient": active})
    # Import the old single-room file once. Deleting the last room must stay deleted.
    legacy = Path("/etc/multiroom/room.env")
    imported = ROOMS_DIR / ".legacy-imported"
    if not rooms and legacy.exists() and not imported.exists():
        data = {}
        for line in legacy.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
        slug = data.get("ROOM_NAME") or "room1"
        write_room(
            slug,
            {
                "SNAPCAST_HOST": data.get("SNAPCAST_HOST", "10.0.0.10"),
                "ROOM_NAME": slug,
                "BT_ADAPTER": "hci0",
                "BT_MAC": "",
                "ALSA_DEVICE": data.get("ALSA_DEVICE", ""),
            },
        )
        if data.get("ALSA_DEVICE", "").startswith("bluealsa:DEV="):
            mac = data["ALSA_DEVICE"].split("DEV=", 1)[1].split(",", 1)[0]
            write_room(
                slug,
                {
                    "SNAPCAST_HOST": data.get("SNAPCAST_HOST", "10.0.0.10"),
                    "ROOM_NAME": slug,
                    "BT_ADAPTER": "hci0",
                    "BT_MAC": mac,
                    "ALSA_DEVICE": data["ALSA_DEVICE"],
                },
            )
        imported.write_text("imported\n", encoding="utf-8")
        rooms = list_rooms()
    return rooms


def ensure_systemd_bits() -> None:
    WRAPPER.parent.mkdir(parents=True, exist_ok=True)
    WRAPPER.write_text(
        """#!/bin/bash
set -euo pipefail
SLUG="${1:?room slug}"
ENV_FILE="/etc/multiroom/rooms/${SLUG}.env"
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a
NAME="${ROOM_NAME:-$SLUG}"
HOST="${SNAPCAST_HOST:?SNAPCAST_HOST required}"
if [[ -n "${ALSA_DEVICE:-}" ]]; then
  exec /usr/bin/snapclient -h "${HOST}" --hostID "${NAME}" --player alsa --soundcard "${ALSA_DEVICE}"
fi
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
exec /usr/bin/snapclient -h "${HOST}" --hostID "${NAME}" --player pulse
""",
        encoding="utf-8",
    )
    WRAPPER.chmod(0o755)

    unit = Path(f"/etc/systemd/system/{UNIT_TEMPLATE}")
    # Detect default user
    user = "gliffy"
    if not Path(f"/home/{user}").exists():
        user = "pi"
    unit.write_text(
        f"""[Unit]
Description=Multiroom Snapclient room %i
After=network-online.target bluetooth.service bluealsa.service
Wants=network-online.target

[Service]
Type=simple
ExecStart={WRAPPER} %i
Restart=always
RestartSec=3
User={user}
Group=audio
SupplementaryGroups=bluetooth

[Install]
WantedBy=multi-user.target
""",
        encoding="utf-8",
    )
    run(["systemctl", "daemon-reload"])


class ScanBody(BaseModel):
    adapter: str = "hci0"
    seconds: int = Field(default=12, ge=5, le=30)


class DeviceBody(BaseModel):
    mac: str = Field(min_length=11)
    adapter: str = "hci0"


class RoomBody(BaseModel):
    slug: str = Field(min_length=1, max_length=32)
    snapcast_host: str = "10.0.0.10"
    room_name: str | None = None
    adapter: str = "hci0"
    mac: str = Field(min_length=11)


@app.on_event("startup")
def _startup() -> None:
    ensure_rooms_dir()
    ensure_systemd_bits()


@app.get("/api/status")
def status() -> dict[str, Any]:
    adapters = list_adapters()
    devices = list_devices()
    rooms = list_rooms()
    bluealsa = run(["systemctl", "is-active", "bluealsa"]).stdout.strip()
    return {
        "adapters": adapters,
        "devices": devices,
        "rooms": rooms,
        "bluealsa": bluealsa,
        "hostname": run(["hostname"]).stdout.strip(),
    }


@app.post("/api/bt/scan")
def scan(body: ScanBody) -> dict[str, Any]:
    bt("select", body.adapter)
    bt("power", "on")
    # Non-interactive scan
    run(["timeout", str(body.seconds + 2), "bluetoothctl", "--timeout", str(body.seconds), "scan", "on"], timeout=body.seconds + 5)
    return {"devices": list_devices(), "adapters": list_adapters()}


@app.post("/api/bt/pair")
def pair(body: DeviceBody) -> dict[str, Any]:
    mac = body.mac.upper()
    bt("select", body.adapter)
    bt("power", "on")
    bt("pairable", "on")
    # Prefer connect if already paired
    info = bt("info", mac)
    log = []
    if "Paired: yes" not in info:
        # headless agent
        agent = subprocess.Popen(
            ["bt-agent", "-c", "NoInputNoOutput"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(0.5)
            log.append(bt("pair", mac, timeout=40))
            log.append(bt("trust", mac))
        finally:
            agent.terminate()
            try:
                agent.wait(timeout=2)
            except Exception:
                agent.kill()
    else:
        log.append("already paired")
        bt("trust", mac)
    log.append(bt("connect", mac, timeout=40))
    time.sleep(2)
    return {"ok": True, "log": "\n".join(log)[-2500:], "devices": list_devices()}


@app.post("/api/bt/connect")
def connect(body: DeviceBody) -> dict[str, Any]:
    mac = body.mac.upper()
    bt("select", body.adapter)
    bt("power", "on")
    out = bt("connect", mac, timeout=40)
    time.sleep(2)
    return {"ok": True, "log": out[-1500:], "devices": list_devices()}


@app.post("/api/bt/disconnect")
def disconnect(body: DeviceBody) -> dict[str, Any]:
    mac = body.mac.upper()
    out = bt("disconnect", mac)
    return {"ok": True, "log": out, "devices": list_devices()}


@app.post("/api/rooms")
def save_room(body: RoomBody) -> dict[str, Any]:
    ensure_systemd_bits()
    slug = body.slug.strip()
    mac = body.mac.upper()
    name = (body.room_name or slug).strip()
    alsa = f"bluealsa:DEV={mac},PROFILE=a2dp"
    room = write_room(
        slug,
        {
            "SNAPCAST_HOST": body.snapcast_host.strip(),
            "ROOM_NAME": name,
            "BT_ADAPTER": body.adapter,
            "BT_MAC": mac,
            "ALSA_DEVICE": alsa,
        },
    )
    # Make sure connected on that adapter
    bt("select", body.adapter)
    bt("power", "on")
    bt("connect", mac, timeout=40)
    time.sleep(2)
    svc = f"multiroom-room@{slug}.service"
    # stop legacy single client to avoid fighting over hostID
    run(["systemctl", "disable", "--now", "multiroom-snapclient.service"])
    run(["systemctl", "enable", "--now", svc])
    run(["systemctl", "restart", svc])
    time.sleep(1)
    room["snapclient"] = run(["systemctl", "is-active", svc]).stdout.strip()
    room["service"] = svc
    return {"room": room, "rooms": list_rooms(), "devices": list_devices()}


@app.delete("/api/rooms/{slug}")
def delete_room(slug: str) -> dict[str, Any]:
    ensure_rooms_dir()
    (ROOMS_DIR / ".legacy-imported").write_text("imported\n", encoding="utf-8")
    svc = f"multiroom-room@{slug}.service"
    run(["systemctl", "disable", "--now", svc])
    path = ROOMS_DIR / f"{slug}.env"
    if path.exists():
        path.unlink()
    return {"rooms": list_rooms()}


@app.post("/api/rooms/{slug}/restart")
def restart_room(slug: str) -> dict[str, Any]:
    svc = f"multiroom-room@{slug}.service"
    run(["systemctl", "restart", svc])
    return {"snapclient": run(["systemctl", "is-active", svc]).stdout.strip(), "rooms": list_rooms()}


CORE_SERVICES = [
    ("multiroom-agent.service", "Pairing UI", "Multiroom agent on :8190"),
    ("bluealsa.service", "BlueALSA", "Bluetooth A2DP audio"),
    ("bluetooth.service", "Bluetooth", "BlueZ stack"),
]


def _systemctl_show(unit: str) -> dict[str, str]:
    proc = run(
        [
            "systemctl",
            "show",
            unit,
            "--no-page",
            "-p",
            "Id",
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "UnitFileState",
            "-p",
            "Description",
            "-p",
            "FragmentPath",
        ]
    )
    props: dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    return props


def _service_entry(unit: str, name: str, detail: str, controllable: bool = True) -> dict[str, Any]:
    props = _systemctl_show(unit)
    state = props.get("ActiveState") or run(["systemctl", "is-active", unit]).stdout.strip() or "unknown"
    enabled = props.get("UnitFileState") or ""
    desc = props.get("Description") or detail
    actions = ["restart", "start", "stop"] if controllable else ["restart"] if unit == "multiroom-agent.service" else []
    if unit == "multiroom-agent.service":
        # Stopping the agent kills this API; restart is still useful.
        actions = ["restart"]
    return {
        "id": unit,
        "name": name,
        "kind": "systemd",
        "state": state,
        "sub_state": props.get("SubState") or "",
        "enabled": enabled,
        "detail": detail or desc,
        "controllable": bool(actions),
        "actions": actions,
    }


def list_services() -> list[dict[str, Any]]:
    services = [_service_entry(unit, name, detail) for unit, name, detail in CORE_SERVICES]
    seen = {s["id"] for s in services}
    for room in list_rooms():
        unit = room.get("service") or f"multiroom-room@{room['slug']}.service"
        if unit in seen:
            continue
        detail = " · ".join(
            x for x in [room.get("BT_ADAPTER"), room.get("BT_MAC"), room.get("SNAPCAST_HOST")] if x
        )
        services.append(
            _service_entry(
                unit,
                f"Room · {room.get('ROOM_NAME') or room.get('slug')}",
                detail or room.get("slug", ""),
            )
        )
        seen.add(unit)
    # Catch orphaned room units still loaded in systemd
    listed = run(["systemctl", "list-units", "multiroom-room@*.service", "--all", "--no-legend", "--no-pager"])
    for line in (listed.stdout or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0]
        if not unit.endswith(".service") or unit in seen:
            continue
        slug = unit[len("multiroom-room@") : -len(".service")] if unit.startswith("multiroom-room@") else unit
        services.append(_service_entry(unit, f"Room · {slug}", "systemd unit"))
        seen.add(unit)
    return services


@app.get("/api/services")
def get_services() -> dict[str, Any]:
    return {
        "hostname": run(["hostname"]).stdout.strip(),
        "services": list_services(),
    }


@app.post("/api/services/{service_id}/{action}")
def service_action(service_id: str, action: str) -> dict[str, Any]:
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(400, "action must be start, stop, or restart")
    if not re.match(r"^[A-Za-z0-9@._:-]+$", service_id):
        raise HTTPException(400, "invalid service id")
    allowed = {s["id"]: s for s in list_services()}
    meta = allowed.get(service_id)
    if not meta:
        raise HTTPException(404, f"Unknown service: {service_id}")
    if action not in (meta.get("actions") or []):
        raise HTTPException(400, f"{action} not allowed for {service_id}")
    proc = run(["systemctl", action, service_id], timeout=45.0)
    if proc.returncode != 0 and action != "restart":
        # restart of multiroom-agent may cut the response; treat other failures as errors
        err = (proc.stderr or proc.stdout or "").strip() or f"systemctl {action} failed"
        raise HTTPException(500, err)
    time.sleep(0.4)
    return {
        "ok": True,
        "service": next((s for s in list_services() if s["id"] == service_id), None),
        "services": list_services(),
        "log": ((proc.stdout or "") + (proc.stderr or "")).strip(),
    }


UI = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Pair a speaker</title>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700&family=Manrope:wght@400;600;700&display=swap" rel="stylesheet"/>
<style>
:root{--ink:#10141c;--muted:#5c677a;--cobalt:#1f4f9c;--signal:#d97706;--ok:#0f7a4e;--danger:#b42318;--line:rgba(16,20,28,.12);--paper:#eef2f7}
*{box-sizing:border-box}
body{margin:0;font-family:Manrope,system-ui,sans-serif;color:var(--ink);
background:radial-gradient(800px 420px at 0 0,rgba(31,79,156,.16),transparent 55%),linear-gradient(180deg,#f7f8fb,var(--paper));min-height:100vh}
main{max-width:720px;margin:0 auto;padding:1.25rem 1rem 2.5rem}
h1{font-family:"Bricolage Grotesque",system-ui,sans-serif;font-size:2rem;margin:0;letter-spacing:-.03em}
.lead{color:var(--muted);margin:.4rem 0 1.1rem;line-height:1.45}
.card{background:rgba(255,255,255,.92);border:1px solid var(--line);border-radius:18px;padding:1rem 1rem 1.1rem;margin-bottom:1rem;box-shadow:0 16px 40px rgba(16,20,28,.08)}
.step-no{display:inline-flex;align-items:center;justify-content:center;width:1.6rem;height:1.6rem;border-radius:999px;background:var(--cobalt);color:#fff;font-size:.85rem;margin-right:.45rem}
h2{margin:0 0 .35rem;font-size:1.05rem;font-weight:700;display:flex;align-items:center}
.hint{color:var(--muted);margin:0 0 .85rem;font-size:.92rem;line-height:1.45}
.row{display:flex;flex-wrap:wrap;gap:.5rem;align-items:end}
label{display:grid;gap:.3rem;font-weight:600;font-size:.88rem;flex:1;min-width:160px}
input,select{padding:.7rem .75rem;border-radius:12px;border:1px solid var(--line);font:inherit;background:#fff;width:100%}
button{border:0;border-radius:999px;padding:.7rem 1.05rem;background:var(--cobalt);color:#fff;font:inherit;font-weight:700;cursor:pointer}
button:disabled{opacity:.45;cursor:wait}
button.ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}
button.signal{background:var(--signal)}
button.danger{background:var(--danger)}
.item{display:flex;flex-wrap:wrap;justify-content:space-between;gap:.65rem;align-items:center;padding:.75rem;border-radius:12px;background:#fff;border:1px solid var(--line);margin-top:.5rem}
.item .who{min-width:0;flex:1}
.item strong{display:block}
.item small{color:var(--muted);word-break:break-all}
.actions{display:flex;flex-wrap:wrap;gap:.4rem}
.badge{display:inline-block;padding:.12rem .45rem;border-radius:999px;font-size:.68rem;font-weight:700;text-transform:uppercase;background:rgba(15,122,78,.12);color:var(--ok)}
.badge.off{background:rgba(180,35,24,.1);color:var(--danger)}
.badge.soft{background:rgba(31,79,156,.1);color:var(--cobalt)}
.empty{color:var(--muted);margin:.2rem 0 0}
#picked{font-weight:700}
details{margin-top:.75rem;color:var(--muted);font-size:.88rem}
pre{white-space:pre-wrap;background:#10141c;color:#dbe4f0;padding:.75rem;border-radius:12px;font-size:.75rem;max-height:140px;overflow:auto;margin-top:.6rem}
#msg{min-height:1.2rem;margin:.6rem 0 0;font-size:.9rem}
#msg.ok{color:var(--ok)} #msg.err{color:var(--danger)}
</style>
</head>
<body>
<main>
  <h1>Pair a speaker</h1>
  <p class="lead" id="hostline">Put the speaker in pairing mode first — hold its Bluetooth button until the light blinks. One speaker per radio.</p>

  <section class="card">
    <h2><span class="step-no">1</span> Find it</h2>
    <p class="hint">Pick the radio (hci0 is the first, hci1 the second), then scan for about 12 seconds.</p>
    <div class="row">
      <label>Radio
        <select id="adapter"></select>
      </label>
      <button id="scan" type="button">Scan for speakers</button>
    </div>
    <div id="devices"></div>
  </section>

  <section class="card">
    <h2><span class="step-no">2</span> Name it and start</h2>
    <p class="hint" id="picked">No speaker selected yet. Scan, then tap Pair.</p>
    <label>Room name
      <input id="rname" placeholder="Living room" autocomplete="off"/>
    </label>
    <div class="row" style="margin-top:.75rem">
      <button class="signal" id="saveRoom" type="button" disabled>Start this speaker</button>
    </div>
    <details>
      <summary>Advanced</summary>
      <label style="margin-top:.7rem">Snapcast host
        <input id="host" value="10.0.0.10"/>
      </label>
    </details>
    <div id="msg"></div>
    <pre id="log" hidden></pre>
  </section>

  <section class="card">
    <h2>Speakers on this Pi</h2>
    <p class="hint">These already send audio to Multiroom. Remove one if it should not play.</p>
    <div id="rooms"></div>
  </section>

  <section class="card">
    <h2>Services on this Pi</h2>
    <p class="hint">Start, stop, or restart the local Multiroom stack. Restarting the pairing UI may briefly disconnect this page.</p>
    <div id="services"></div>
  </section>
</main>
<script>
let selectedMac = '';
let busy = false;

async function api(path, opts){
  const res = await fetch(path, Object.assign({headers:{'Content-Type':'application/json'}}, opts||{}));
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = {detail: text}; }
  if(!res.ok) throw new Error(data.detail || text || res.statusText);
  return data;
}
function badge(ok, on, off){return `<span class="badge ${ok?'':'off'}">${ok?on:off}</span>`}
function setMsg(text, cls){
  const el = document.getElementById('msg');
  el.className = cls || '';
  el.textContent = text || '';
}
function slugify(name){
  const s = (name||'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,32);
  return s || 'speaker';
}
function pick(mac, name){
  selectedMac = mac;
  const input = document.getElementById('rname');
  if(!input.value.trim() && name && !/^([0-9A-F]{2}:){5}[0-9A-F]{2}$/.test(name)) input.value = name;
  document.getElementById('picked').textContent = name
    ? `Selected: ${name} (${mac})`
    : `Selected: ${mac}`;
  document.getElementById('saveRoom').disabled = !selectedMac;
}
function render(s){
  document.getElementById('hostline').textContent =
    `${s.hostname} · Bluetooth audio ${s.bluealsa==='active'?'ready':'not running'} · ${s.adapters.length} radio(s)`;
  const sel=document.getElementById('adapter');
  const cur=sel.value;
  sel.innerHTML=(s.adapters||[]).map((a,i)=>
    `<option value="${a.id}">Radio ${i+1} · ${a.id}${a.name&&a.name!==a.id?' · '+a.name:''}</option>`
  ).join('') || '<option value="hci0">No radio found</option>';
  if(cur) sel.value=cur;

  const list=(s.devices||[]).filter(d=>d.audio || d.paired || d.connected);
  const show=list.length?list:(s.devices||[]);
  document.getElementById('devices').innerHTML = show.map(d=>{
    const state = d.connected ? 'connected' : (d.paired ? 'paired, not connected' : 'not paired');
    return `<div class="item">
      <div class="who"><strong>${d.name||'Speaker'}</strong><small>${d.mac} · ${state}</small></div>
      <div class="actions">
        <button type="button" data-pair="${d.mac}" data-name="${(d.name||'').replace(/"/g,'')}">${d.paired?'Connect':'Pair'}</button>
      </div>
    </div>`;
  }).join('') || '<p class="empty">No speakers yet. Put one in pairing mode, then scan.</p>';
  document.querySelectorAll('[data-pair]').forEach(b=>b.onclick=()=>pair(b.dataset.pair, b.dataset.name));

  document.getElementById('rooms').innerHTML=(s.rooms||[]).map(r=>`
    <div class="item">
      <div class="who"><strong>${r.ROOM_NAME||r.slug}</strong>
        <small>${r.BT_ADAPTER||'radio ?'} · ${r.BT_MAC||'no speaker'}</small></div>
      <div class="actions">
        ${badge(r.snapclient==='active','playing','not playing')}
        <button class="ghost" type="button" data-restart="${r.slug}">Restart</button>
        <button class="danger" type="button" data-del="${r.slug}">Remove</button>
      </div>
    </div>`).join('') || '<p class="empty">None yet. Pair a speaker above to add one.</p>';
  document.querySelectorAll('[data-restart]').forEach(b=>b.onclick=async()=>{
    setMsg('Restarting '+b.dataset.restart+'…');
    await api('/api/rooms/'+b.dataset.restart+'/restart',{method:'POST'});
    setMsg('Restarted.','ok');
    refresh();
  });
  document.querySelectorAll('[data-del]').forEach(b=>b.onclick=async()=>{
    if(!confirm('Remove '+b.dataset.del+' from this Pi?')) return;
    await api('/api/rooms/'+b.dataset.del,{method:'DELETE'});
    setMsg('Removed '+b.dataset.del+'.','ok');
    refresh();
  });
  document.getElementById('saveRoom').disabled = busy || !selectedMac;
  renderServices(s.services);
}
async function renderServices(list){
  const services = list || (await api('/api/services').catch(()=>({services:[]}))).services || [];
  document.getElementById('services').innerHTML = services.map(svc=>{
    const ok = svc.state==='active';
    const actions=(svc.actions||[]).map(a=>
      `<button class="${a==='stop'?'danger':'ghost'}" type="button" data-svc="${svc.id}" data-act="${a}">${a}</button>`
    ).join('');
    return `<div class="item">
      <div class="who"><strong>${svc.name}</strong>
        <small>${svc.id}${svc.detail?' · '+svc.detail:''}</small></div>
      <div class="actions">
        ${badge(ok, svc.state, svc.state)}
        ${actions}
      </div>
    </div>`;
  }).join('') || '<p class="empty">No services reported.</p>';
  document.querySelectorAll('[data-svc]').forEach(b=>b.onclick=async()=>{
    setMsg(b.dataset.act+' '+b.dataset.svc+'…');
    try{
      await api('/api/services/'+encodeURIComponent(b.dataset.svc)+'/'+b.dataset.act,{method:'POST'});
      setMsg('Done.','ok');
    }catch(e){ setMsg(String(e.message||e),'err'); }
    refresh();
  });
}
async function refresh(){
  const s = await api('/api/status');
  try {
    const svc = await api('/api/services');
    s.services = svc.services;
  } catch {}
  render(s);
}
async function pair(mac, name){
  busy = true;
  document.getElementById('saveRoom').disabled = true;
  const log=document.getElementById('log');
  log.hidden=false;
  log.textContent='Pairing '+mac+'… keep the speaker in pairing mode.';
  setMsg('Pairing…');
  try{
    const r=await api('/api/bt/pair',{method:'POST',body:JSON.stringify({mac, adapter:document.getElementById('adapter').value})});
    log.textContent=r.log||'Paired.';
    pick(mac, name);
    setMsg('Paired. Give it a room name, then start it.','ok');
  }catch(e){
    log.textContent=String(e.message||e);
    setMsg(String(e.message||e),'err');
  }finally{
    busy=false;
    await refresh();
    pick(mac, name);
  }
}
document.getElementById('scan').onclick=async()=>{
  const btn=document.getElementById('scan');
  btn.disabled=true;
  setMsg('Scanning for 12 seconds. Leave the speaker blinking.');
  const log=document.getElementById('log');
  log.hidden=true;
  try{
    await api('/api/bt/scan',{method:'POST',body:JSON.stringify({adapter:document.getElementById('adapter').value, seconds:12})});
    setMsg('Scan finished. Tap Pair on your speaker.','ok');
    await refresh();
  }catch(e){
    setMsg(String(e.message||e),'err');
  }finally{
    btn.disabled=false;
  }
};
document.getElementById('saveRoom').onclick=async()=>{
  const name=document.getElementById('rname').value.trim();
  const body={
    slug:slugify(name),
    room_name:name || slugify(name),
    snapcast_host:document.getElementById('host').value.trim() || '10.0.0.10',
    adapter:document.getElementById('adapter').value,
    mac:selectedMac
  };
  if(!body.mac){ setMsg('Pair a speaker first.','err'); return; }
  const btn=document.getElementById('saveRoom');
  btn.disabled=true;
  setMsg('Starting '+body.room_name+'…');
  try{
    const r=await api('/api/rooms',{method:'POST',body:JSON.stringify(body)});
    const state=(r.room&&r.room.snapclient)||'started';
    setMsg(body.room_name+' is '+state+'. It should show as live in Multiroom.','ok');
    await refresh();
  }catch(e){
    setMsg(String(e.message||e),'err');
    btn.disabled=!selectedMac;
  }
};
refresh().catch(e=>setMsg(String(e.message||e),'err'));
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return UI


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
