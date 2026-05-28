"""Telegram sink: отправка live-транскрипции в группу "Разговоры".

Стратегия:
- При старте записи отправляем сообщение "🎙 Запись началась..."
- Накапливаем текст из transcript_delta, раз в FLUSH_INTERVAL_SECONDS редактируем сообщение
- Когда сообщение > MAX_MESSAGE_CHARS, фиксируем его и создаём новое
- При стопе отправляем финальный .txt файл и полную аудиозапись
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiohttp

from config import TELEGRAM_CHAT_ID, env_or_file

log = logging.getLogger("dictaphone.telegram")

BOT_TOKEN = env_or_file("TELEGRAM_BOT_TOKEN")
CHAT_ID = TELEGRAM_CHAT_ID
FLUSH_INTERVAL_SECONDS = float(env_or_file("DICTAPHONE_TG_FLUSH_INTERVAL", "2.5"))
MAX_MESSAGE_CHARS = int(env_or_file("DICTAPHONE_TG_MAX_MESSAGE_CHARS", "3800"))
SEND_AUDIO = env_or_file("DICTAPHONE_TG_SEND_AUDIO", "1") != "0"
MAX_AUDIO_BYTES = int(env_or_file("DICTAPHONE_TG_AUDIO_MAX_BYTES", str(48 * 1024 * 1024)))
AUDIO_BITRATE = env_or_file("DICTAPHONE_TG_AUDIO_BITRATE", "32k")
AUDIO_PREP_TIMEOUT_SECONDS = float(env_or_file("DICTAPHONE_TG_AUDIO_PREP_TIMEOUT_SECONDS", "90"))
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


class TelegramSink:
    """Отправляет live-транскрипцию в Telegram-группу."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._http: aiohttp.ClientSession | None = None
        self._current_message_id: int | None = None
        self._current_text: str = ""
        self._pending_deltas: list[str] = []
        self._delta_item_ids: set[str] = set()
        self._flush_task: asyncio.Task | None = None
        self._stopped = False
        self._header: str = ""

    async def start(self) -> None:
        if not BOT_TOKEN:
            log.warning("TELEGRAM_BOT_TOKEN не настроен, Telegram sink отключён")
            return

        self._http = aiohttp.ClientSession()
        now = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M МСК")
        self._header = f"🎙 Запись началась: {now}\n\n"

        msg = await self._send_message(self._header + "⏳ Ожидание речи...")
        if msg:
            self._current_message_id = msg.get("message_id")
            self._current_text = ""
            log.info("Telegram: стартовое сообщение %s в чат %s", self._current_message_id, CHAT_ID)

        self._flush_task = asyncio.create_task(self._flush_loop(), name=f"tg-flush-{self.session_id}")

    async def on_transcript_delta(self, delta: str, item_id: str | None = None) -> None:
        """Вызывается при каждом transcript_delta."""
        if not self._http or self._stopped:
            return
        if item_id:
            self._delta_item_ids.add(item_id)
        self._pending_deltas.append(delta)

    async def on_transcript_completed(self, transcript: str, item_id: str | None = None) -> None:
        """Вызывается при transcript_completed (финальный текст utterance)."""
        if not self._http or self._stopped:
            return
        if item_id and item_id in self._delta_item_ids:
            if not (self._current_text + "".join(self._pending_deltas)).endswith("\n"):
                self._pending_deltas.append("\n")
            return
        clean = transcript.strip()
        if clean:
            self._pending_deltas.append(clean + "\n")

    async def stop(
        self,
        transcript_path: Path | None = None,
        audio_path: Path | None = None,
        sample_rate: int = 24000,
        channels: int = 1,
    ) -> None:
        """Остановить sink, отправить финальные файлы."""
        self._stopped = True
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Финальный flush
        await self._flush_now()

        # Отправить финальное сообщение
        if self._http:
            now = datetime.now(timezone(timedelta(hours=3))).strftime("%H:%M МСК")
            await self._send_message(f"✅ Запись завершена: {now}")

            # Отправить .txt файл если есть
            if transcript_path and transcript_path.exists() and transcript_path.stat().st_size > 0:
                await self._send_document(transcript_path, caption=f"📝 Транскрипт: {self.session_id}")

            if SEND_AUDIO and audio_path and audio_path.exists() and audio_path.stat().st_size > 0:
                prepared_audio = await self._prepare_audio_file(audio_path, sample_rate, channels)
                if prepared_audio:
                    await self._send_document(prepared_audio, caption=f"🎧 Аудиозапись: {self.session_id}")

            await self._http.close()
            self._http = None

    async def _flush_loop(self) -> None:
        """Периодически обновляет текущее сообщение в Telegram."""
        try:
            while not self._stopped:
                await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
                await self._flush_now()
        except asyncio.CancelledError:
            pass

    async def _flush_now(self) -> None:
        """Применить pending_deltas к текущему сообщению."""
        if not self._pending_deltas or not self._http:
            return

        new_text = "".join(self._pending_deltas)
        self._pending_deltas.clear()

        self._current_text += new_text

        # Проверяем лимит длины
        if len(self._current_text) > MAX_MESSAGE_CHARS:
            # Текущее сообщение оставляем как есть, начинаем новое
            overflow = self._current_text[MAX_MESSAGE_CHARS:]
            self._current_text = self._current_text[:MAX_MESSAGE_CHARS]

            # Обновляем текущее
            await self._edit_current()

            # Создаём новое сообщение для продолжения
            self._current_text = overflow
            msg = await self._send_message(self._current_text)
            if msg:
                self._current_message_id = msg.get("message_id")
        else:
            await self._edit_current()

    async def _edit_current(self) -> None:
        """Редактировать текущее сообщение."""
        if not self._current_message_id or not self._http:
            return

        display_text = self._header + self._current_text if self._current_text else self._header + "⏳ Ожидание речи..."

        try:
            async with self._http.post(
                f"{API_BASE}/editMessageText",
                json={
                    "chat_id": CHAT_ID,
                    "message_id": self._current_message_id,
                    "text": display_text[:4096],
                },
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    # "message is not modified" - не ошибка
                    if "message is not modified" not in body:
                        log.warning("Telegram editMessageText %s: %s", resp.status, body[:200])
        except Exception as exc:
            log.warning("Telegram edit failed: %s", exc)

    async def _send_message(self, text: str) -> dict[str, Any] | None:
        """Отправить новое сообщение."""
        if not self._http:
            return None
        try:
            async with self._http.post(
                f"{API_BASE}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": text[:4096],
                },
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("result", {})
                else:
                    body = await resp.text()
                    log.warning("Telegram sendMessage %s: %s", resp.status, body[:200])
                    return None
        except Exception as exc:
            log.warning("Telegram send failed: %s", exc)
            return None

    async def _prepare_audio_file(self, audio_path: Path, sample_rate: int, channels: int) -> Path | None:
        """Сделать из raw PCM удобный аудиофайл для Telegram."""
        ogg_path = audio_path.with_suffix(".ogg")
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            command = [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "s16le",
                "-ar",
                str(sample_rate),
                "-ac",
                str(channels),
                "-i",
                str(audio_path),
                "-c:a",
                "libopus",
                "-b:a",
                AUDIO_BITRATE,
                "-vbr",
                "on",
                str(ogg_path),
            ]
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=AUDIO_PREP_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                log.warning("Telegram audio prepare timeout: %s", audio_path)
            else:
                if proc.returncode == 0 and ogg_path.exists() and ogg_path.stat().st_size > 0:
                    log.info("Telegram: аудио подготовлено %s", ogg_path.name)
                    return ogg_path
                log.warning("Telegram audio ffmpeg failed: %s", stderr.decode("utf-8", "replace")[:500])

        wav_path = audio_path.with_suffix(".wav")
        try:
            await asyncio.to_thread(self._write_wav_file, audio_path, wav_path, sample_rate, channels)
            if wav_path.exists() and wav_path.stat().st_size > 0:
                log.info("Telegram: аудио подготовлено %s", wav_path.name)
                return wav_path
        except Exception as exc:
            log.warning("Telegram wav fallback failed: %s", exc)
        return None

    def _write_wav_file(self, audio_path: Path, wav_path: Path, sample_rate: int, channels: int) -> None:
        with audio_path.open("rb") as source, wave.open(str(wav_path), "wb") as target:
            target.setnchannels(max(1, channels))
            target.setsampwidth(2)
            target.setframerate(sample_rate)
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                target.writeframes(chunk)

    async def _send_document(self, path: Path, caption: str) -> None:
        """Отправить файл в группу."""
        if not self._http:
            return
        size = path.stat().st_size if path.exists() else 0
        if size <= 0:
            return
        if size > MAX_AUDIO_BYTES:
            size_mb = size / 1024 / 1024
            limit_mb = MAX_AUDIO_BYTES / 1024 / 1024
            log.warning("Telegram file too large: %s %.1f MB > %.1f MB", path.name, size_mb, limit_mb)
            await self._send_message(f"⚠️ Файл слишком большой для Telegram: {path.name}, {size_mb:.1f} МБ")
            return
        try:
            with path.open("rb") as fp:
                data = aiohttp.FormData()
                data.add_field("chat_id", str(CHAT_ID))
                data.add_field("document", fp, filename=path.name)
                data.add_field("caption", caption)

                async with self._http.post(f"{API_BASE}/sendDocument", data=data) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        log.warning("Telegram sendDocument %s: %s", resp.status, body[:200])
                    else:
                        log.info("Telegram: файл %s отправлен", path.name)
        except Exception as exc:
            log.warning("Telegram sendDocument failed: %s", exc)
