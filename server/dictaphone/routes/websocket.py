"""WebSocket streaming endpoint."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

from aiohttp import WSMsgType, web

from dictaphone.services.outputs import OutputsOrchestrator
from dictaphone.services.session_factory import create_session, write_event
from protocol import DictaphoneSession, utc_now_iso

log = logging.getLogger("dictaphone.ws")

MAX_AUDIO_MESSAGE_BYTES = 262144  # mirrors config default


def _send(ws: web.WebSocketResponse, event: str, **payload: Any) -> None:
    payload["event"] = event
    payload.setdefault("ts", utc_now_iso())
    asyncio.create_task(ws.send_str(json.dumps(payload, ensure_ascii=False)))


async def stream_ws(request: web.Request) -> web.WebSocketResponse:
    from config import ALLOW_INSECURE, MAX_AUDIO_MESSAGE_BYTES, TOKEN

    if not _check_token(request):
        raise web.HTTPUnauthorized(text="missing or invalid DICTAPHONE_TOKEN")

    ws = web.WebSocketResponse(heartbeat=None, max_msg_size=MAX_AUDIO_MESSAGE_BYTES)
    await ws.prepare(request)
    await _send(ws, "hello", protocol="banzai-dictaphone.v1")

    session: DictaphoneSession | None = None
    audio_fp = None
    orchestrator: OutputsOrchestrator | None = None

    async def send_client_event(event: str, **payload: Any) -> None:
        await ws.send_str(json.dumps({**payload, "event": event, "ts": utc_now_iso()}, ensure_ascii=False))

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError as exc:
                    await _send(ws, "error", code="bad_json", message=str(exc))
                    continue

                command = payload.get("type") or payload.get("command")

                if command == "start":
                    if session is not None:
                        await _send(ws, "error", code="already_started")
                        continue

                    session = create_session(payload)
                    audio_fp = session.audio_path.open("ab")

                    orchestrator = OutputsOrchestrator(
                        session,
                        send_client_event=send_client_event,
                    )
                    await orchestrator.start()

                    await _send(ws, "started", **session.metadata())

                elif command == "pause":
                    if not session:
                        await _send(ws, "error", code="not_started")
                        continue
                    session.paused = True
                    write_event(session, {"event": "pause"})
                    await _send(ws, "paused", **session.metadata())

                elif command == "resume":
                    if not session:
                        await _send(ws, "error", code="not_started")
                        continue
                    session.paused = False
                    write_event(session, {"event": "resume"})
                    await _send(ws, "resumed", **session.metadata())

                elif command == "stop":
                    if not session:
                        await _send(ws, "error", code="not_started")
                        continue
                    session.stopped = True
                    write_event(session, {"event": "stop", "metadata": session.metadata()})
                    await orchestrator.stop(audio_fp)
                    await _send(ws, "stopped", **session.metadata())
                    await ws.close()

                elif command == "ping":
                    await _send(ws, "pong")

                elif command == "client_status":
                    if not session:
                        await _send(ws, "error", code="not_started")
                        continue
                    write_event(
                        session,
                        {
                            "event": "client_status",
                            "status": str(payload.get("status") or "")[:300],
                            "details": payload.get("details"),
                        },
                    )
                    await _send(ws, "client_status_ack", status=str(payload.get("status") or "")[:120])

                elif command == "audio":
                    if not session or not audio_fp or not orchestrator:
                        await _send(ws, "error", code="not_started")
                        continue
                    if session.paused:
                        await _send(ws, "audio_ignored", reason="paused")
                        continue
                    encoded_audio = payload.get("audio") or ""
                    try:
                        audio_data = base64.b64decode(encoded_audio, validate=True)
                    except Exception as exc:
                        await _send(ws, "error", code="bad_audio_base64", message=str(exc))
                        continue
                    await _handle_audio_chunk(
                        ws=ws,
                        session=session,
                        audio_fp=audio_fp,
                        orchestrator=orchestrator,
                        data=audio_data,
                    )

                else:
                    await _send(ws, "error", code="unknown_command", command=command)

            elif msg.type == WSMsgType.BINARY:
                if not session or not audio_fp or not orchestrator:
                    await _send(ws, "error", code="not_started")
                    continue
                if session.paused:
                    await _send(ws, "audio_ignored", reason="paused")
                    continue
                await _handle_audio_chunk(
                    ws=ws,
                    session=session,
                    audio_fp=audio_fp,
                    orchestrator=orchestrator,
                    data=msg.data,
                )

            elif msg.type == WSMsgType.ERROR:
                log.warning("WebSocket error: %s", ws.exception())

    finally:
        if orchestrator:
            await orchestrator.stop(audio_fp)
        if audio_fp:
            try:
                audio_fp.flush()
                audio_fp.close()
            except Exception:
                pass
        if session and not session.stopped:
            write_event(session, {"event": "disconnect", "metadata": session.metadata()})
        log.info("WebSocket closed: session=%s", session.session_id if session else "-")

    return ws


async def _handle_audio_chunk(
    *,
    ws: web.WebSocketResponse,
    session: DictaphoneSession,
    audio_fp: Any,
    orchestrator: OutputsOrchestrator,
    data: bytes,
) -> None:
    audio_fp.write(data)
    session.bytes_received += len(data)
    session.chunks_received += 1

    asyncio.create_task(orchestrator.append_audio(data))

    if session.chunks_received == 1:
        audio_fp.flush()
        write_event(
            session,
            {
                "event": "first_audio_chunk",
                "bytes_received": session.bytes_received,
                "chunk_bytes": len(data),
            },
        )
        await _send(
            ws,
            "audio_started",
            bytes_received=session.bytes_received,
            chunk_bytes=len(data),
        )
    elif session.chunks_received % 25 == 0:
        audio_fp.flush()
        write_event(
            session,
            {
                "event": "audio_progress",
                "bytes_received": session.bytes_received,
                "chunks_received": session.chunks_received,
            },
        )
        await _send(
            ws,
            "audio_ack",
            bytes_received=session.bytes_received,
            chunks_received=session.chunks_received,
        )


def _check_token(request: web.Request) -> bool:
    import secrets

    from config import ALLOW_INSECURE, TOKEN

    if ALLOW_INSECURE:
        return True
    if not TOKEN:
        return False
    supplied = request.headers.get("X-Dictaphone-Token", "")
    if not supplied:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            supplied = auth.removeprefix("Bearer ").strip()
    return secrets.compare_digest(supplied, TOKEN)