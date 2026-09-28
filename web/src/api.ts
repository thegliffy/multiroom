export type Room = {
  id: string;
  name: string;
  connected: boolean;
  volume: number;
  muted: boolean;
  latency: number;
  group_id: string;
  stream_id?: string;
  host?: string;
  nickname?: string;
};

export type Group = {
  id: string;
  name: string;
  muted: boolean;
  stream_id?: string;
  clients: string[];
};

export type Track = {
  id: string;
  title: string;
  artist: string;
  album: string;
  duration?: number;
  cover_url?: string | null;
};

export type Playback = {
  status: "stopped" | "playing" | "paused";
  current: Track | null;
  queue: Track[];
  mode?: "queue" | "artist" | "radio";
  seed_id?: string | null;
  label?: string | null;
};

export type Song = {
  id: string;
  title?: string;
  artist?: string;
  album?: string;
  duration?: number;
  coverArt?: string;
  coverUrl?: string;
};

export type Album = {
  id: string;
  name?: string;
  artist?: string;
  artistId?: string;
  coverArt?: string;
  coverUrl?: string;
  songCount?: number;
};

export type Artist = {
  id: string;
  name?: string;
  albumCount?: number;
  coverUrl?: string;
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<Record<string, unknown>>("/api/health"),
  rooms: () => req<{ rooms: Room[]; groups: Group[] }>("/api/rooms"),
  setVolume: (id: string, percent: number, muted?: boolean) =>
    req<{ rooms: Room[]; groups: Group[] }>(`/api/rooms/${encodeURIComponent(id)}/volume`, {
      method: "POST",
      body: JSON.stringify({ percent, muted }),
    }),
  setMute: (id: string, muted: boolean) =>
    req<{ rooms: Room[]; groups: Group[] }>(`/api/rooms/${encodeURIComponent(id)}/mute`, {
      method: "POST",
      body: JSON.stringify({ muted }),
    }),
  setLatency: (id: string, latency: number) =>
    req<{ rooms: Room[]; groups: Group[] }>(`/api/rooms/${encodeURIComponent(id)}/latency`, {
      method: "POST",
      body: JSON.stringify({ latency }),
    }),
  setName: (id: string, name: string) =>
    req<{ rooms: Room[]; groups: Group[] }>(`/api/rooms/${encodeURIComponent(id)}/name`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  setGroupClients: (groupId: string, clients: string[]) =>
    req<{ rooms: Room[]; groups: Group[] }>(`/api/groups/${encodeURIComponent(groupId)}/clients`, {
      method: "POST",
      body: JSON.stringify({ clients }),
    }),
  search: (q: string) =>
    req<{ artists: Artist[]; albums: Album[]; songs: Song[] }>(
      `/api/library/search?q=${encodeURIComponent(q)}`
    ),
  albums: (listType = "newest") =>
    req<{ albums: Album[] }>(`/api/library/albums?list_type=${encodeURIComponent(listType)}`),
  album: (id: string) =>
    req<{ album: Album; songs: Song[] }>(`/api/library/albums/${encodeURIComponent(id)}`),
  artists: () => req<{ artists: Artist[] }>("/api/library/artists"),
  artist: (id: string) =>
    req<{ artist: Artist; albums: Album[] }>(`/api/library/artists/${encodeURIComponent(id)}`),
  playback: () => req<Playback>("/api/playback"),
  playTrack: (id: string, queue?: string[]) =>
    req<Playback>("/api/playback/play", {
      method: "POST",
      body: JSON.stringify({ id, queue }),
    }),
  playAlbum: (id: string, start_index = 0) =>
    req<Playback>("/api/playback/album", {
      method: "POST",
      body: JSON.stringify({ id, start_index }),
    }),
  playArtist: (id: string, shuffle = true) =>
    req<Playback>("/api/playback/artist", {
      method: "POST",
      body: JSON.stringify({ id, shuffle }),
    }),
  playRadio: (id: string, count = 50) =>
    req<Playback>("/api/playback/radio", {
      method: "POST",
      body: JSON.stringify({ id, count }),
    }),
  enqueue: (id: string) =>
    req<Playback>("/api/playback/enqueue", {
      method: "POST",
      body: JSON.stringify({ id }),
    }),
  skip: () => req<Playback>("/api/playback/skip", { method: "POST" }),
  stop: () => req<Playback>("/api/playback/stop", { method: "POST" }),
  pause: () => req<Playback>("/api/playback/pause", { method: "POST" }),
  resume: () => req<Playback>("/api/playback/resume", { method: "POST" }),
};
