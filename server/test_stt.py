#!/usr/bin/env python3
"""Тестовый клиент: шлёт PCM-файл в dictaphone server и выводит transcript."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

import websockets


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8097/v1/stream")
    parser.add_argument("--token", default=os.getenv("DICTAPHONE_TOKEN", ""))
    parser.add_argument("--pcm", default="/tmp/test_dictaphone.pcm")
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--chunk-ms", type=int, default=100, help="Размер чанка в мс")
    args = parser.parse_args()

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    chunk_bytes = int(args.sample_rate * (args.chunk_ms / 1000) * 2)  # s16le = 2 bytes/sample

    async with websockets.connect(args.url, additional_headers=headers, max_size=2**20) as ws:
        # hello
        hello = json.loads(await ws.recv())
        print(f"[server] {hello.get('event', '?')}: {hello.get('protocol', '')}")

        # start
        await ws.send(json.dumps({
            "type": "start",
            "session_id": f"test-stt-{int(time.time())}",
            "device": "test-stt-client",
            "mode": "stt-test",
            "sample_rate": args.sample_rate,
            "channels": 1,
            "encoding": "pcm_s16le",
        }))

        # Читаем ответы асинхронно
        transcript_parts = []

        async def reader():
            try:
                async for msg in ws:
                    event = json.loads(msg)
                    evt = event.get("event", event.get("type", "?"))
                    if evt == "transcript_delta":
                        delta = event.get("delta", "")
                        print(f"[delta] {delta}", end="", flush=True)
                        transcript_parts.append(delta)
                    elif evt == "transcript_completed":
                        t = event.get("transcript", "")
                        print(f"\n[completed] {t}")
                    elif evt == "stt_error":
                        print(f"\n[STT ERROR] {event.get('error', event)}")
                    elif evt == "stt_start_error":
                        print(f"\n[STT START ERROR] {event.get('message', event)}")
                    elif evt == "stopped":
                        print(f"\n[stopped]")
                        break
                    elif evt in ("started", "audio_ack"):
                        print(f"[{evt}] {event.get('session_id', '')}")
                    else:
                        print(f"[{evt}]")
            except websockets.ConnectionClosed:
                pass

        reader_task = asyncio.create_task(reader())

        # Ждём started
        await asyncio.sleep(1)

        # Шлём аудио
        with open(args.pcm, "rb") as f:
            pcm_data = f.read()

        print(f"\nОтправляю {len(pcm_data)} байт PCM ({len(pcm_data) / (args.sample_rate * 2):.1f} сек)...")

        for offset in range(0, len(pcm_data), chunk_bytes):
            chunk = pcm_data[offset:offset + chunk_bytes]
            await ws.send(chunk)
            # Имитируем реальное время
            await asyncio.sleep(args.chunk_ms / 1000 * 0.5)

        print("\nАудио отправлено, жду финальный transcript...")
        await asyncio.sleep(5)

        # stop
        await ws.send(json.dumps({"type": "stop"}))
        await asyncio.sleep(2)
        reader_task.cancel()
        try:
            await reader_task
        except asyncio.CancelledError:
            pass

        if transcript_parts:
            print(f"\n{'='*50}\nПолный текст: {''.join(transcript_parts)}")


if __name__ == "__main__":
    asyncio.run(main())
