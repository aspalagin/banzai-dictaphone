"""Yandex AI Studio Realtime STT client for saved dictaphone sessions."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiohttp

from config import (
    YANDEX_REALTIME_API_KEY,
    YANDEX_REALTIME_FOLDER_ID,
    YANDEX_REALTIME_LANGUAGE,
    YANDEX_REALTIME_MODEL,
    YANDEX_REALTIME_SILENCE_MS,
    YANDEX_REALTIME_STOP_GRACE_SECONDS,
    YANDEX_REALTIME_URL,
    YANDEX_REALTIME_VOICE,
)
from transcript_merge import merge_transcript_line

log = logging.getLogger("dictaphone.yandex_realtime")
EventWriter = Callable[[dict[str, Any]], None]


class YandexRealtimeTranscriber:
    """Streams PCM audio to Yandex AI Studio Realtime over WebSocket."""

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
        self.http_session: aiohttp.ClientSession | None = None
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self._listen_task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._closed = False
        self._send_lock = asyncio.Lock()
        self._start_error: str | None = None
        self._full_transcript: list[str] = []

    async def start(self) -> None:
        if not YANDEX_REALTIME_FOLDER_ID:
            raise RuntimeError("YC_FOLDER_ID is not configured")
        if not YANDEX_REALTIME_API_KEY:
            raise RuntimeError("YC_API_KEY is not configured")

        model_uri = f"gpt://{YANDEX_REALTIME_FOLDER_ID}/{YANDEX_REALTIME_MODEL}"
        url = f"{YANDEX_REALTIME_URL}?model={model_uri}"
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        self.http_session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=None, connect=10, sock_connect=10, sock_read=60),
        )
        self.ws = await self.http_session.ws_connect(
            url,
            headers={"Authorization": f"Api-Key {YANDEX_REALTIME_API_KEY}"},
            heartbeat=20.0,
            max_msg_size=2**24,
        )
        self._listen_task = asyncio.create_task(self._listen(), name=f"yandex-realtime-{self.session_id}")
        await self._send_session_update()

        try:
            await asyncio.wait_for(self._ready.wait(), timeout=15)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Yandex Realtime session.updated не получен за 15 сек") from exc
        if self._start_error:
            raise RuntimeError(self._start_error)

        self.write_event(
            {
                "event": "stt_started",
                "provider": "yandex_realtime",
                "model": YANDEX_REALTIME_MODEL,
                "language": YANDEX_REALTIME_LANGUAGE,
                "sample_rate": self.sample_rate,
            }
        )

    async def _send_session_update(self) -> None:
        await self._send(
            {
                "type": "session.update",
                "session": {
                    "instructions": (
                        "Ты только расшифровываешь входящую русскую речь. "
                        "Не отвечай на смысл и не добавляй пояснения."
                    ),
                    "output_modalities": ["text"],
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": self.sample_rate},
                            "languages": [YANDEX_REALTIME_LANGUAGE],
                            "turn_detection": {
                                "type": "server_vad",
                                "threshold": 0.5,
                                "silence_duration_ms": YANDEX_REALTIME_SILENCE_MS,
                            },
                        },
                        "output": {
                            "format": {"type": "audio/pcm", "rate": self.sample_rate},
                            "voice": YANDEX_REALTIME_VOICE,
                        },
                    },
                },
            }
        )

    async def append_audio(self, data: bytes) -> None:
        if self._closed or not data:
            return
        async with self._send_lock:
            if self._closed:
                return
            await self._send(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(data).decode("ascii"),
                }
            )

    async def stop(self) -> None:
        if self._closed:
            return

        try:
            silence = b"\x00" * max(0, int(self.sample_rate * 2 * YANDEX_REALTIME_SILENCE_MS / 1000))
            if silence:
                await self.append_audio(silence)
            async with self._send_lock:
                await self._send({"type": "input_audio_buffer.commit"})
        except Exception as exc:
            self.write_event({"event": "stt_commit_error", "provider": "yandex_realtime", "message": str(exc)[:500]})

        await asyncio.sleep(YANDEX_REALTIME_STOP_GRACE_SECONDS)
        self._closed = True

        try:
            if self.ws:
                await self.ws.close()
        except Exception:
            pass
        finally:
            if self._listen_task:
                await asyncio.gather(self._listen_task, return_exceptions=True)
            if self.http_session:
                await self.http_session.close()
            self.write_event({"event": "stt_stopped", "provider": "yandex_realtime"})

    async def _send(self, payload: dict[str, Any]) -> None:
        if not self.ws:
            raise RuntimeError("Yandex Realtime WebSocket is not connected")
        await self.ws.send_str(json.dumps(payload, ensure_ascii=False))

    async def _listen(self) -> None:
        assert self.ws is not None
        try:
            async for msg in self.ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                event = json.loads(msg.data)
                await self._handle_event(event)
        except Exception as exc:
            if not self._closed:
                log.exception("Yandex Realtime listener failed: %s", exc)
                self.write_event(
                    {
                        "event": "stt_listener_error",
                        "provider": "yandex_realtime",
                        "message": str(exc)[:500],
                    }
                )

    async def _handle_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")

        if event_type == "session.created":
            session = event.get("session") or {}
            self.write_event(
                {
                    "event": "stt_session_created",
                    "provider": "yandex_realtime",
                    "session_id": session.get("id"),
                    "model": session.get("model"),
                }
            )
            return

        if event_type == "session.updated":
            self._ready.set()
            session = event.get("session") or {}
            self.write_event(
                {
                    "event": "stt_session_updated",
                    "provider": "yandex_realtime",
                    "session_id": session.get("id"),
                    "model": session.get("model"),
                }
            )
            return

        if event_type == "error":
            self._ready.set()
            error_info = event.get("error", event)
            message = json.dumps(error_info, ensure_ascii=False)[:1000]
            self._start_error = message
            self.write_event(
                {
                    "event": "stt_error",
                    "provider": "yandex_realtime",
                    "error": error_info,
                }
            )
            return

        if event_type == "conversation.item.input_audio_transcription.delta":
            delta = str(event.get("delta") or "")
            if delta:
                self.write_event(
                    {
                        "event": "transcript_delta",
                        "provider": "yandex_realtime",
                        "item_id": event.get("item_id"),
                        "content_index": event.get("content_index"),
                        "delta": delta,
                    }
                )
            return

        if event_type == "conversation.item.input_audio_transcription.completed":
            transcript = str(event.get("transcript") or "").strip()
            if transcript:
                action = self._store_transcript(transcript)
                self.write_event(
                    {
                        "event": "transcript_completed",
                        "provider": "yandex_realtime",
                        "item_id": event.get("item_id"),
                        "content_index": event.get("content_index"),
                        "transcript": transcript,
                        "storage_action": action,
                    }
                )
            return

        if event_type in {
            "input_audio_buffer.speech_started",
            "input_audio_buffer.speech_stopped",
            "input_audio_buffer.committed",
            "conversation.item.created",
            "response.done",
        }:
            self.write_event({"event": "stt_signal", "provider": "yandex_realtime", "type": event_type})
            return

        if event_type.startswith("response."):
            return

        log.debug("Unhandled Yandex Realtime event: %s", event_type)

    def _store_transcript(self, transcript: str) -> str:
        action = merge_transcript_line(self._full_transcript, transcript)
        if action not in {"empty", "duplicate", "covered_by_previous"}:
            self._rewrite_transcript_file()
        return action

    def _rewrite_transcript_file(self) -> None:
        text = "\n".join(line for line in self._full_transcript if line.strip())
        with self.transcript_path.open("w", encoding="utf-8") as fp:
            if text:
                fp.write(text.rstrip() + "\n")
