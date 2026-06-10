"""STT provider abstraction layer.

Provides AbstractTranscriber base class and get_transcriber() factory.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any

EventWriter = Callable[[dict[str, Any]], None]


class AbstractTranscriber(ABC):
    """Base class for all STT providers."""

    def __init__(
        self,
        *,
        session_id: str,
        sample_rate: int,
        transcript_path: Path,
        write_event: EventWriter,
    ) -> None:
        self.session_id = session_id
        self.sample_rate = sample_rate
        self.transcript_path = transcript_path
        self.write_event = write_event

    @abstractmethod
    async def start(self) -> None:
        """Initialize the STT session and start streaming."""

    @abstractmethod
    async def append_audio(self, data: bytes) -> None:
        """Append a PCM audio chunk to the STT buffer."""

    @abstractmethod
    async def stop(self) -> None:
        """Flush the buffer, stop the STT session, and close resources."""

    async def __aenter__(self) -> "AbstractTranscriber":
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()


def get_transcriber(
    session_id: str,
    sample_rate: int,
    audio_path: Path,
    transcript_path: Path,
    write_event: EventWriter,
) -> Any:
    """Factory: create the appropriate transcriber based on STT_PROVIDER config."""
    from config import STT_PROVIDER

    if STT_PROVIDER == "openai":
        from openai_realtime_stt import RealtimeTranscriber

        return RealtimeTranscriber(
            session_id=session_id,
            sample_rate=sample_rate,
            transcript_path=transcript_path,
            write_event=write_event,
        )

    if STT_PROVIDER == "yandex":
        from yandex_batch_stt import YandexBatchTranscriber

        return YandexBatchTranscriber(
            session_id=session_id,
            sample_rate=sample_rate,
            audio_path=audio_path,
            transcript_path=transcript_path,
            write_event=write_event,
        )

    if STT_PROVIDER in {"yandex_realtime", "yandex-realtime"}:
        from yandex_realtime_stt import YandexRealtimeTranscriber

        return YandexRealtimeTranscriber(
            session_id=session_id,
            sample_rate=sample_rate,
            transcript_path=transcript_path,
            write_event=write_event,
        )

    raise RuntimeError(f"Unknown DICTAPHONE_STT_PROVIDER: {STT_PROVIDER}")