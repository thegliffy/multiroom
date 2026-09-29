"""Aggregate Multiroom stack + Pi agent service status."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from hub.config import Settings
from hub.navidrome import NavidromeClient
from hub.snapcast import SnapcastClient, SnapcastError
from hub.store import RoomStore

log = logging.getLogger("hub.services")

SAFE_SERVICE = re.compile(r"^[A-Za-z0-9@._:-]+$")
SAFE_ACTION = frozenset({"start", "stop", "restart"})


def _local_hub_service() -> dict[str, Any]:
    return {
        "id": "multiroom-hub",
        "name": "Hub API + UI",
        "kind": "process",
        "state": "active",
        "detail": "Responding",
        "controllable": False,
        "actions": [],
    }


async def _probe_snapcast(snap: SnapcastClient) -> dict[str, Any]:
    try:
        status = await snap.get_status()
        server = status.get("server") or status
        groups = server.get("groups") or []
        clients = sum(len(g.get("clients") or []) for g in groups)
        connected = sum(
            1
            for g in groups
            for c in (g.get("clients") or [])
            if c.get("connected")
        )
        return {
            "id": "snapcast",
            "name": "Snapcast",
            "kind": "tcp",
            "state": "active",
            "detail": f"{connected}/{clients} clients connected",
            "controllable": False,
            "actions": [],
        }
    except SnapcastError as exc:
        return {
            "id": "snapcast",
            "name": "Snapcast",
            "kind": "tcp",
            "state": "failed",
            "detail": str(exc),
            "controllable": False,
            "actions": [],
        }


async def _probe_navidrome(nav: NavidromeClient) -> dict[str, Any]:
    if not nav.configured():
        return {
            "id": "navidrome",
            "name": "Navidrome",
            "kind": "http",
            "state": "inactive",
            "detail": "Not configured",
            "controllable": False,
            "actions": [],
        }
    try:
        await nav.ping()
        return {
            "id": "navidrome",
            "name": "Navidrome",
            "kind": "http",
            "state": "active",
            "detail": nav.base.rstrip("/"),
            "controllable": False,
            "actions": [],
        }
    except Exception as exc:
        return {
            "id": "navidrome",
            "name": "Navidrome",
            "kind": "http",
            "state": "failed",
            "detail": str(exc),
            "controllable": False,
            "actions": [],
        }


async def _fetch_agent_services(agent: dict[str, str], client: httpx.AsyncClient) -> dict[str, Any]:
    url = agent["url"].rstrip("/")
    host: dict[str, Any] = {
        "id": agent["id"],
        "name": agent["name"],
        "kind": "agent",
        "url": url,
        "reachable": False,
        "services": [],
        "hostname": None,
        "error": None,
    }
    try:
        resp = await client.get(f"{url}/api/services", timeout=4.0)
        resp.raise_for_status()
        data = resp.json()
        host["reachable"] = True
        host["hostname"] = data.get("hostname")
        host["services"] = data.get("services") or []
    except Exception as exc:
        host["error"] = str(exc)
        # Fallback: older agents only expose /api/status
        try:
            resp = await client.get(f"{url}/api/status", timeout=4.0)
            resp.raise_for_status()
            data = resp.json()
            host["reachable"] = True
            host["hostname"] = data.get("hostname")
            host["error"] = None
            host["services"] = _services_from_legacy_status(data)
        except Exception as fallback_exc:
            host["error"] = str(fallback_exc)
    return host


def _services_from_legacy_status(data: dict[str, Any]) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = [
        {
            "id": "bluealsa.service",
            "name": "BlueALSA",
            "kind": "systemd",
            "state": data.get("bluealsa") or "unknown",
            "detail": "Bluetooth audio",
            "controllable": False,
            "actions": [],
        }
    ]
    for room in data.get("rooms") or []:
        slug = room.get("slug") or "room"
        state = room.get("snapclient") or "unknown"
        services.append(
            {
                "id": room.get("service") or f"multiroom-room@{slug}.service",
                "name": f"Room · {room.get('ROOM_NAME') or slug}",
                "kind": "systemd",
                "state": state,
                "detail": room.get("BT_MAC") or slug,
                "controllable": True,
                "actions": ["restart", "stop", "start"],
            }
        )
    return services


async def collect_services(
    settings: Settings,
    store: RoomStore,
    snap: SnapcastClient,
    nav: NavidromeClient,
) -> dict[str, Any]:
    local_services = await asyncio.gather(_probe_snapcast(snap), _probe_navidrome(nav))
    hosts: list[dict[str, Any]] = [
        {
            "id": "hub",
            "name": "Hub host",
            "kind": "local",
            "url": None,
            "reachable": True,
            "hostname": None,
            "error": None,
            "services": [_local_hub_service(), *local_services],
        }
    ]

    agents = store.list_agents(settings.agent_urls())
    async with httpx.AsyncClient() as client:
        remote = await asyncio.gather(*[_fetch_agent_services(a, client) for a in agents])
    hosts.extend(remote)

    suggestions = await _suggest_agents(snap, {a["url"].rstrip("/") for a in agents})
    return {"hosts": hosts, "suggestions": suggestions}


async def _suggest_agents(snap: SnapcastClient, known_urls: set[str]) -> list[dict[str, str]]:
    try:
        status = await snap.get_status()
    except SnapcastError:
        return []
    rooms = snap.rooms_from_status(status)
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for room in rooms:
        host = (room.get("host") or "").strip()
        if not host or host in ("127.0.0.1", "localhost"):
            continue
        url = f"http://{host}:8190"
        if url in known_urls or url in seen:
            continue
        seen.add(url)
        out.append({"name": room.get("name") or host, "url": url, "host": host})
    return out


async def run_service_action(
    store: RoomStore,
    settings: Settings,
    host_id: str,
    service_id: str,
    action: str,
) -> dict[str, Any]:
    if action not in SAFE_ACTION:
        raise ValueError(f"Unsupported action: {action}")
    if not SAFE_SERVICE.match(service_id):
        raise ValueError(f"Invalid service id: {service_id}")
    if host_id == "hub":
        raise ValueError("Hub-host services are view-only from this UI")

    agents = {a["id"]: a for a in store.list_agents(settings.agent_urls())}
    agent = agents.get(host_id)
    if not agent:
        raise KeyError(f"Unknown host: {host_id}")

    url = agent["url"].rstrip("/")
    encoded = quote(service_id, safe="@._-:")
    async with httpx.AsyncClient(timeout=20.0) as client:
        # Prefer dedicated services API; fall back to room restart for older agents.
        try:
            resp = await client.post(f"{url}/api/services/{encoded}/{action}")
            if resp.status_code < 400:
                return resp.json()
        except Exception:
            pass
        if action == "restart" and service_id.startswith("multiroom-room@") and service_id.endswith(".service"):
            slug = service_id[len("multiroom-room@") : -len(".service")]
            resp = await client.post(f"{url}/api/rooms/{quote(slug, safe='')}/restart")
            resp.raise_for_status()
            return resp.json()
        resp = await client.post(f"{url}/api/services/{encoded}/{action}")
        resp.raise_for_status()
        return resp.json()
