from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hub.config import get_settings
from hub.feeder import StreamFeeder
from hub.navidrome import NavidromeClient
from hub.playback import PlaybackController
from hub.services import collect_services, run_service_action
from hub.snapcast import SnapcastClient, SnapcastError
from hub.store import RoomStore

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hub")


class VolumeBody(BaseModel):
    percent: int = Field(ge=0, le=100)
    muted: bool | None = None


class MuteBody(BaseModel):
    muted: bool


class LatencyBody(BaseModel):
    latency: int = Field(ge=0, le=5000)


class NameBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class GroupClientsBody(BaseModel):
    clients: list[str]


class PlayTrackBody(BaseModel):
    id: str
    queue: list[str] | None = None


class PlayAlbumBody(BaseModel):
    id: str
    start_index: int = 0


class PlayArtistBody(BaseModel):
    id: str
    shuffle: bool = True


class PlayRadioBody(BaseModel):
    id: str
    count: int = 50


class EnqueueBody(BaseModel):
    id: str


class AgentBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=3, max_length=256)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    navidrome = NavidromeClient(settings)
    snapcast = SnapcastClient(settings)
    feeder = StreamFeeder(settings)
    playback = PlaybackController(navidrome, feeder)
    store = RoomStore(settings.data_dir)

    app.state.settings = settings
    app.state.navidrome = navidrome
    app.state.snapcast = snapcast
    app.state.feeder = feeder
    app.state.playback = playback
    app.state.store = store
    log.info("Hub started; Navidrome=%s Snapcast=%s:%s", settings.navidrome_url, settings.snapcast_host, settings.snapcast_control_port)
    yield
    await feeder.stop()
    await navidrome.close()


app = FastAPI(title="Multiroom Audio Hub", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def nav() -> NavidromeClient:
    return app.state.navidrome


def snap() -> SnapcastClient:
    return app.state.snapcast


def pb() -> PlaybackController:
    return app.state.playback


def store() -> RoomStore:
    return app.state.store


@app.get("/api/health")
async def health() -> dict[str, Any]:
    settings = app.state.settings
    result: dict[str, Any] = {
        "ok": True,
        "navidrome_configured": nav().configured(),
        "navidrome_url": settings.navidrome_url,
    }
    try:
        await snap().get_status()
        result["snapcast"] = "ok"
    except SnapcastError as exc:
        result["snapcast"] = f"error: {exc}"
    if nav().configured():
        try:
            await nav().ping()
            result["navidrome"] = "ok"
        except Exception as exc:
            result["navidrome"] = f"error: {exc}"
    else:
        result["navidrome"] = "not_configured"
    return result


# --- Rooms / Snapcast ---


@app.get("/api/rooms")
async def list_rooms() -> dict[str, Any]:
    try:
        status = await snap().get_status()
    except SnapcastError as exc:
        raise HTTPException(503, str(exc)) from exc
    rooms = store().apply_nicknames(snap().rooms_from_status(status))
    groups = snap().groups_from_status(status)
    return {"rooms": rooms, "groups": groups}


@app.post("/api/rooms/{client_id}/volume")
async def set_volume(client_id: str, body: VolumeBody) -> dict[str, Any]:
    try:
        await snap().set_client_volume(client_id, body.percent, body.muted)
    except SnapcastError as exc:
        raise HTTPException(502, str(exc)) from exc
    return await list_rooms()


@app.post("/api/rooms/{client_id}/mute")
async def set_mute(client_id: str, body: MuteBody) -> dict[str, Any]:
    try:
        await snap().set_client_mute(client_id, body.muted)
    except SnapcastError as exc:
        raise HTTPException(502, str(exc)) from exc
    return await list_rooms()


@app.post("/api/rooms/{client_id}/latency")
async def set_latency(client_id: str, body: LatencyBody) -> dict[str, Any]:
    try:
        await snap().set_client_latency(client_id, body.latency)
    except SnapcastError as exc:
        raise HTTPException(502, str(exc)) from exc
    return await list_rooms()


@app.post("/api/rooms/{client_id}/name")
async def set_name(client_id: str, body: NameBody) -> dict[str, Any]:
    store().set_nickname(client_id, body.name)
    try:
        await snap().set_client_name(client_id, body.name)
    except SnapcastError:
        pass  # nickname still persisted locally
    return await list_rooms()


@app.post("/api/groups/{group_id}/mute")
async def group_mute(group_id: str, body: MuteBody) -> dict[str, Any]:
    try:
        await snap().set_group_mute(group_id, body.muted)
    except SnapcastError as exc:
        raise HTTPException(502, str(exc)) from exc
    return await list_rooms()


@app.post("/api/groups/{group_id}/clients")
async def group_clients(group_id: str, body: GroupClientsBody) -> dict[str, Any]:
    try:
        await snap().set_group_clients(group_id, body.clients)
    except SnapcastError as exc:
        raise HTTPException(502, str(exc)) from exc
    return await list_rooms()


# --- Navidrome library ---


@app.get("/api/library/search")
async def library_search(q: str = Query("")) -> dict[str, Any]:
    if not nav().configured():
        raise HTTPException(503, "Navidrome credentials not configured")
    try:
        result = await nav().search(q)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    artists = result.get("artist") or []
    albums = result.get("album") or []
    songs = result.get("song") or []
    for a in albums:
        a["coverUrl"] = nav().cover_url(a.get("coverArt"))
    for s in songs:
        s["coverUrl"] = nav().cover_url(s.get("coverArt"))
    for ar in artists:
        ar["coverUrl"] = nav().cover_url(ar.get("coverArt") or ar.get("id"))
    return {"artists": artists, "albums": albums, "songs": songs}


@app.get("/api/library/artists")
async def library_artists() -> dict[str, Any]:
    if not nav().configured():
        raise HTTPException(503, "Navidrome credentials not configured")
    try:
        artists = await nav().get_artists()
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"artists": artists}


@app.get("/api/library/artists/{artist_id}")
async def library_artist(artist_id: str) -> dict[str, Any]:
    try:
        artist = await nav().get_artist(artist_id)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    albums = artist.get("album") or []
    for a in albums:
        a["coverUrl"] = nav().cover_url(a.get("coverArt"))
    return {"artist": artist, "albums": albums}


@app.get("/api/library/albums")
async def library_albums(
    list_type: str = Query("newest"),
    size: int = 40,
    offset: int = 0,
) -> dict[str, Any]:
    if not nav().configured():
        raise HTTPException(503, "Navidrome credentials not configured")
    try:
        albums = await nav().get_album_list(list_type, size, offset)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    for a in albums:
        a["coverUrl"] = nav().cover_url(a.get("coverArt"))
    return {"albums": albums}


@app.get("/api/library/albums/{album_id}")
async def library_album(album_id: str) -> dict[str, Any]:
    try:
        album = await nav().get_album(album_id)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    album["coverUrl"] = nav().cover_url(album.get("coverArt"))
    songs = album.get("song") or []
    for s in songs:
        s["coverUrl"] = nav().cover_url(s.get("coverArt") or album.get("coverArt"))
    return {"album": album, "songs": songs}


@app.get("/api/library/cover")
async def library_cover(id: str = Query(...), size: int = 300) -> Response:
    if not nav().configured():
        raise HTTPException(503, "Navidrome credentials not configured")
    url = nav().upstream_cover_url(id, size)
    if not url:
        raise HTTPException(404, "No cover")
    try:
        resp = await nav()._client.get(url)
        resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    content_type = resp.headers.get("content-type", "image/jpeg")
    return Response(content=resp.content, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})


# --- Playback ---


@app.get("/api/playback")
async def get_playback() -> dict[str, Any]:
    return pb().state.to_dict()


@app.post("/api/playback/play")
async def play_track(body: PlayTrackBody) -> dict[str, Any]:
    try:
        state = await pb().play_track(body.id, body.queue)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return state.to_dict()


@app.post("/api/playback/album")
async def play_album(body: PlayAlbumBody) -> dict[str, Any]:
    try:
        state = await pb().play_album(body.id, body.start_index)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return state.to_dict()


@app.post("/api/playback/artist")
async def play_artist(body: PlayArtistBody) -> dict[str, Any]:
    try:
        state = await pb().play_artist(body.id, shuffle=body.shuffle)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return state.to_dict()


@app.post("/api/playback/radio")
async def play_radio(body: PlayRadioBody) -> dict[str, Any]:
    try:
        state = await pb().play_radio(body.id, count=max(10, min(body.count, 100)))
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return state.to_dict()


@app.post("/api/playback/enqueue")
async def enqueue(body: EnqueueBody) -> dict[str, Any]:
    try:
        state = await pb().enqueue(body.id)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return state.to_dict()


@app.post("/api/playback/skip")
async def skip() -> dict[str, Any]:
    return (await pb().skip()).to_dict()


@app.post("/api/playback/stop")
async def stop() -> dict[str, Any]:
    return (await pb().stop()).to_dict()


@app.post("/api/playback/pause")
async def pause() -> dict[str, Any]:
    return (await pb().pause()).to_dict()


@app.post("/api/playback/resume")
async def resume() -> dict[str, Any]:
    return (await pb().resume()).to_dict()


@app.post("/api/playback/clear-queue")
async def clear_queue() -> dict[str, Any]:
    return pb().clear_queue().to_dict()


# --- Services / Pi agents ---


@app.get("/api/services")
async def list_services() -> dict[str, Any]:
    return await collect_services(app.state.settings, store(), snap(), nav())


@app.post("/api/services/{host_id}/{service_id}/{action}")
async def service_action(host_id: str, service_id: str, action: str) -> dict[str, Any]:
    try:
        result = await run_service_action(store(), app.state.settings, host_id, service_id, action)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    overview = await collect_services(app.state.settings, store(), snap(), nav())
    return {"result": result, **overview}


@app.get("/api/agents")
async def list_agents() -> dict[str, Any]:
    return {"agents": store().list_agents(app.state.settings.agent_urls())}


@app.post("/api/agents")
async def add_agent(body: AgentBody) -> dict[str, Any]:
    try:
        agent = store().add_agent(body.name, body.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"agent": agent, "agents": store().list_agents(app.state.settings.agent_urls())}


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str) -> dict[str, Any]:
    if not store().remove_agent(agent_id):
        raise HTTPException(404, "Agent not found (env-configured agents cannot be removed here)")
    return {"agents": store().list_agents(app.state.settings.agent_urls())}


# --- Static UI ---

STATIC = Path(__file__).parent / "static"
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str) -> FileResponse:
        file = STATIC / full_path
        if full_path and file.is_file():
            return FileResponse(file)
        return FileResponse(STATIC / "index.html")
