#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


ENV_PATH = Path(os.getenv("DICTAPHONE_ENV_FILE", ".env"))


def load_env_file() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


def post(base_url: str, path: str, body: bytes, token: str, content_type: str, timeout: float) -> dict:
    url = base_url.rstrip("/") + path
    command = [
        "curl",
        "-sS",
        "--ipv4",
        "--max-time",
        str(timeout),
        "-H",
        f"Authorization: Bearer {token}",
        "-H",
        f"Content-Type: {content_type}",
        "-H",
        f"Content-Length: {len(body)}",
        "-H",
        "Connection: close",
        "--data-binary",
        "@-",
        "-w",
        "\n__META__%{http_code} %{time_total}",
        url,
    ]
    started = time.monotonic()
    completed = subprocess.run(command, input=body, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    output = completed.stdout
    marker = b"\n__META__"
    if marker in output:
        data, meta = output.rsplit(marker, 1)
        parts = meta.decode("utf-8", "replace").strip().split()
        code = int(parts[0]) if parts else 0
    else:
        data = output
        code = 0
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", "replace").strip() or "curl завершился с ошибкой")
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception:
        payload = {"raw": data.decode("utf-8", "replace")}
    payload["_code"] = code
    payload["_elapsed_ms"] = elapsed_ms
    return payload


def get(base_url: str, path: str, token: str, timeout: float) -> dict:
    url = base_url.rstrip("/") + path
    command = [
        "curl",
        "-sS",
        "--ipv4",
        "--max-time",
        str(timeout),
        "-H",
        f"Authorization: Bearer {token}",
        "-H",
        "Connection: close",
        "-w",
        "\n__META__%{http_code} %{time_total}",
        url,
    ]
    started = time.monotonic()
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    output = completed.stdout
    marker = b"\n__META__"
    if marker in output:
        data, meta = output.rsplit(marker, 1)
        parts = meta.decode("utf-8", "replace").strip().split()
        code = int(parts[0]) if parts else 0
    else:
        data = output
        code = 0
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", "replace").strip() or "curl завершился с ошибкой")
    payload = json.loads(data.decode("utf-8"))
    payload["_code"] = code
    payload["_elapsed_ms"] = elapsed_ms
    return payload


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="Проверка HTTP-пути диктофона")
    parser.add_argument("--base-url", required=True, help="Базовый URL сервера")
    parser.add_argument("--token", default=os.getenv("DICTAPHONE_TOKEN", ""), help="Токен диктофона")
    parser.add_argument("--chunks", type=int, default=None, help="Сколько чанков отправить")
    parser.add_argument("--chunk-bytes", type=int, default=2400, help="Размер чанка в байтах")
    parser.add_argument("--audio-file", type=Path, help="PCM-файл, который нужно отправить вместо синтетического аудио")
    parser.add_argument("--wait-transcript", type=float, default=0, help="Сколько секунд ждать появления transcript.txt")
    parser.add_argument("--chunk-delay", type=float, default=0, help="Пауза между чанками, секунды")
    parser.add_argument("--timeout", type=float, default=8.0, help="Таймаут запроса в секундах")
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("Нет DICTAPHONE_TOKEN: передай --token или заполни .env")

    session_id = f"smoke-{int(time.time())}"
    start_body = json.dumps(
        {
            "type": "start",
            "session_id": session_id,
            "device": "smoke",
            "mode": "dictation",
            "sample_rate": 24000,
            "channels": 1,
            "encoding": "pcm_s16le",
            "client_version": "http-smoke-v26",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    start = post(args.base_url, "/v1/http/start", start_body, args.token, "application/json; charset=utf-8", args.timeout)
    print("Старт:", json.dumps(start, ensure_ascii=False), flush=True)
    if not start.get("ok"):
        raise SystemExit(2)
    sid = start.get("session_id", session_id)

    sent_bytes = 0
    sent_chunks = 0
    if args.audio_file:
        with args.audio_file.open("rb") as fp:
            while True:
                if args.chunks is not None and sent_chunks >= args.chunks:
                    break
                audio = fp.read(args.chunk_bytes)
                if not audio:
                    break
                result = post(args.base_url, f"/v1/http/audio/{sid}", audio, args.token, "application/octet-stream", args.timeout)
                sent_chunks += 1
                sent_bytes += len(audio)
                print(f"Чанк {sent_chunks}:", json.dumps(result, ensure_ascii=False), flush=True)
                if not result.get("ok"):
                    raise SystemExit(3)
                if args.chunk_delay > 0:
                    time.sleep(args.chunk_delay)
    else:
        total_chunks = args.chunks if args.chunks is not None else 5
        audio = bytes((i % 251 for i in range(args.chunk_bytes)))
        for index in range(total_chunks):
            result = post(args.base_url, f"/v1/http/audio/{sid}", audio, args.token, "application/octet-stream", args.timeout)
            sent_chunks += 1
            sent_bytes += len(audio)
            print(f"Чанк {index + 1}:", json.dumps(result, ensure_ascii=False), flush=True)
            if not result.get("ok"):
                raise SystemExit(3)
            if args.chunk_delay > 0:
                time.sleep(args.chunk_delay)

    stop = post(args.base_url, f"/v1/http/stop/{sid}", b"", args.token, "application/octet-stream", args.timeout)
    print("Стоп:", json.dumps(stop, ensure_ascii=False), flush=True)
    if not stop.get("ok"):
        raise SystemExit(4)

    received = int(stop.get("bytes_received") or 0)
    if received < sent_bytes:
        raise SystemExit(f"Получено меньше байт, чем ожидалось: {received} < {sent_bytes}")
    print(f"Готово: {received} байт, чанков: {stop.get('chunks_received')}", flush=True)

    if args.wait_transcript > 0:
        deadline = time.monotonic() + args.wait_transcript
        while time.monotonic() < deadline:
            status = get(args.base_url, f"/v1/http/status/{sid}", args.token, args.timeout)
            print("Статус:", json.dumps(status, ensure_ascii=False), flush=True)
            if status.get("transcript_exists"):
                print("Транскрипт готов:", status.get("transcript_path"), flush=True)
                break
            time.sleep(5)
        else:
            raise SystemExit("transcript.txt не появился за отведённое время")


if __name__ == "__main__":
    main()
