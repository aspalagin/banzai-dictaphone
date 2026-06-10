"""Routes package: HTTP and WebSocket endpoint handlers."""
from __future__ import annotations

from dictaphone.routes import (
    health,
    http_audio,
    http_client_status,
    http_start,
    http_status,
    http_stop,
    websocket,
)

__all__ = [
    "health",
    "http_audio",
    "http_client_status",
    "http_start",
    "http_status",
    "http_stop",
    "websocket",
]