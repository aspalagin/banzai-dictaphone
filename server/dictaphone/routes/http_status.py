"""HTTP session status endpoint."""
from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from dictaphone.services.session_factory import recordings


async def http_status(request: web.Request) -> web.Response:
    from config import ALLOW_INSECURE, SESSIONS_DIR, TOKEN

    if not _check_token(request):
        raise web.HTTPUnauthorized(text="missing or invalid DICTAPHONE_TOKEN")

    from protocol import safe_session_id

    session_id = safe_session_id(request.match_info["session_id"])
    recording = recordings.get(session_id)
    if recording:
        return web.json_response(
            {
                "ok": True,
                "active": True,
                "closing": recording.closing,
                "stt_active": bool(recording.transcriber),
                **recording.session.metadata(),
            },
            status=200,
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    for date_dir in sorted(SESSIONS_DIR.iterdir(), reverse=True):
        candidate = date_dir / session_id
        if candidate.exists():
            audio_path = candidate / "audio.pcm"
            transcript_path = candidate / "transcript.txt"
            return web.json_response(
                {
                    "ok": True,
                    "active": False,
                    "session_id": session_id,
                    "audio_path": str(audio_path),
                    "audio_bytes": audio_path.stat().st_size if audio_path.exists() else 0,
                    "transcript_path": str(transcript_path),
                    "transcript_exists": transcript_path.exists(),
                },
                status=200,
                dumps=lambda x: json.dumps(x, ensure_ascii=False),
            )

    return web.json_response({"ok": False, "error": "session_not_found"}, status=404)


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