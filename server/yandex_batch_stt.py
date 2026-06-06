"""Yandex SpeechKit batch STT for saved dictaphone PCM recordings."""
from __future__ import annotations

import asyncio
import contextlib
import json
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
    YANDEX_STT_TIMEOUT_SECONDS,
)

EventWriter = Callable[[dict[str, Any]], None]

_YANDEX_NETWORK_LOCK = threading.Lock()
_STT_START_URL = "https://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync"
_STT_RESULT_URL = "https://stt.api.cloud.yandex.net/stt/v3/getRecognition"
_OPS_URL = "https://operation.api.cloud.yandex.net/operations"


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
    """Runs Yandex SpeechKit v3 after audio.pcm is closed."""

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
            raise RuntimeError("ffmpeg is required for Yandex STT audio encoding")
        self.write_event(
            {
                "event": "stt_started",
                "provider": "yandex",
                "mode": "batch_after_stop_v3",
                "model": YANDEX_STT_MODEL,
                "language": YANDEX_STT_LANGUAGE,
                "sample_rate": self.sample_rate,
                "container_format": "OGG_OPUS",
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
                "processed_path": result["processed_path"],
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
                "processed_path": "",
            }

        api_key = env_or_file("YC_API_KEY")
        bucket = env_or_file("YC_S3_BUCKET")
        s3_key_id = env_or_file("YC_S3_KEY_ID")
        s3_secret_key = env_or_file("YC_S3_SECRET_KEY")

        processed_path = self.audio_path.with_name("audio.yandex.v3.ogg")
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
                "-acodec",
                "libopus",
                "-ar",
                "48000",
                "-ac",
                "1",
                str(processed_path),
            ],
            check=True,
            timeout=120,
        )

        with _YANDEX_NETWORK_LOCK, _force_yandex_ipv4_dns():
            object_key = f"dictaphone/sessions/{self.session_id}/{int(time.time())}.ogg"
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
            s3.upload_file(str(processed_path), bucket, object_key)
            uri = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": object_key},
                ExpiresIn=max(600, int(YANDEX_STT_TIMEOUT_SECONDS) + 300),
            )

            operation_id = ""
            try:
                response = requests.post(
                    _STT_START_URL,
                    headers={"Authorization": f"Api-Key {api_key}"},
                    json={
                        "uri": uri,
                        "recognitionModel": {
                            "model": YANDEX_STT_MODEL,
                            "audioFormat": {
                                "containerAudio": {
                                    "containerAudioType": "OGG_OPUS",
                                }
                            },
                            "textNormalization": {
                                "textNormalization": "TEXT_NORMALIZATION_ENABLED",
                                "profanityFilter": False,
                                "literatureText": True,
                                "phoneFormattingMode": "PHONE_FORMATTING_MODE_DISABLED",
                            },
                            "languageRestriction": {
                                "restrictionType": "WHITELIST",
                                "languageCode": [YANDEX_STT_LANGUAGE],
                            },
                            "audioProcessingType": "FULL_DATA",
                        },
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
                        f"{_OPS_URL}/{operation_id}",
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

                result = requests.get(
                    _STT_RESULT_URL,
                    params={"operation_id": operation_id},
                    headers={"Authorization": f"Api-Key {api_key}"},
                    timeout=(10, 60),
                )
                if result.status_code != 200:
                    raise RuntimeError(f"Yandex STT result failed {result.status_code}: {result.text[:500]}")

                lines = _extract_v3_lines(result.text)
                return {
                    "operation_id": operation_id,
                    "chunks": len(lines),
                    "text": "\n".join(lines),
                    "processed_path": str(processed_path),
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


def _extract_v3_lines(ndjson_text: str) -> list[str]:
    refined: list[str] = []
    fallback: list[str] = []
    for line in ndjson_text.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        result = obj.get("result") or {}
        refinement = result.get("finalRefinement") or {}
        normalized = refinement.get("normalizedText") or {}
        alternatives = normalized.get("alternatives") or []
        if alternatives:
            text = (alternatives[0].get("text") or "").strip()
            if text:
                refined.append(text)
            continue

        final = result.get("final") or {}
        alternatives = final.get("alternatives") or []
        if alternatives:
            text = (alternatives[0].get("text") or "").strip()
            if text:
                fallback.append(text)

    lines = refined or fallback
    deduped: list[str] = []
    previous = ""
    for text in lines:
        if text != previous:
            deduped.append(text)
        previous = text
    return deduped
