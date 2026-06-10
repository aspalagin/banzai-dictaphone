"""HTTP session stop endpoint."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import web

from dictaphone.services.session_factory import recordings, write_event


async def http_stop(request: web.Request) -> web.Response:
    from config import ALLOW_INSECURE, TOKEN

    if not _check_token(request):
        raise web.HTTPUnauthorized(text="missing or invalid DICTAPHONE_TOKEN")

    from protocol import safe_session_id

    session_id = safe_session_id(request.match_info["session_id"])
    recording = recordings.pop(session_id, None)
    if not recording:
        return web.json_response({"ok": False, "error": "session_not_found"}, status=404)

    async with recording.lock:
        recording.closing = True
        recording.session.stopped = True
        try:
            recording.audio_fp.flush()
            recording.audio_fp.close()
        except Exception:
            pass
        write_event(
            recording.session,
            {"event": "stop", "transport": "http", "metadata": recording.session.metadata()},
        )

    asyncio.create_task(_stop_outputs(recording))

    return web.json_response(
        {"ok": True, **recording.session.metadata()},
        status=200,
        dumps=lambda x: json.dumps(x, ensure_ascii=False),
    )


async def _stop_outputs(recording: Any) -> None:
    """Stop transcriber and Telegram sink for an HTTP recording."""
    if recording.transcriber:
        try:
            await recording.transcriber.stop()
        except Exception as exc:
            write_event(
                recording.session,
                {"event": "stt_stop_error", "message": str(exc)[:500]},
            )

    if recording.tg_sink:
        try:
            await recording.tg_sink.stop(
                transcript_path=recording.session.transcript_path,
                audio_path=recording.session.audio_path,
                sample_rate=recording.session.sample_rate,
                channels=recording.session.channels,
            )
        except Exception as exc:
            write_event(
                recording.session,
                {"event": "telegram_stop_error", "message": str(exc)[:500]},
            )


def _check_token(request: web.Request) -> bool:
    import secrets

    from config import ALLOW_INSECURE, TOKEN

    if ALLOW_INSECURE:
        return True
    if not TOKEN:
        return False
    supplied = request.headers.get("X-Dictaphone-Token", "")
    if not supplied:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            supplied = auth.removeprefix("Bearer ").strip()
    return secrets.compare_digest(supplied, TOKEN)