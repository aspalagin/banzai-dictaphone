"""Session factory and active recording registry."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from protocol import DictaphoneSession, safe_session_id, utc_now_iso

# Global registry of active HTTP recordings
recordings: dict[str, "ActiveHttpRecording"] = {}


def create_session(payload: dict[str, Any]) -> DictaphoneSession:
    """Create a new DictaphoneSession from a start payload and write the start event."""
    from config import SESSIONS_DIR, STT_DEFAULT_SAMPLE_RATE

    now = datetime.now(timezone.utc)
    requested_id = str(payload.get("session_id") or now.strftime("%Y%m%dT%H%M%SZ"))
    session_id = safe_session_id(requested_id)
    root = SESSIONS_DIR / now.strftime("%Y-%m-%d") / session_id
    suffix = 1
    while root.exists():
        suffix += 1
        root = SESSIONS_DIR / now.strftime("%Y-%m-%d") / f"{session_id}-{suffix}"
    root.mkdir(parents=True, exist_ok=False)

    session = DictaphoneSession(
        session_id=root.name,
        root=root,
        device=str(payload.get("device") or "unknown")[:120],
        mode=str(payload.get("mode") or "dictation")[:60],
        sample_rate=int(payload.get("sample_rate") or STT_DEFAULT_SAMPLE_RATE),
        channels=int(payload.get("channels") or 1),
        encoding=str(payload.get("encoding") or "pcm_s16le")[:40],
    )
    write_event(session, {"event": "start", "metadata": session.metadata()})
    return session


def write_event(session: DictaphoneSession, event: dict[str, Any]) -> None:
    """Append an event to the session's events.jsonl file."""
    event.setdefault("ts", utc_now_iso())
    with session.events_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(event, ensure_ascii=False) + "\n")


def write_event_raw(session: DictaphoneSession, event: dict[str, Any]) -> None:
    """Alias for write_event - kept for compatibility."""
    write_event(session, event)


@dataclass
class ActiveHttpRecording:
    """Holds all state for an active HTTP recording session."""

    session: DictaphoneSession
    audio_fp: Any  # typing.IO would require Python 3.10+
    transcriber: Any | None = None
    tg_sink: Any | None = None
    lock: dataclass.field(default_factory=lambda: __import__("asyncio").Lock()) = field(
        default_factory=lambda: __import__("asyncio").Lock()
    )
    closing: bool = False
    pending_stt: list[bytes] = field(default_factory=list)