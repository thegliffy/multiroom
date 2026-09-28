import { useCallback, useEffect, useState } from "react";
import {
  api,
  type Album,
  type Artist,
  type Playback,
  type Room,
  type Song,
} from "./api";

type View =
  | { kind: "home" }
  | { kind: "album"; id: string; title: string }
  | { kind: "artist"; id: string; title: string };

function formatDur(sec?: number) {
  if (!sec && sec !== 0) return "";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function App() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [playback, setPlayback] = useState<Playback | null>(null);
  const [albums, setAlbums] = useState<Album[]>([]);
  const [artists, setArtists] = useState<Artist[]>([]);
  const [songs, setSongs] = useState<Song[]>([]);
  const [view, setView] = useState<View>({ kind: "home" });
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [primaryGroup, setPrimaryGroup] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refreshRooms = useCallback(async () => {
    const data = await api.rooms();
    setRooms(data.rooms);
    setPrimaryGroup(data.groups[0]?.id ?? null);
    setSelected((prev) => {
      if (prev.size) return prev;
      return new Set(data.rooms.filter((r) => r.connected).map((r) => r.id));
    });
  }, []);

  const refreshPlayback = useCallback(async () => {
    setPlayback(await api.playback());
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const h = await api.health();
        if (!cancelled) {
          setHealth(`Library ${String(h.navidrome)} · Sync ${String(h.snapcast)}`);
        }
        await refreshRooms();
        await refreshPlayback();
        const newest = await api.albums("newest");
        if (!cancelled) {
          setAlbums(newest.albums);
          setArtists([]);
          setSongs([]);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    const t = setInterval(() => {
      refreshRooms().catch(() => undefined);
      refreshPlayback().catch(() => undefined);
    }, 4000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [refreshRooms, refreshPlayback]);

  useEffect(() => {
    if (!primaryGroup || !selected.size) return;
    const handle = setTimeout(() => {
      api
        .setGroupClients(primaryGroup, [...selected])
        .then((data) => setRooms(data.rooms))
        .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    }, 350);
    return () => clearTimeout(handle);
  }, [selected, primaryGroup]);

  async function withBusy(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runSearch(q: string) {
    await withBusy(async () => {
      const data = await api.search(q);
      setAlbums(data.albums);
      setArtists(data.artists);
      setSongs(data.songs);
      setView({ kind: "home" });
    });
  }

  async function openAlbum(album: Album) {
    await withBusy(async () => {
      const data = await api.album(album.id);
      setSongs(data.songs);
      setArtists([]);
      setView({ kind: "album", id: album.id, title: album.name || "Album" });
    });
  }

  async function openArtist(artist: Artist) {
    await withBusy(async () => {
      const data = await api.artist(artist.id);
      setAlbums(data.albums);
      setSongs([]);
      setArtists([]);
      setView({ kind: "artist", id: artist.id, title: artist.name || "Artist" });
    });
  }

  async function goHome() {
    await withBusy(async () => {
      setView({ kind: "home" });
      setSongs([]);
      setArtists([]);
      setAlbums((await api.albums("newest")).albums);
    });
  }

  function toggleRoom(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const current = playback?.current;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          Multi<em>room</em>
        </div>
        <div className="search-wrap">
          <input
            placeholder="Search artists, albums, tracks…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") runSearch(query);
            }}
          />
          <button type="button" disabled={busy} onClick={() => runSearch(query)}>
            Search
          </button>
        </div>
      </header>

      <div className="status">
        {health}
        {error ? <div className="err">{error}</div> : null}
      </div>

      <section className="stage">
        <div className={`hero ${current ? "playing" : ""}`}>
          {current?.cover_url ? (
            <img className="hero-art" src={current.cover_url} alt="" />
          ) : (
            <div className="hero-art-empty" aria-hidden />
          )}
          <div className="hero-copy">
            {current ? (
              <>
                <h2>{current.title}</h2>
                <p>
                  {current.artist}
                  {current.album ? ` · ${current.album}` : ""}
                  {playback?.status === "paused" ? " · paused" : ""}
                  {playback?.label ? ` · ${playback.label}` : ""}
                  {playback?.queue.length ? ` · +${playback.queue.length} queued` : ""}
                </p>
                <div className="hero-actions">
                  <button
                    type="button"
                    className="control primary"
                    aria-label={playback?.status === "playing" ? "Pause" : "Play"}
                    onClick={() =>
                      withBusy(async () => {
                        setPlayback(
                          playback?.status === "playing"
                            ? await api.pause()
                            : await api.resume()
                        );
                      })
                    }
                  >
                    {playback?.status === "playing" ? "❚❚" : "▶"}
                  </button>
                  <button
                    type="button"
                    className="control"
                    aria-label="Skip"
                    onClick={() => withBusy(async () => setPlayback(await api.skip()))}
                  >
                    ⏭
                  </button>
                  <button
                    type="button"
                    className="control"
                    aria-label="Stop"
                    onClick={() => withBusy(async () => setPlayback(await api.stop()))}
                  >
                    ■
                  </button>
                  <button
                    type="button"
                    className="btn signal"
                    disabled={busy}
                    onClick={() =>
                      withBusy(async () => setPlayback(await api.playRadio(current.id)))
                    }
                  >
                    Radio
                  </button>
                </div>
              </>
            ) : (
              <>
                <h2>Nothing playing</h2>
                <p>Play an album, an artist, or start Radio from any track for similar songs.</p>
              </>
            )}
          </div>
        </div>

        <aside className="speakers">
          <h3>Speakers</h3>
          {rooms.length === 0 ? (
            <div className="empty-speakers">
              <strong>No speakers online</strong>
              <p style={{ margin: 0, color: "var(--ink-muted)" }}>
                Open the Pi setup UI, pair a speaker, then snapclient connects here.
              </p>
              <ol>
                <li>
                  On the Pi open <code>http://&lt;pi-ip&gt;:8190</code>
                </li>
                <li>Pair on hci0 / hci1 and save a room to Snapcast <code>10.0.0.10</code></li>
              </ol>
            </div>
          ) : (
            rooms.map((room) => (
              <div className="room" key={room.id}>
                <div className="room-top">
                  <label>
                    <input
                      type="checkbox"
                      checked={selected.has(room.id)}
                      onChange={() => toggleRoom(room.id)}
                    />
                    <span
                      contentEditable
                      suppressContentEditableWarning
                      onBlur={async (e) => {
                        const name = e.currentTarget.textContent?.trim();
                        if (!name || name === room.name) return;
                        try {
                          const data = await api.setName(room.id, name);
                          setRooms(data.rooms);
                        } catch (err) {
                          setError(err instanceof Error ? err.message : String(err));
                        }
                      }}
                    >
                      {room.name}
                    </span>
                  </label>
                  <span className={`badge ${room.connected ? "" : "off"}`}>
                    {room.connected ? "live" : "away"}
                  </span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={room.volume}
                  onChange={(e) => {
                    const percent = Number(e.target.value);
                    setRooms((prev) =>
                      prev.map((r) => (r.id === room.id ? { ...r, volume: percent } : r))
                    );
                  }}
                  onMouseUp={async (e) => {
                    const percent = Number((e.target as HTMLInputElement).value);
                    try {
                      const data = await api.setVolume(room.id, percent, room.muted);
                      setRooms(data.rooms);
                    } catch (err) {
                      setError(err instanceof Error ? err.message : String(err));
                    }
                  }}
                />
                <div className="room-meta">
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        const data = await api.setMute(room.id, !room.muted);
                        setRooms(data.rooms);
                      } catch (err) {
                        setError(err instanceof Error ? err.message : String(err));
                      }
                    }}
                  >
                    {room.muted ? "Unmute" : "Mute"}
                  </button>
                  <span>
                    {room.volume}%
                    {room.host ? ` · ${room.host}` : ""}
                  </span>
                </div>
              </div>
            ))
          )}
        </aside>
      </section>

      <section className="library">
        <h3>Library</h3>
        <div className="toolbar">
          <button
            type="button"
            className={`chip ${view.kind === "home" ? "active" : ""}`}
            onClick={() => goHome()}
          >
            Newest
          </button>
        </div>

        {view.kind !== "home" ? (
          <>
            <button type="button" className="back" onClick={() => goHome()}>
              ← Back
            </button>
            <div className="row-title">
              <h2 style={{ margin: 0, fontFamily: "var(--display)" }}>
                {view.kind === "album" || view.kind === "artist" ? view.title : ""}
              </h2>
              {view.kind === "artist" ? (
                <button
                  type="button"
                  className="btn signal"
                  disabled={busy}
                  onClick={() =>
                    withBusy(async () => setPlayback(await api.playArtist(view.id, true)))
                  }
                >
                  Play artist
                </button>
              ) : null}
              {view.kind === "album" && songs[0] ? (
                <button
                  type="button"
                  className="btn signal"
                  disabled={busy}
                  onClick={() =>
                    withBusy(async () => setPlayback(await api.playRadio(songs[0].id)))
                  }
                >
                  Radio from album
                </button>
              ) : null}
            </div>
          </>
        ) : null}

        {artists.length > 0 && view.kind === "home" ? (
          <>
            <h3 style={{ marginTop: "0.5rem" }}>Artists</h3>
            <ul className="song-list" style={{ marginBottom: "1rem" }}>
              {artists.map((artist) => (
                <li key={artist.id}>
                  <button
                    type="button"
                    className="back"
                    style={{ margin: 0 }}
                    onClick={() => openArtist(artist)}
                  >
                    {artist.name}
                  </button>
                  <div className="actions">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        withBusy(async () => setPlayback(await api.playArtist(artist.id, true)))
                      }
                    >
                      Play
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        ) : null}

        {songs.length > 0 ? (
          <ul className="song-list">
            {songs.map((song, idx) => (
              <li key={song.id}>
                <div>
                  <strong>{song.title}</strong>
                  <div>
                    <small style={{ color: "var(--ink-muted)" }}>
                      {song.artist}
                      {song.duration ? ` · ${formatDur(song.duration)}` : ""}
                    </small>
                  </div>
                </div>
                <div className="actions">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      withBusy(async () => {
                        if (view.kind === "album") {
                          setPlayback(await api.playAlbum(view.id, idx));
                        } else {
                          setPlayback(await api.playTrack(song.id));
                        }
                      })
                    }
                  >
                    Play
                  </button>
                  <button
                    type="button"
                    className="queue"
                    disabled={busy}
                    onClick={() =>
                      withBusy(async () => setPlayback(await api.playRadio(song.id)))
                    }
                  >
                    Radio
                  </button>
                  <button
                    type="button"
                    className="queue"
                    disabled={busy}
                    onClick={() =>
                      withBusy(async () => setPlayback(await api.enqueue(song.id)))
                    }
                  >
                    Queue
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ) : albums.length ? (
          <div className="grid">
            {albums.map((album) => (
              <button
                key={album.id}
                className="album"
                type="button"
                onClick={() => openAlbum(album)}
              >
                {album.coverUrl ? (
                  <img src={album.coverUrl} alt="" loading="lazy" />
                ) : (
                  <div className="cover-fallback" />
                )}
                <div className="meta">
                  <strong>{album.name}</strong>
                  <small>{album.artist}</small>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <p style={{ color: "var(--ink-muted)" }}>No albums yet.</p>
        )}
      </section>

      {current ? (
        <div className="dock">
          <div className="dock-meta">
            {current.cover_url ? (
              <img src={current.cover_url} alt="" />
            ) : (
              <div className="dock-fallback" />
            )}
            <div>
              <strong>{current.title}</strong>
              <span>
                {current.artist}
                {playback?.mode === "radio" ? " · radio" : ""}
                {playback?.mode === "artist" ? " · artist" : ""}
              </span>
            </div>
          </div>
          <div className="dock-controls">
            <button
              type="button"
              className="primary"
              onClick={() =>
                withBusy(async () => {
                  setPlayback(
                    playback?.status === "playing" ? await api.pause() : await api.resume()
                  );
                })
              }
            >
              {playback?.status === "playing" ? "❚❚" : "▶"}
            </button>
            <button type="button" onClick={() => withBusy(async () => setPlayback(await api.skip()))}>
              ⏭
            </button>
            <button
              type="button"
              title="Start radio from this track"
              onClick={() =>
                withBusy(async () => setPlayback(await api.playRadio(current.id)))
              }
            >
              ♪
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
