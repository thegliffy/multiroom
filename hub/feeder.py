"""ffmpeg feeder: Navidrome stream URL -> Snapcast TCP PCM source."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from hub.config import Settings

log = logging.getLogger("hub.feeder")


class StreamFeeder:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self.on_ended: Callable[[], Awaitable[None]] | None = None
        self._watch_task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def stop(self) -> None:
        async with self._lock:
            if self._watch_task and not self._watch_task.done():
                self._watch_task.cancel()
                try:
                    await self._watch_task
                except asyncio.CancelledError:
                    pass
            self._watch_task = None
            if self._proc and self._proc.returncode is None:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    self._proc.kill()
                    await self._proc.wait()
            self._proc = None

    async def play(self, stream_url: str) -> None:
        await self.stop()
        host = self.settings.snapcast_host
        port = self.settings.snapcast_tcp_port
        # Raw PCM matching snapserver sampleformat=48000:16:2
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-re",
            "-i",
            stream_url,
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "2",
            "-ar",
            "48000",
            f"tcp://{host}:{port}",
        ]
        async with self._lock:
            log.info("Starting ffmpeg feeder -> tcp://%s:%s", host, port)
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            self._watch_task = asyncio.create_task(self._watch(self._proc))

    async def _watch(self, proc: asyncio.subprocess.Process) -> None:
        stderr = b""
        if proc.stderr:
            stderr = await proc.stderr.read()
        code = await proc.wait()
        log.info("ffmpeg exited code=%s stderr=%s", code, stderr.decode(errors="replace")[-500:])
        if self.on_ended and code == 0:
            try:
                await self.on_ended()
            except Exception:
                log.exception("on_ended callback failed")
