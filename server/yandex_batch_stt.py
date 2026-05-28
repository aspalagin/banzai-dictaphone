"""Yandex SpeechKit batch STT for saved dictaphone PCM recordings."""
from __future__ import annotations

import asyncio
import contextlib
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import boto3
import requests
from botocore.client import Config as BotoConfig

from config import (
    env_or_file,
    YANDEX_STT_DELETE_OBJECT,
    YANDEX_STT_LANGUAGE,
    YANDEX_STT_MODEL,
    YANDEX_STT_POLL_INTERVAL_SECONDS,
    YANDEX_STT_SAMPLE_RATE,
    YANDEX_STT_TIMEOUT_SECONDS,
)

EventWriter = Callable[[dict[str, Any]], None]

_YANDEX_NETWORK_LOCK = threading.Lock()


def _is_yandex_host(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    name = str(host).rstrip(".").lower()
    return name.endswith("yandexcloud.net") or name.endswith("cloud.yandex.net")


@contextlib.contextmanager
def _force_yandex_ipv4_dns():
    original_getaddrinfo = socket.getaddrinfo

    def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        if _is_yandex_host(host) and family in (0, socket.AF_UNSPEC, socket.AF_INET6):
            try:
                return original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
            except socket.gaierror:
                pass
        return original_getaddrinfo(host, port, family, type, proto, flags)

    socket.getaddrinfo = getaddrinfo_ipv4
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo


class YandexBatchTranscriber:
    """Runs Yandex SpeechKit longRunningRecognize after audio.pcm is closed."""

    def __init__(
        self,
        *,
        session_id: str,
        sample_rate: int,
        audio_path: Path,
        transcript_path: Path,
        write_event: EventWriter,
    ) -> None:
        self.session_id = session_id
        self.sample_rate = sample_rate
        self.audio_path = audio_path
        self.transcript_path = transcript_path
        self.write_event = write_event
        self._closed = False

    async def start(self) -> None:
        self._require_config()
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg is required for Yandex STT resampling")
        self.write_event(
            {
                "event": "stt_started",
                "provider": "yandex",
                "mode": "batch_after_stop",
                "model": YANDEX_STT_MODEL,
                "language": YANDEX_STT_LANGUAGE,
                "sample_rate": self.sample_rate,
                "target_sample_rate": YANDEX_STT_SAMPLE_RATE,
            }
        )

    async def append_audio(self, data: bytes) -> None:
        return None

    async def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.write_event({"event": "yandex_stt_started", "audio_path": str(self.audio_path)})
        try:
            result = await asyncio.to_thread(self._recognize_sync)
        except Exception as exc:
            self.write_event(
                {
                    "event": "stt_error",
                    "provider": "yandex",
                    "error": {"message": str(exc)[:1000]},
                }
            )
            self.write_event({"event": "stt_stopped", "provider": "yandex"})
            return

        text = result["text"]
        if text:
            with self.transcript_path.open("a", encoding="utf-8") as fp:
                fp.write(text.rstrip() + "\n")
        self.write_event(
            {
                "event": "yandex_stt_completed",
                "operation_id": result["operation_id"],
                "chunks": result["chunks"],
                "text_chars": len(text),
                "resampled_path": result["resampled_path"],
            }
        )
        if text:
            self.write_event(
                {
                    "event": "transcript_completed",
                    "provider": "yandex",
                    "item_id": f"yandex-{self.session_id}",
                    "content_index": 0,
                    "transcript": text,
                }
            )
        self.write_event({"event": "stt_stopped", "provider": "yandex"})

    def _recognize_sync(self) -> dict[str, Any]:
        if not self.audio_path.exists() or self.audio_path.stat().st_size == 0:
            return {
                "operation_id": "",
                "chunks": 0,
                "text": "",
                "resampled_path": "",
            }

        api_key = env_or_file("YC_API_KEY")
        bucket = env_or_file("YC_S3_BUCKET")
        s3_key_id = env_or_file("YC_S3_KEY_ID")
        s3_secret_key = env_or_file("YC_S3_SECRET_KEY")

        resampled_path = self.audio_path.with_name(f"audio.yandex.{YANDEX_STT_SAMPLE_RATE}.pcm")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "s16le",
                "-ar",
                str(self.sample_rate),
                "-ac",
                "1",
                "-i",
                str(self.audio_path),
                "-f",
                "s16le",
                "-ar",
                str(YANDEX_STT_SAMPLE_RATE),
                "-ac",
                "1",
                str(resampled_path),
            ],
            check=True,
            timeout=120,
        )

        with _YANDEX_NETWORK_LOCK, _force_yandex_ipv4_dns():
            object_key = f"dictaphone/sessions/{self.session_id}/{int(time.time())}.pcm"
            s3 = boto3.client(
                "s3",
                endpoint_url="https://storage.yandexcloud.net",
                aws_access_key_id=s3_key_id,
                aws_secret_access_key=s3_secret_key,
                config=BotoConfig(
                    signature_version="s3v4",
                    connect_timeout=10,
                    read_timeout=60,
                    retries={"max_attempts": 2},
                ),
                region_name="ru-central1",
            )
            s3.upload_file(str(resampled_path), bucket, object_key)
            uri = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": object_key},
                ExpiresIn=max(600, int(YANDEX_STT_TIMEOUT_SECONDS) + 300),
            )

            operation_id = ""
            try:
                response = requests.post(
                    "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize",
                    headers={"Authorization": f"Api-Key {api_key}"},
                    json={
                        "config": {
                            "specification": {
                                "languageCode": YANDEX_STT_LANGUAGE,
                                "model": YANDEX_STT_MODEL,
                                "audioEncoding": "LINEAR16_PCM",
                                "sampleRateHertz": YANDEX_STT_SAMPLE_RATE,
                                "audioChannelCount": 1,
                            }
                        },
                        "audio": {"uri": uri},
                    },
                    timeout=(10, 30),
                )
                if response.status_code != 200:
                    raise RuntimeError(f"Yandex STT start failed {response.status_code}: {response.text[:500]}")
                operation_id = response.json().get("id") or ""
                if not operation_id:
                    raise RuntimeError(f"Yandex STT did not return operation id: {response.text[:500]}")
                self.write_event({"event": "yandex_operation_created", "operation_id": operation_id})

                deadline = time.monotonic() + YANDEX_STT_TIMEOUT_SECONDS
                operation: dict[str, Any] | None = None
                while time.monotonic() < deadline:
                    time.sleep(YANDEX_STT_POLL_INTERVAL_SECONDS)
                    poll = requests.get(
                        f"https://operation.api.cloud.yandex.net/operations/{operation_id}",
                        headers={"Authorization": f"Api-Key {api_key}"},
                        timeout=(10, 30),
                    )
                    if poll.status_code != 200:
                        raise RuntimeError(f"Yandex STT poll failed {poll.status_code}: {poll.text[:500]}")
                    data = poll.json()
                    if data.get("done"):
                        operation = data
                        break
                if operation is None:
                    raise RuntimeError(f"Yandex STT timed out: operation={operation_id}")
                if operation.get("error"):
                    raise RuntimeError(f"Yandex STT failed: {operation['error']}")

                chunks = operation.get("response", {}).get("chunks") or []
                lines: list[str] = []
                for chunk in chunks:
                    alternatives = chunk.get("alternatives") or []
                    if not alternatives:
                        continue
                    text = (alternatives[0].get("text") or "").strip()
                    if text:
                        lines.append(text)
                return {
                    "operation_id": operation_id,
                    "chunks": len(chunks),
                    "text": "\n".join(lines),
                    "resampled_path": str(resampled_path),
                }
            finally:
                if YANDEX_STT_DELETE_OBJECT and object_key:
                    try:
                        s3.delete_object(Bucket=bucket, Key=object_key)
                    except Exception:
                        pass

    def _require_config(self) -> None:
        missing = [
            name
            for name in ("YC_API_KEY", "YC_S3_BUCKET", "YC_S3_KEY_ID", "YC_S3_SECRET_KEY")
            if not env_or_file(name)
        ]
        if missing:
            raise RuntimeError("Missing Yandex STT config: " + ", ".join(missing))
