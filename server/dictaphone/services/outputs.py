"""STT and Telegram output orchestration.

Coordinates transcriber lifecycle and Telegram sink, consolidating the
duplicated _stt_event callback pattern that existed in both WebSocket
and HTTP paths.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable

from dictaphone.stt import get_transcriber
from protocol import DictaphoneSession

log = logging.getLogger("dictaphone.outputs")

EventWriter = Callable[[dict[str, Any]], None]
SendClientEvent = Callable[[str, Any], None]


class OutputsOrchestrator:
    """Manages STT transcriber and Telegram sink for a session."""

    def __init__(
        self,
        session: DictaphoneSession,
        *,
        send_client_event: SendClientEvent | None = None,
        audio_path: Path | None = None,
    ) -> None:
        self.session = session
        self._send_client = send_client_event
        self._audio_path = audio_path or session.audio_path
        self._transcriber: Any | None = None
        self._tg_sink: Any | None = None
        self._started = False
        self._closed = False

    async def start(self) -> None:
        """Start the Telegram sink and STT transcriber."""
        from config import STT_ENABLED, TELEGRAM_STOP_TIMEOUT_SECONDS
        from telegram_sink import TelegramSink

        if self._started:
            return
        self._started = True

        # Telegram sink
        try:
            self._tg_sink = TelegramSink(session_id=self.session.session_id)
            await self._tg_sink.start()
        except Exception as exc:
            log.warning("Telegram sink start failed: %s", exc)
            self._tg_sink = None

        # STT transcriber
        if STT_ENABLED:
            transcriber = get_transcriber(
                session_id=self.session.session_id,
                sample_rate=self.session.sample_rate,
                audio_path=self._audio_path,
                transcript_path=self.session.transcript_path,
                write_event=self._stt_event,
            )
            try:
                await asyncio.wait_for(transcriber.start(), timeout=20)
                self._transcriber = transcriber
            except Exception as exc:
                log.error("STT start failed: %s", exc)
                self._stt_event({"event": "stt_start_error", "message": str(exc)})
                if self._send_client:
                    await self._send_client("stt_start_error", message=str(exc))

    def _stt_event(self, event: dict[str, Any]) -> None:
        """Route STT events to logging, client, and Telegram sink."""
        from protocol import utc_now_iso

        event.setdefault("ts", utc_now_iso())

        # Write to events.jsonl
        from dictaphone.services.session_factory import write_event

        write_event(self.session, event)

        evt_name = event.get("event", "")

        # Send to client (WebSocket)
        if self._send_client and evt_name in {
            "transcript_delta",
            "transcript_completed",
            "stt_error",
            "stt_start_error",
        }:
            payload = {k: v for k, v in event.items() if k != "event"}
            asyncio.create_task(self._send_client(evt_name, **payload))

        # Forward to Telegram sink
        if self._tg_sink:
            if evt_name == "transcript_delta":
                asyncio.create_task(
                    self._tg_sink.on_transcript_delta(
                        event.get("delta", ""),
                        item_id=event.get("item_id"),
                    )
                )
            elif evt_name == "transcript_completed":
                asyncio.create_task(
                    self._tg_sink.on_transcript_completed(
                        event.get("transcript", ""),
                        item_id=event.get("item_id"),
                        storage_action=event.get("storage_action"),
                    )
                )

    async def append_audio(self, data: bytes) -> None:
        """Append a PCM chunk to the STT transcriber if ready."""
        if not self._transcriber or self._closed:
            return
        try:
            await self._transcriber.append_audio(data)
        except Exception as exc:
            self._stt_event({"event": "stt_append_error", "message": str(exc)[:500]})

    async def stop(self, audio_fp: Any | None = None) -> None:
        """Stop transcriber and Telegram sink, optionally flush audio."""
        if self._closed:
            return
        self._closed = True

        if self._transcriber:
            from config import STT_PROVIDER, TELEGRAM_STOP_TIMEOUT_SECONDS

            try:
                if STT_PROVIDER == "yandex":
                    await self._transcriber.stop()
                elif STT_PROVIDER in {"yandex_realtime", "yandex-realtime"}:
                    await asyncio.wait_for(self._transcriber.stop(), timeout=10)
                else:
                    await asyncio.wait_for(self._transcriber.stop(), timeout=4)
            except Exception as exc:
                self._stt_event({"event": "stt_stop_error", "message": str(exc)[:500]})
            finally:
                self._transcriber = None

        if self._tg_sink:
            try:
                await asyncio.wait_for(
                    self._tg_sink.stop(
                        transcript_path=self.session.transcript_path,
                        audio_path=self.session.audio_path,
                        sample_rate=self.session.sample_rate,
                        channels=self.session.channels,
                    ),
                    timeout=TELEGRAM_STOP_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                self._stt_event({"event": "telegram_stop_error", "message": str(exc)[:500]})
            finally:
                self._tg_sink = None

        if audio_fp:
            try:
                audio_fp.flush()
            except Exception:
                pass