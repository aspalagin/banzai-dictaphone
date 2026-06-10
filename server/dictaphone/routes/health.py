"""Health check endpoint."""
from __future__ import annotations

import json
from typing import Any

from aiohttp import web
from protocol import utc_now_iso


async def health(request: web.Request) -> web.Response:
    from config import ALLOW_INSECURE, SESSIONS_DIR, STT_ENABLED, STT_PROVIDER, TOKEN

    return web.json_response(
        {
            "ok": True,
            "service": "banzai-dictaphone",
            "time": utc_now_iso(),
            "auth_configured": bool(TOKEN) or ALLOW_INSECURE,
            "sessions_dir": str(SESSIONS_DIR),
            "stt_enabled": STT_ENABLED,
            "stt_provider": STT_PROVIDER,
        },
        status=200,
        dumps=lambda x: json.dumps(x, ensure_ascii=False),
    )