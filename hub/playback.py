"""Playback queue and now-playing state."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field, asdict
from typing import Any

from hub.feeder import StreamFeeder
from hub.navidrome import NavidromeClient

log = logging.getLogger("hub.playback")


@dataclass
class Track:
    id: str
    title: str
    artist: str = ""
    album: str = ""
    duration: int | None = None
    cover_art: str | None = None
    cover_url: str | None = None

    @classmethod
    def from_song(cls, song: dict[str, Any], cover_url: str | None = None) -> "Track":
        return cls(
            id=str(song.get("id")),
            title=song.get("title") or "Unknown",
            artist=song.get("artist") or "",
            album=song.get("album") or "",
            duration=song.get("duration"),
            cover_art=song.get("coverArt"),
            cover_url=cover_url,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlaybackState:
    status: str = "stopped"  # stopped | playing | paused
    current: Track | None = None
    queue: list[Track] = field(default_factory=list)
    mode: str = "queue"  # queue | artist | radio
    seed_id: str | None = None
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "current": self.current.to_dict() if self.current else None,
            "queue": [t.to_dict() for t in self.queue],
            "mode": self.mode,
            "seed_id": self.seed_id,
            "label": self.label,
        }


class PlaybackController:
    def __init__(self, navidrome: NavidromeClient, feeder: StreamFeeder) -> None:
        self.navidrome = navidrome
        self.feeder = feeder
        self.state = PlaybackState()
        self.feeder.on_ended = self._on_track_ended
        self._seen: set[str] = set()

    async def _on_track_ended(self) -> None:
        if self.state.mode == "radio" and len(self.state.queue) < 5 and self.state.seed_id:
            try:
                await self._extend_radio(self.state.seed_id, count=30)
            except Exception:
                log.exception("Failed to extend radio queue")
        if self.state.queue:
            await self.skip()
        else:
            self.state.status = "stopped"
            self.state.current = None
            self.state.mode = "queue"
            self.state.label = None

    def _enrich(self, song: dict[str, Any]) -> Track:
        cover = self.navidrome.cover_url(song.get("coverArt"))
        return Track.from_song(song, cover_url=cover)

    def _dedupe_songs(self, songs: list[dict[str, Any]], *, reset_seen: bool = False) -> list[dict[str, Any]]:
        if reset_seen:
            self._seen = set()
        out: list[dict[str, Any]] = []
        for song in songs:
            sid = str(song.get("id"))
            if not sid or sid in self._seen:
                continue
            self._seen.add(sid)
            out.append(song)
        return out

    async def play_track(self, song_id: str, enqueue_rest: list[str] | None = None) -> PlaybackState:
        song = await self.navidrome.get_song(song_id)
        track = self._enrich(song)
        self.state.queue = []
        self.state.mode = "queue"
        self.state.seed_id = None
        self.state.label = None
        self._seen = {song_id}
        if enqueue_rest:
            for sid in enqueue_rest:
                s = await self.navidrome.get_song(sid)
                self.state.queue.append(self._enrich(s))
                self._seen.add(str(sid))
        self.state.current = track
        self.state.status = "playing"
        await self.feeder.play(self.navidrome.stream_url(song_id))
        return self.state

    async def play_album(self, album_id: str, start_index: int = 0) -> PlaybackState:
        album = await self.navidrome.get_album(album_id)
        songs = album.get("song") or []
        if not songs:
            raise ValueError("Album has no songs")
        start_index = max(0, min(start_index, len(songs) - 1))
        first = songs[start_index]
        rest_ids = [str(s["id"]) for s in songs[start_index + 1 :]]
        state = await self.play_track(str(first["id"]), enqueue_rest=rest_ids)
        self.state.mode = "queue"
        self.state.label = album.get("name") or "Album"
        return state

    async def play_artist(self, artist_id: str, *, shuffle: bool = True) -> PlaybackState:
        songs = await self.navidrome.get_artist_songs(artist_id)
        if not songs:
            raise ValueError("Artist has no songs")
        songs = self._dedupe_songs(songs, reset_seen=True)
        if shuffle:
            random.shuffle(songs)
        first = songs[0]
        rest = [str(s["id"]) for s in songs[1:]]
        artist = await self.navidrome.get_artist(artist_id)
        state = await self.play_track(str(first["id"]), enqueue_rest=rest)
        self.state.mode = "artist"
        self.state.seed_id = artist_id
        self.state.label = f"Artist · {artist.get('name') or 'Unknown'}"
        return state

    async def _radio_candidates(self, seed_id: str, count: int) -> list[dict[str, Any]]:
        songs = await self.navidrome.get_similar_songs(seed_id, count=count)
        if len(songs) < max(5, count // 4):
            seed = await self.navidrome.get_song(seed_id)
            artist_name = seed.get("artist") or ""
            if artist_name:
                tops = await self.navidrome.get_top_songs(artist_name, count=count)
                songs = songs + tops
            if seed.get("artistId"):
                own = await self.navidrome.get_artist_songs(str(seed["artistId"]))
                songs = songs + own
            rnd = await self.navidrome.get_random_songs(size=count)
            songs = songs + rnd
        return songs

    async def _extend_radio(self, seed_id: str, count: int = 30) -> None:
        songs = self._dedupe_songs(await self._radio_candidates(seed_id, count))
        random.shuffle(songs)
        for song in songs[:count]:
            self.state.queue.append(self._enrich(song))

    async def play_radio(self, seed_id: str, count: int = 50) -> PlaybackState:
        seed = await self.navidrome.get_song(seed_id)
        songs = self._dedupe_songs(await self._radio_candidates(seed_id, count), reset_seen=True)
        # Keep seed first, then shuffled similar
        songs = [s for s in songs if str(s.get("id")) != seed_id]
        random.shuffle(songs)
        playlist = [seed] + songs[: count - 1]
        if not playlist:
            raise ValueError("No songs available for radio")
        first = playlist[0]
        rest = [str(s["id"]) for s in playlist[1:]]
        state = await self.play_track(str(first["id"]), enqueue_rest=rest)
        self.state.mode = "radio"
        self.state.seed_id = seed_id
        title = seed.get("title") or "track"
        artist = seed.get("artist") or ""
        self.state.label = f"Radio · {title}" + (f" — {artist}" if artist else "")
        return state

    async def enqueue(self, song_id: str) -> PlaybackState:
        song = await self.navidrome.get_song(song_id)
        self.state.queue.append(self._enrich(song))
        self._seen.add(song_id)
        if self.state.status == "stopped" and self.state.current is None:
            return await self.skip()
        return self.state

    async def skip(self) -> PlaybackState:
        if self.state.mode == "radio" and len(self.state.queue) < 5 and self.state.seed_id:
            try:
                await self._extend_radio(self.state.seed_id, count=30)
            except Exception:
                log.exception("Failed to extend radio queue")
        if self.state.queue:
            nxt = self.state.queue.pop(0)
            self.state.current = nxt
            self.state.status = "playing"
            if self.state.mode == "radio":
                self.state.seed_id = nxt.id
            await self.feeder.play(self.navidrome.stream_url(nxt.id))
        else:
            await self.stop()
        return self.state

    async def stop(self) -> PlaybackState:
        await self.feeder.stop()
        self.state.status = "stopped"
        self.state.current = None
        self.state.mode = "queue"
        self.state.seed_id = None
        self.state.label = None
        return self.state

    async def pause(self) -> PlaybackState:
        if self.state.status == "playing":
            await self.feeder.stop()
            self.state.status = "paused"
        return self.state

    async def resume(self) -> PlaybackState:
        if self.state.status == "paused" and self.state.current:
            await self.feeder.play(self.navidrome.stream_url(self.state.current.id))
            self.state.status = "playing"
        return self.state

    def clear_queue(self) -> PlaybackState:
        self.state.queue = []
        return self.state
