"""HTTP client status diagnostic endpoint."""
from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from dictaphone.services.session_factory import recordings, write_event


async def http_client_status(request: web.Request) -> web.Response:
    from config import ALLOW_INSECURE, SESSIONS_DIR, TOKEN

    if not _check_token(request):
        raise web.HTTPUnauthorized(text="missing or invalid DICTAPHONE_TOKEN")

    from protocol import safe_session_id, utc_now_iso

    session_id = safe_session_id(request.match_info["session_id"])
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    status = str(payload.get("status") or "")[:500]

    recording = recordings.get(session_id)
    if recording:
        write_event(recording.session, {"event": "client_status", "status": status})
    else:
        # Try to find session directory
        for date_dir in sorted(SESSIONS_DIR.iterdir(), reverse=True):
            candidate = date_dir / session_id
            if candidate.exists():
                events_path = candidate / "events.jsonl"
                try:
                    with events_path.open("a", encoding="utf-8") as fp:
                        fp.write(
                            json.dumps(
                                {"event": "client_status", "status": status, "ts": utc_now_iso()},
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                except Exception:
                    pass
                break

    return web.json_response({"ok": True})


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