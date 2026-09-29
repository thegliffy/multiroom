"""Persist friendly room nicknames, latency overrides, and Pi agent registry."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _normalize_url(url: str) -> str:
    value = url.strip().rstrip("/")
    if not value:
        raise ValueError("URL is required")
    if "://" not in value:
        value = "http://" + value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("URL must be http(s) with a host")
    return value.rstrip("/")


class RoomStore:
    def __init__(self, data_dir: str) -> None:
        self.path = Path(data_dir) / "rooms.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {"nicknames": {}, "latency": {}, "agents": []}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._data = {"nicknames": {}, "latency": {}, "agents": []}
        self._data.setdefault("nicknames", {})
        self._data.setdefault("latency", {})
        self._data.setdefault("agents", [])

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def get_nickname(self, client_id: str) -> str | None:
        return (self._data.get("nicknames") or {}).get(client_id)

    def set_nickname(self, client_id: str, name: str) -> None:
        self._data.setdefault("nicknames", {})[client_id] = name
        self._save()

    def apply_nicknames(self, rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
        nicks = self._data.get("nicknames") or {}
        for room in rooms:
            if room["id"] in nicks:
                room["name"] = nicks[room["id"]]
                room["nickname"] = nicks[room["id"]]
        return rooms

    def list_agents(self, env_agents: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
        """Merge env-provided agents with persisted ones (persisted wins on URL match)."""
        by_url: dict[str, dict[str, str]] = {}
        for agent in env_agents or []:
            url = _normalize_url(agent["url"])
            by_url[url] = {
                "id": agent.get("id") or f"env-{re.sub(r'[^a-z0-9]+', '-', url.lower())[:40]}",
                "name": agent.get("name") or url,
                "url": url,
                "source": "env",
            }
        for agent in self._data.get("agents") or []:
            try:
                url = _normalize_url(str(agent.get("url") or ""))
            except ValueError:
                continue
            by_url[url] = {
                "id": str(agent.get("id") or uuid.uuid4()),
                "name": str(agent.get("name") or url),
                "url": url,
                "source": "store",
            }
        return list(by_url.values())

    def add_agent(self, name: str, url: str) -> dict[str, str]:
        url = _normalize_url(url)
        agents = self._data.setdefault("agents", [])
        for existing in agents:
            if _normalize_url(str(existing.get("url") or "")) == url:
                existing["name"] = name.strip() or existing.get("name") or url
                self._save()
                return {
                    "id": str(existing["id"]),
                    "name": str(existing["name"]),
                    "url": url,
                    "source": "store",
                }
        agent = {
            "id": str(uuid.uuid4()),
            "name": name.strip() or urlparse(url).hostname or url,
            "url": url,
        }
        agents.append(agent)
        self._save()
        return {**agent, "source": "store"}

    def remove_agent(self, agent_id: str) -> bool:
        agents = self._data.get("agents") or []
        kept = [a for a in agents if str(a.get("id")) != agent_id]
        if len(kept) == len(agents):
            return False
        self._data["agents"] = kept
        self._save()
        return True
