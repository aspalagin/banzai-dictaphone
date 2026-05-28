"""OpenAI Realtime Transcription API клиент для dictaphone.

Подключается к wss://api.openai.com/v1/realtime?model=gpt-realtime-whisper&intent=transcription
через Codex OAuth токен. Стримит PCM-аудио, получает transcript delta/completed события.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import websockets

from config import (
    env_or_file,
    OPENAI_REALTIME_URL,
    OPENAI_REFRESH_SCRIPT,
    OPENAI_STT_LANGUAGE,
    OPENAI_STT_MODEL,
    OPENAI_TOKEN_FILE,
    STT_COMMIT_INTERVAL_SECONDS,
)

log = logging.getLogger("dictaphone.openai_stt")

EventWriter = Callable[[dict[str, Any]], None]


def get_openai_token() -> str:
    """Получить access token: сначала из файла, потом через refresh скрипт."""
    try:
        token = OPENAI_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if len(token) > 100:
            return token
    except OSError:
        pass

    if OPENAI_REFRESH_SCRIPT and Path(OPENAI_REFRESH_SCRIPT).exists():
        subprocess.run([OPENAI_REFRESH_SCRIPT], check=True, timeout=15)
        token = OPENAI_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if len(token) > 100:
            return token

    return env_or_file("OPENAI_API_KEY")


class RealtimeTranscriber:
    """Стримит PCM-аудио в OpenAI Realtime Transcription API, отдаёт delta/completed."""

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
        self.ws: websockets.WebSocketClientProtocol | None = None
        self._listen_task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._closed = False
        self._pending_delta: list[str] = []
        self._bytes_since_commit = 0
        self._full_transcript: list[str] = []
        self._send_lock = asyncio.Lock()
        self._start_error: str | None = None

    async def start(self) -> None:
        token = get_openai_token()
        if not token:
            raise RuntimeError("OpenAI token is not configured")

        # Для transcription-сессий модель НЕ передаётся в URL, только intent
        url = f"{OPENAI_REALTIME_URL}?intent=transcription"
        log.info("Подключаюсь к OpenAI Realtime: %s", url)

        self.ws = await websockets.connect(
            url,
            additional_headers={
                "Authorization": f"Bearer {token}",
                "OpenAI-Safety-Identifier": f"arseniy-dictaphone-{self.session_id}",
            },
            max_size=2**24,
            ping_interval=20,
        )
        self._listen_task = asyncio.create_task(self._listen(), name=f"stt-listen-{self.session_id}")

        # Ждём session.created, потом шлём session.update
        # _listen() установит _ready после session.updated
        await self._send_session_update()

        try:
            await asyncio.wait_for(self._ready.wait(), timeout=15)
        except asyncio.TimeoutError:
            raise RuntimeError("OpenAI Realtime session.updated не получен за 15 сек")
        if self._start_error:
            raise RuntimeError(self._start_error)

        self.write_event(
            {
                "event": "stt_started",
                "model": OPENAI_STT_MODEL,
                "language": OPENAI_STT_LANGUAGE,
                "sample_rate": self.sample_rate,
            }
        )

    async def _send_session_update(self) -> None:
        """Конфигурируем transcription session по документации OpenAI."""
        await self._send(
            {
                "type": "session.update",
                "session": {
                    "type": "transcription",
                    "audio": {
                        "input": {
                            "format": {
                                "type": "audio/pcm",
                                "rate": self.sample_rate,
                            },
                            "transcription": {
                                "model": OPENAI_STT_MODEL,
                                "language": OPENAI_STT_LANGUAGE,
                            },
                            # turn_detection не поддерживается gpt-realtime-whisper,
                            # используем ручной commit по таймеру (STT_COMMIT_INTERVAL_SECONDS)
                        }
                    },
                },
            }
        )

    async def append_audio(self, data: bytes) -> None:
        """Отправить PCM-чанк в OpenAI Realtime, периодически делать commit."""
        if self._closed or not self.ws:
            return
        async with self._send_lock:
            if self._closed or not self.ws:
                return
            await self._send(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(data).decode("ascii"),
                }
            )
            self._bytes_since_commit += len(data)
            # Делаем commit каждые STT_COMMIT_INTERVAL_SECONDS секунд аудио
            if self._bytes_since_commit >= self._commit_threshold_bytes:
                await self._commit()

    async def _commit(self) -> None:
        """Зафиксировать буфер - запустить транскрибацию."""
        if self._bytes_since_commit < self._minimum_commit_bytes:
            return
        try:
            await self._send({"type": "input_audio_buffer.commit"})
            log.debug("STT commit: %d bytes", self._bytes_since_commit)
            self._bytes_since_commit = 0
        except Exception as exc:
            log.warning("STT commit failed: %s", exc)

    @property
    def _commit_threshold_bytes(self) -> int:
        # Порог = STT_COMMIT_INTERVAL_SECONDS секунд аудио
        return max(self._minimum_commit_bytes, int(self.sample_rate * STT_COMMIT_INTERVAL_SECONDS * 2))

    @property
    def _minimum_commit_bytes(self) -> int:
        # Минимум 0.5 сек аудио перед commit
        return int(self.sample_rate * 0.5 * 2)

    async def stop(self) -> None:
        """Остановить transcriber, закрыть WebSocket."""
        if self._closed:
            return
        self._closed = True

        # Финальный commit остатка буфера
        try:
            if self.ws and self._bytes_since_commit >= self._minimum_commit_bytes:
                await self._commit()
        except Exception:
            pass

        # Дадим время получить оставшиеся события
        await asyncio.sleep(1.5)

        try:
            if self.ws:
                await self.ws.close()
        except Exception:
            pass
        finally:
            if self._listen_task:
                await asyncio.gather(self._listen_task, return_exceptions=True)
            self._flush_pending_delta()
            self.write_event({"event": "stt_stopped"})

    async def _send(self, payload: dict[str, Any]) -> None:
        if not self.ws:
            raise RuntimeError("STT WebSocket is not connected")
        await self.ws.send(json.dumps(payload, ensure_ascii=False))

    async def _listen(self) -> None:
        assert self.ws is not None
        try:
            async for message in self.ws:
                event = json.loads(message)
                await self._handle_event(event)
        except websockets.ConnectionClosed:
            if not self._closed:
                log.warning("STT WebSocket closed unexpectedly")
                self.write_event({"event": "stt_disconnected"})
        except Exception as exc:
            if not self._closed:
                log.exception("STT listener failed: %s", exc)
                self.write_event({"event": "stt_listener_error", "message": str(exc)})

    async def _handle_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type", "")

        # session.created - сервер подтверждает подключение
        if event_type == "session.created":
            log.info("Realtime session created: %s", event.get("session", {}).get("id", "?"))
            return

        # session.updated - сервер подтверждает нашу конфигурацию
        if event_type == "session.updated":
            self._ready.set()
            self.write_event({"event": "stt_session_updated"})
            return

        # Ошибка от OpenAI
        if event_type == "error":
            self._ready.set()  # разблокируем ожидание, чтобы не зависнуть
            error_info = event.get("error", event)
            code = str(error_info.get("code") or "")
            message = str(error_info.get("message") or error_info)
            self._start_error = f"{code}: {message}" if code else message
            log.error("STT error from OpenAI: %s", error_info)
            self.write_event(
                {
                    "event": "stt_error",
                    "error": error_info,
                }
            )
            if code in {"token_invalidated", "invalid_api_key", "insufficient_quota"}:
                self._closed = True
                try:
                    if self.ws:
                        await self.ws.close()
                except Exception:
                    pass
            return

        # Частичный текст (delta)
        if event_type == "conversation.item.input_audio_transcription.delta":
            delta = event.get("delta") or ""
            if delta:
                self._pending_delta.append(delta)
                self.write_event(
                    {
                        "event": "transcript_delta",
                        "item_id": event.get("item_id"),
                        "content_index": event.get("content_index"),
                        "delta": delta,
                    }
                )
            return

        # Финальный текст для одного utterance
        if event_type == "conversation.item.input_audio_transcription.completed":
            transcript = event.get("transcript") or ""
            self._flush_pending_delta()
            if transcript:
                self._full_transcript.append(transcript.strip())
                with self.transcript_path.open("a", encoding="utf-8") as fp:
                    fp.write(transcript.strip() + "\n")
                self.write_event(
                    {
                        "event": "transcript_completed",
                        "item_id": event.get("item_id"),
                        "content_index": event.get("content_index"),
                        "transcript": transcript,
                    }
                )
            return

        # VAD и буфер-события - логируем для отладки
        if event_type in {
            "input_audio_buffer.speech_started",
            "input_audio_buffer.speech_stopped",
            "input_audio_buffer.committed",
            "conversation.item.created",
        }:
            self.write_event({"event": "stt_signal", "type": event_type})
            return

        # rate_limits - игнорируем тихо
        if "rate_limits" in event_type:
            return

        # Неизвестные события - логируем
        log.debug("Unhandled realtime event: %s", event_type)

    def _flush_pending_delta(self) -> None:
        if not self._pending_delta:
            return
        text = "".join(self._pending_delta).strip()
        self._pending_delta.clear()
        if not text:
            return
        live_path = self.transcript_path.with_suffix(".live.txt")
        with live_path.open("a", encoding="utf-8") as fp:
            fp.write(text + "\n")

    def get_full_transcript(self) -> str:
        """Вернуть весь накопленный transcript."""
        return "\n".join(self._full_transcript)
