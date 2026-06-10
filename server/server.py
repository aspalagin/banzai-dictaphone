#!/usr/bin/env python3
"""Banzai Dictaphone — aiohttp server entry point.

Responsibilities:
- Application bootstrap and routing
- Graceful shutdown of active recordings

All business logic (routes, session management, STT, Telegram) is in the
``dictaphone`` package. This file only wires the components together.
"""
from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import web

from config import HOST, PORT

from dictaphone import get_transcriber
from dictaphone.routes import (
    health,
    http_audio,
    http_client_status,
    http_start,
    http_status,
    http_stop,
    websocket,
)
from dictaphone.services import ActiveHttpRecording, recordings


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health.health)
    app.router.add_get("/v1/stream", websocket.stream_ws)
    app.router.add_post("/v1/http/start", http_start.http_start)
    app.router.add_post("/v1/http/audio/{session_id}", http_audio.http_audio)
    app.router.add_post("/v1/http/client-status/{session_id}", http_client_status.http_client_status)
    app.router.add_get("/v1/http/status/{session_id}", http_status.http_status)
    app.router.add_post("/v1/http/stop/{session_id}", http_stop.http_stop)
    app.on_cleanup.append(_shutdown)
    return app


async def _shutdown(app: web.Application) -> None:
    log = logging.getLogger("dictaphone.server")
    log.info("Shutting down dictaphone server")
    active = list(recordings.values())
    recordings.clear()

    for rec in active:
        rec.closing = True
        rec.session.stopped = True
        try:
            rec.audio_fp.flush()
            rec.audio_fp.close()
        except Exception:
            pass
        # Stop transcriber
        if rec.transcriber:
            try:
                await rec.transcriber.stop()
            except Exception:
                pass
        # Stop Telegram sink
        if rec.tg_sink:
            try:
                await rec.tg_sink.stop(
                    transcript_path=rec.session.transcript_path,
                    audio_path=rec.session.audio_path,
                    sample_rate=rec.session.sample_rate,
                    channels=rec.session.channels,
                )
            except Exception:
                pass


def main() -> None:
    from dictaphone.services.session_factory import create_session

    logging.basicConfig(
        level=os.getenv("DICTAPHONE_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # Ensure sessions dir exists
    from config import SESSIONS_DIR, TOKEN, ALLOW_INSECURE

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if not TOKEN and not ALLOW_INSECURE:
        raise SystemExit(
            "DICTAPHONE_TOKEN is required. For local dev: DICTAPHONE_ALLOW_INSECURE=1"
        )

    app = create_app()
    web.run_app(app, host=HOST, port=PORT, handle_signals=True)


if __name__ == "__main__":
    main()
