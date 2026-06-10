"""HTTP session start endpoint."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import web

from dictaphone.services.outputs import OutputsOrchestrator
from dictaphone.services.session_factory import ActiveHttpRecording, create_session, recordings


async def http_start(request: web.Request) -> web.Response:
    from config import ALLOW_INSECURE, TOKEN

    if not _check_token(request):
        raise web.HTTPUnauthorized(text="missing or invalid DICTAPHONE_TOKEN")

    try:
        payload = await request.json()
    except Exception as exc:
        return web.json_response(
            {"ok": False, "error": "bad_json", "message": str(exc)}, status=400
        )

    session = create_session(payload)
    audio_fp = session.audio_path.open("ab")

    recording = ActiveHttpRecording(
        session=session,
        audio_fp=audio_fp,
    )
    recordings[session.session_id] = recording

    # Start outputs asynchronously (STT + Telegram)
    asyncio.create_task(_start_outputs(recording))

    return web.json_response(
        {"ok": True, **session.metadata()},
        status=200,
        dumps=lambda x: json.dumps(x, ensure_ascii=False),
    )


async def _start_outputs(recording: ActiveHttpRecording) -> None:
    """Start STT and Telegram sink for an HTTP recording."""
    await asyncio.sleep(0.1)
    if recording.closing or recording.session.stopped:
        return

    orchestrator = OutputsOrchestrator(
        recording.session,
        audio_path=recording.session.audio_path,
    )
    await orchestrator.start()

    async with recording.lock:
        if not recording.closing and not recording.session.stopped:
            recording.transcriber = orchestrator
            recording.tg_sink = orchestrator._tg_sink
        else:
            await orchestrator.stop(None)
            return

    # Forward pending STT chunks to the transcriber
    for chunk in recording.pending_stt:
        asyncio.create_task(_append_audio_safely(recording.session, orchestrator, chunk))
    recording.pending_stt = []


async def _append_audio_safely(
    session: Any,
    orchestrator: OutputsOrchestrator,
    data: bytes,
) -> None:
    try:
        await orchestrator.append_audio(data)
    except Exception as exc:
        from dictaphone.services.session_factory import write_event

        write_event(session, {"event": "stt_append_error", "message": str(exc)[:500]})


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