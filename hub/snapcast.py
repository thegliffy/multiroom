"""Snapcast JSON-RPC control client (TCP port 1705)."""

from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any

from hub.config import Settings


class SnapcastError(RuntimeError):
    pass


class SnapcastClient:
    def __init__(self, settings: Settings) -> None:
        self.host = settings.snapcast_host
        self.port = settings.snapcast_control_port
        self._id = itertools.count(1)
        self._lock = asyncio.Lock()

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request = {
            "id": next(self._id),
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            request["params"] = params

        payload = (json.dumps(request) + "\r\n").encode()
        async with self._lock:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=5.0,
                )
            except (OSError, asyncio.TimeoutError) as exc:
                raise SnapcastError(f"Cannot connect to Snapcast at {self.host}:{self.port}") from exc
            try:
                writer.write(payload)
                await writer.drain()
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        if not line:
            raise SnapcastError("Empty response from Snapcast")
        data = json.loads(line.decode())
        if "error" in data:
            err = data["error"]
            raise SnapcastError(f"{err.get('message', err)}")
        return data.get("result")

    async def get_status(self) -> dict[str, Any]:
        return await self._rpc("Server.GetStatus")

    async def set_client_volume(self, client_id: str, percent: int, muted: bool | None = None) -> Any:
        volume: dict[str, Any] = {"percent": max(0, min(100, percent))}
        if muted is not None:
            volume["muted"] = muted
        return await self._rpc("Client.SetVolume", {"id": client_id, "volume": volume})

    async def set_client_mute(self, client_id: str, muted: bool) -> Any:
        status = await self.get_status()
        client = self._find_client(status, client_id)
        percent = ((client or {}).get("config") or {}).get("volume", {}).get("percent", 100)
        return await self.set_client_volume(client_id, percent, muted=muted)

    async def set_client_latency(self, client_id: str, latency_ms: int) -> Any:
        return await self._rpc("Client.SetLatency", {"id": client_id, "latency": latency_ms})

    async def set_client_name(self, client_id: str, name: str) -> Any:
        return await self._rpc("Client.SetName", {"id": client_id, "name": name})

    async def set_group_mute(self, group_id: str, muted: bool) -> Any:
        return await self._rpc("Group.SetMute", {"id": group_id, "mute": muted})

    async def set_group_stream(self, group_id: str, stream_id: str) -> Any:
        return await self._rpc("Group.SetStream", {"id": group_id, "stream_id": stream_id})

    async def set_group_clients(self, group_id: str, client_ids: list[str]) -> Any:
        return await self._rpc("Group.SetClients", {"id": group_id, "clients": client_ids})

    @staticmethod
    def _find_client(status: dict[str, Any], client_id: str) -> dict[str, Any] | None:
        server = status.get("server") or status
        groups = (server.get("groups") if "groups" in server else status.get("groups")) or []
        # Server.GetStatus returns {"server": {"groups": ..., "streams": ...}}
        if "server" in status:
            groups = status["server"].get("groups") or []
        for group in groups:
            for client in group.get("clients") or []:
                if client.get("id") == client_id:
                    return client
        return None

    def rooms_from_status(self, status: dict[str, Any]) -> list[dict[str, Any]]:
        server = status.get("server") or status
        groups = server.get("groups") or []
        rooms: list[dict[str, Any]] = []
        for group in groups:
            group_id = group.get("id")
            group_muted = group.get("muted", False)
            stream_id = group.get("stream_id")
            for client in group.get("clients") or []:
                cfg = client.get("config") or {}
                vol = cfg.get("volume") or {}
                host = (client.get("host") or {})
                name = cfg.get("name") or host.get("name") or client.get("id")
                rooms.append(
                    {
                        "id": client.get("id"),
                        "name": name,
                        "connected": client.get("connected", False),
                        "volume": vol.get("percent", 100),
                        "muted": vol.get("muted", False) or group_muted,
                        "latency": cfg.get("latency", 0),
                        "group_id": group_id,
                        "stream_id": stream_id,
                        "host": host.get("ip") or host.get("name"),
                    }
                )
        return rooms

    def groups_from_status(self, status: dict[str, Any]) -> list[dict[str, Any]]:
        server = status.get("server") or status
        groups = server.get("groups") or []
        out: list[dict[str, Any]] = []
        for group in groups:
            clients = [c.get("id") for c in (group.get("clients") or [])]
            out.append(
                {
                    "id": group.get("id"),
                    "muted": group.get("muted", False),
                    "stream_id": group.get("stream_id"),
                    "clients": clients,
                    "name": group.get("name") or group.get("id"),
                }
            )
        return out
