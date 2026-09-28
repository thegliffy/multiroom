"""Persist friendly room nicknames and default latency overrides."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RoomStore:
    def __init__(self, data_dir: str) -> None:
        self.path = Path(data_dir) / "rooms.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {"nicknames": {}, "latency": {}}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._data = {"nicknames": {}, "latency": {}}

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
