"""HTTP audio chunk endpoint."""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from aiohttp import web

from dictaphone.services.session_factory import recordings, write_event


async def http_audio(request: web.Request) -> web.Response:
    from config import ALLOW_INSECURE, MAX_AUDIO_MESSAGE_BYTES, TOKEN

    if not _check_token(request):
        raise web.HTTPUnauthorized(text="missing or invalid DICTAPHONE_TOKEN")

    from protocol import safe_session_id

    session_id = safe_session_id(request.match_info["session_id"])
    recording = recordings.get(session_id)
    if not recording:
        return web.json_response({"ok": False, "error": "session_not_found"}, status=404)

    if request.content_type == "application/json":
        try:
            payload = await request.json()
            data = base64.b64decode(str(payload.get("audio") or ""), validate=True)
        except Exception as exc:
            return web.json_response(
                {"ok": False, "error": "bad_audio_json", "message": str(exc)}, status=400
            )
    else:
        data = await request.read()

    if not data:
        return web.json_response({"ok": False, "error": "empty_audio"}, status=400)
    if len(data) > MAX_AUDIO_MESSAGE_BYTES:
        return web.json_response(
            {"ok": False, "error": "audio_too_large", "max_bytes": MAX_AUDIO_MESSAGE_BYTES},
            status=413,
        )

    async with recording.lock:
        if recording.session.stopped or recording.closing:
            return web.json_response({"ok": False, "error": "session_stopped"}, status=409)

        audio_fp = recording.audio_fp
        audio_fp.write(data)
        recording.session.bytes_received += len(data)
        recording.session.chunks_received += 1

        if recording.session.chunks_received == 1:
            audio_fp.flush()
            write_event(
                recording.session,
                {
                    "event": "first_audio_chunk",
                    "bytes_received": recording.session.bytes_received,
                    "chunk_bytes": len(data),
                },
            )
        elif recording.session.chunks_received % 25 == 0:
            audio_fp.flush()
            write_event(
                recording.session,
                {
                    "event": "audio_progress",
                    "bytes_received": recording.session.bytes_received,
                    "chunks_received": recording.session.chunks_received,
                },
            )

        # Route to transcriber or buffer if not ready
        if recording.transcriber:
            asyncio.create_task(recording.transcriber.append_audio(data))
        elif len(recording.pending_stt) < 40:
            recording.pending_stt.append(data)

    return web.json_response(
        {
            "ok": True,
            "session_id": recording.session.session_id,
            "bytes_received": recording.session.bytes_received,
            "chunks_received": recording.session.chunks_received,
            "stt_active": bool(recording.transcriber),
        },
        status=200,
        dumps=lambda x: json.dumps(x, ensure_ascii=False),
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