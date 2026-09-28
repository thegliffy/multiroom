"""OpenSubsonic / Navidrome API client."""

from __future__ import annotations

import hashlib
import random
import string
from typing import Any
from urllib.parse import urlencode, urljoin

import httpx

from hub.config import Settings


def _token(password: str, salt: str) -> str:
    return hashlib.md5(f"{password}{salt}".encode()).hexdigest()


def _salt(n: int = 12) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


class NavidromeClient:
    def __init__(self, settings: Settings) -> None:
        self.base = settings.navidrome_url.rstrip("/") + "/"
        self.user = settings.navidrome_user
        self.password = settings.navidrome_password
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    def _auth_params(self) -> dict[str, str]:
        salt = _salt()
        return {
            "u": self.user,
            "t": _token(self.password, salt),
            "s": salt,
            "v": "1.16.1",
            "c": "multiroom-hub",
            "f": "json",
        }

    async def _get(self, endpoint: str, **params: Any) -> dict[str, Any]:
        query = {**self._auth_params(), **{k: v for k, v in params.items() if v is not None}}
        url = urljoin(self.base, f"rest/{endpoint}")
        resp = await self._client.get(url, params=query)
        resp.raise_for_status()
        data = resp.json()
        sub = data.get("subsonic-response") or data.get("subsonic-response".title()) or data
        # Navidrome returns {"subsonic-response": {...}}
        if "subsonic-response" in data:
            sub = data["subsonic-response"]
        if sub.get("status") == "failed":
            err = sub.get("error", {})
            raise RuntimeError(f"Navidrome error {err.get('code')}: {err.get('message')}")
        return sub

    def configured(self) -> bool:
        return bool(self.user and self.password and self.base)

    async def ping(self) -> dict[str, Any]:
        return await self._get("ping.view")

    async def search(self, query: str, artist_count: int = 20, album_count: int = 20, song_count: int = 50) -> dict[str, Any]:
        sub = await self._get(
            "search3.view",
            query=query or "",
            artistCount=artist_count,
            albumCount=album_count,
            songCount=song_count,
        )
        return sub.get("searchResult3") or {}

    async def get_artists(self) -> list[dict[str, Any]]:
        sub = await self._get("getArtists.view")
        index = (sub.get("artists") or {}).get("index") or []
        artists: list[dict[str, Any]] = []
        for bucket in index:
            artists.extend(bucket.get("artist") or [])
        return artists

    async def get_artist(self, artist_id: str) -> dict[str, Any]:
        sub = await self._get("getArtist.view", id=artist_id)
        return sub.get("artist") or {}

    async def get_album(self, album_id: str) -> dict[str, Any]:
        sub = await self._get("getAlbum.view", id=album_id)
        return sub.get("album") or {}

    async def get_song(self, song_id: str) -> dict[str, Any]:
        sub = await self._get("getSong.view", id=song_id)
        return sub.get("song") or {}

    async def get_album_list(self, list_type: str = "newest", size: int = 40, offset: int = 0) -> list[dict[str, Any]]:
        sub = await self._get("getAlbumList2.view", type=list_type, size=size, offset=offset)
        return (sub.get("albumList2") or {}).get("album") or []

    async def get_similar_songs(self, song_id: str, count: int = 50) -> list[dict[str, Any]]:
        sub = await self._get("getSimilarSongs2.view", id=song_id, count=count)
        return (sub.get("similarSongs2") or {}).get("song") or []

    async def get_top_songs(self, artist: str, count: int = 50) -> list[dict[str, Any]]:
        sub = await self._get("getTopSongs.view", artist=artist, count=count)
        return (sub.get("topSongs") or {}).get("song") or []

    async def get_random_songs(self, size: int = 50, genre: str | None = None) -> list[dict[str, Any]]:
        sub = await self._get("getRandomSongs.view", size=size, genre=genre)
        return (sub.get("randomSongs") or {}).get("song") or []

    async def get_artist_songs(self, artist_id: str) -> list[dict[str, Any]]:
        artist = await self.get_artist(artist_id)
        albums = artist.get("album") or []
        songs: list[dict[str, Any]] = []
        for album_meta in albums:
            album = await self.get_album(str(album_meta["id"]))
            songs.extend(album.get("song") or [])
        return songs

    def stream_url(self, song_id: str) -> str:
        params = self._auth_params()
        params["id"] = song_id
        return f"{self.base}rest/stream.view?{urlencode(params)}"

    def cover_url(self, cover_id: str | None, size: int = 300) -> str | None:
        if not cover_id:
            return None
        # Served via hub proxy so the browser need not reach Navidrome directly
        from urllib.parse import quote

        return f"/api/library/cover?id={quote(str(cover_id))}&size={size}"

    def upstream_cover_url(self, cover_id: str | None, size: int = 300) -> str | None:
        if not cover_id:
            return None
        params = self._auth_params()
        params["id"] = cover_id
        params["size"] = str(size)
        return f"{self.base}rest/getCoverArt.view?{urlencode(params)}"
