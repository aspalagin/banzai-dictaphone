#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import math
import struct
import time

import websockets


def tone_pcm(duration_seconds: float, sample_rate: int = 24000, hz: int = 440) -> bytes:
    frames = int(duration_seconds * sample_rate)
    out = bytearray()
    for i in range(frames):
        sample = int(12000 * math.sin(2 * math.pi * hz * i / sample_rate))
        out += struct.pack("<h", sample)
    return bytes(out)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8097/v1/stream")
    parser.add_argument("--token", default="")
    parser.add_argument("--duration", type=float, default=1.0)
    parser.add_argument("--sample-rate", type=int, default=24000)
    args = parser.parse_args()

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    async with websockets.connect(args.url, additional_headers=headers, max_size=2**20) as ws:
        print(await ws.recv())
        await ws.send(
            json.dumps(
                {
                    "type": "start",
                    "session_id": f"test-{int(time.time())}",
                    "device": "test-client",
                    "mode": "protocol-test",
                    "sample_rate": args.sample_rate,
                    "channels": 1,
                    "encoding": "pcm_s16le",
                },
                ensure_ascii=False,
            )
        )
        print(await ws.recv())

        data = tone_pcm(args.duration, sample_rate=args.sample_rate)
        chunk_bytes = int(args.sample_rate * 0.1 * 2)
        for offset in range(0, len(data), chunk_bytes):
            await ws.send(data[offset : offset + chunk_bytes])
            await asyncio.sleep(0.02)

        await ws.send(json.dumps({"type": "stop"}, ensure_ascii=False))
        while True:
            try:
                print(await ws.recv())
            except websockets.ConnectionClosed:
                break


if __name__ == "__main__":
    asyncio.run(main())
