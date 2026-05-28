from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SESSION_ID_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_session_id(value: str) -> str:
    value = SESSION_ID_RE.sub("-", value.strip())[:80].strip("-")
    return value or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@dataclass
class DictaphoneSession:
    session_id: str
    root: Path
    device: str = "unknown"
    mode: str = "dictation"
    sample_rate: int = 16000
    channels: int = 1
    encoding: str = "pcm_s16le"
    started_at: str = field(default_factory=utc_now_iso)
    paused: bool = False
    stopped: bool = False
    bytes_received: int = 0
    chunks_received: int = 0

    @property
    def audio_path(self) -> Path:
        return self.root / "audio.pcm"

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def transcript_path(self) -> Path:
        return self.root / "transcript.txt"

    def metadata(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "device": self.device,
            "mode": self.mode,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "encoding": self.encoding,
            "started_at": self.started_at,
            "paused": self.paused,
            "stopped": self.stopped,
            "bytes_received": self.bytes_received,
            "chunks_received": self.chunks_received,
            "audio_path": str(self.audio_path),
            "events_path": str(self.events_path),
            "transcript_path": str(self.transcript_path),
        }
