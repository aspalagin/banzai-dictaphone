#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

from aiohttp import WSMsgType, web

from config import (
    ALLOW_INSECURE,
    HOST,
    MAX_AUDIO_MESSAGE_BYTES,
    PING_INTERVAL_SECONDS,
    PORT,
    SESSIONS_DIR,
    STT_DEFAULT_SAMPLE_RATE,
    STT_ENABLED,
    STT_PROVIDER,
    TELEGRAM_STOP_TIMEOUT_SECONDS,
    TOKEN,
)
from openai_realtime_stt import RealtimeTranscriber
from protocol import DictaphoneSession, safe_session_id, utc_now_iso
from telegram_sink import TelegramSink
from yandex_batch_stt import YandexBatchTranscriber
from yandex_realtime_stt import YandexRealtimeTranscriber


log = logging.getLogger("dictaphone.server")


@dataclass
class ActiveHttpRecording:
    session: DictaphoneSession
    audio_fp: Any
    transcriber: Any | None
    tg_sink: TelegramSink | None
    lock: asyncio.Lock
    closing: bool = False
    pending_stt: list[bytes] = field(default_factory=list)


HTTP_RECORDINGS: dict[str, ActiveHttpRecording] = {}
STT_APPEND_CHUNK_BYTES = 24000


def _json_response(payload: dict[str, Any], status: int = 200) -> web.Response:
    return web.json_response(payload, status=status, dumps=lambda x: json.dumps(x, ensure_ascii=False))


def _check_token(request: web.Request) -> bool:
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


async def health(request: web.Request) -> web.Response:
    return _json_response(
        {
            "ok": True,
            "service": "banzai-dictaphone",
            "time": utc_now_iso(),
            "auth_configured": bool(TOKEN) or ALLOW_INSECURE,
            "sessions_dir": str(SESSIONS_DIR),
            "stt_enabled": STT_ENABLED,
            "stt_provider": STT_PROVIDER,
        }
    )


def _write_event(session: DictaphoneSession, event: dict[str, Any]) -> None:
    event.setdefault("ts", utc_now_iso())
    with session.events_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(event, ensure_ascii=False) + "\n")


def _create_session(payload: dict[str, Any]) -> DictaphoneSession:
    now = datetime.now(timezone.utc)
    requested_id = str(payload.get("session_id") or now.strftime("%Y%m%dT%H%M%SZ"))
    session_id = safe_session_id(requested_id)
    root = SESSIONS_DIR / now.strftime("%Y-%m-%d") / session_id
    suffix = 1
    while root.exists():
        suffix += 1
        root = SESSIONS_DIR / now.strftime("%Y-%m-%d") / f"{session_id}-{suffix}"
    root.mkdir(parents=True, exist_ok=False)
    return DictaphoneSession(
        session_id=root.name,
        root=root,
        device=str(payload.get("device") or "unknown")[:120],
        mode=str(payload.get("mode") or "dictation")[:60],
        sample_rate=int(payload.get("sample_rate") or STT_DEFAULT_SAMPLE_RATE),
        channels=int(payload.get("channels") or 1),
        encoding=str(payload.get("encoding") or "pcm_s16le")[:40],
    )


async def _append_audio_safely(
    session: DictaphoneSession,
    transcriber: Any,
    data: bytes,
) -> None:
    try:
        if STT_PROVIDER in {"yandex_realtime", "yandex-realtime"}:
            for offset in range(0, len(data), STT_APPEND_CHUNK_BYTES):
                await transcriber.append_audio(data[offset : offset + STT_APPEND_CHUNK_BYTES])
                await asyncio.sleep(0)
        else:
            await transcriber.append_audio(data)
    except Exception as exc:
        _write_event(session, {"event": "stt_append_error", "message": str(exc)[:500]})


async def _stop_outputs_later(recording: ActiveHttpRecording) -> None:
    if recording.transcriber:
        try:
            if STT_PROVIDER == "yandex":
                await recording.transcriber.stop()
            elif STT_PROVIDER in {"yandex_realtime", "yandex-realtime"}:
                await asyncio.wait_for(recording.transcriber.stop(), timeout=10)
            else:
                await asyncio.wait_for(recording.transcriber.stop(), timeout=4)
        except Exception as exc:
            _write_event(recording.session, {"event": "stt_stop_error", "message": str(exc)[:500]})
        finally:
            recording.transcriber = None
    if recording.tg_sink:
        try:
            await asyncio.wait_for(
                recording.tg_sink.stop(
                    transcript_path=recording.session.transcript_path,
                    audio_path=recording.session.audio_path,
                    sample_rate=recording.session.sample_rate,
                    channels=recording.session.channels,
                ),
                timeout=TELEGRAM_STOP_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            _write_event(recording.session, {"event": "telegram_stop_error", "message": str(exc)[:500]})
        finally:
            recording.tg_sink = None


async def _send(ws: web.WebSocketResponse, event: str, **payload: Any) -> None:
    payload["event"] = event
    payload.setdefault("ts", utc_now_iso())
    await ws.send_str(json.dumps(payload, ensure_ascii=False))


async def _handle_audio_chunk(
    *,
    ws: web.WebSocketResponse | None,
    session: DictaphoneSession,
    audio_fp: Any,
    transcriber: Any | None,
    data: bytes,
    wait_for_transcriber: bool = False,
) -> None:
    audio_fp.write(data)
    session.bytes_received += len(data)
    session.chunks_received += 1
    if transcriber:
        if wait_for_transcriber:
            await _append_audio_safely(session, transcriber, data)
        else:
            asyncio.create_task(_append_audio_safely(session, transcriber, data))
    if session.chunks_received == 1:
        audio_fp.flush()
        _write_event(
            session,
            {
                "event": "first_audio_chunk",
                "bytes_received": session.bytes_received,
                "chunk_bytes": len(data),
            },
        )
        if ws:
            await _send(
                ws,
                "audio_started",
                bytes_received=session.bytes_received,
                chunk_bytes=len(data),
            )
    if session.chunks_received % 25 == 0:
        audio_fp.flush()
        _write_event(
            session,
            {
                "event": "audio_progress",
                "bytes_received": session.bytes_received,
                "chunks_received": session.chunks_received,
            },
        )
        if ws:
            await _send(
                ws,
                "audio_ack",
                bytes_received=session.bytes_received,
                chunks_received=session.chunks_received,
            )


def _create_transcriber(session: DictaphoneSession, write_event: Any) -> Any:
    if STT_PROVIDER == "openai":
        return RealtimeTranscriber(
            session_id=session.session_id,
            sample_rate=session.sample_rate,
            transcript_path=session.transcript_path,
            write_event=write_event,
        )
    if STT_PROVIDER == "yandex":
        return YandexBatchTranscriber(
            session_id=session.session_id,
            sample_rate=session.sample_rate,
            audio_path=session.audio_path,
            transcript_path=session.transcript_path,
            write_event=write_event,
        )
    if STT_PROVIDER in {"yandex_realtime", "yandex-realtime"}:
        return YandexRealtimeTranscriber(
            session_id=session.session_id,
            sample_rate=session.sample_rate,
            transcript_path=session.transcript_path,
            write_event=write_event,
        )
    raise RuntimeError(f"Unknown DICTAPHONE_STT_PROVIDER: {STT_PROVIDER}")


async def _start_session_outputs(
    session: DictaphoneSession,
    *,
    send_client_event: Any | None = None,
) -> tuple[Any | None, TelegramSink | None]:
    tg_sink: TelegramSink | None = TelegramSink(session_id=session.session_id)
    try:
        await tg_sink.start()
    except Exception as exc:
        log.warning("Telegram sink start failed: %s", exc)
        tg_sink = None

    transcriber: Any | None = None
    if STT_ENABLED:
        def _stt_event(event: dict[str, Any]) -> None:
            _write_event(session, event)
            evt_name = event.get("event", "")
            if send_client_event and evt_name in {"transcript_delta", "transcript_completed", "stt_error"}:
                payload = {k: v for k, v in event.items() if k != "event"}
                asyncio.create_task(send_client_event(evt_name, **payload))
            if tg_sink:
                if evt_name == "transcript_delta":
                    asyncio.create_task(
                        tg_sink.on_transcript_delta(
                            event.get("delta", ""),
                            item_id=event.get("item_id"),
                        )
                    )
                elif evt_name == "transcript_completed":
                    asyncio.create_task(
                        tg_sink.on_transcript_completed(
                            event.get("transcript", ""),
                            item_id=event.get("item_id"),
                        )
                    )

        try:
            transcriber = _create_transcriber(session, _stt_event)
            await asyncio.wait_for(transcriber.start(), timeout=20)
        except Exception as exc:
            transcriber = None
            _write_event(session, {"event": "stt_start_error", "message": str(exc)})
            if send_client_event:
                await send_client_event("stt_start_error", message=str(exc))

    return transcriber, tg_sink


async def _start_http_outputs_later(recording: ActiveHttpRecording) -> None:
    await asyncio.sleep(0.1)
    if recording.closing or recording.session.stopped:
        _write_event(recording.session, {"event": "outputs_skipped", "reason": "session_stopped"})
        return
    _write_event(recording.session, {"event": "outputs_starting", "transport": "http"})
    transcriber, tg_sink = await _start_session_outputs(recording.session)
    pending: list[bytes] = []
    async with recording.lock:
        if not recording.closing and not recording.session.stopped:
            recording.transcriber = transcriber
            recording.tg_sink = tg_sink
            if transcriber and recording.pending_stt:
                pending = recording.pending_stt
                recording.pending_stt = []
        else:
            pending = []
    if recording.closing or recording.session.stopped:
        tmp = ActiveHttpRecording(
            session=recording.session,
            audio_fp=recording.audio_fp,
            transcriber=transcriber,
            tg_sink=tg_sink,
            lock=recording.lock,
            closing=True,
        )
        await _stop_outputs_later(tmp)
        return
    if transcriber:
        for chunk in pending:
            asyncio.create_task(_append_audio_safely(recording.session, transcriber, chunk))
    _write_event(
        recording.session,
        {
            "event": "outputs_started",
            "stt": bool(transcriber),
            "telegram": bool(tg_sink),
            "pending_chunks": len(pending),
        },
    )


async def stream_ws(request: web.Request) -> web.WebSocketResponse:
    if not _check_token(request):
        raise web.HTTPUnauthorized(text="missing or invalid DICTAPHONE_TOKEN")

    ws = web.WebSocketResponse(heartbeat=None, max_msg_size=MAX_AUDIO_MESSAGE_BYTES)
    await ws.prepare(request)
    await _send(ws, "hello", protocol="banzai-dictaphone.v1")

    session: DictaphoneSession | None = None
    audio_fp = None
    transcriber: Any | None = None
    tg_sink: TelegramSink | None = None

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
                    session = _create_session(payload)
                    audio_fp = session.audio_path.open("ab")
                    _write_event(session, {"event": "start", "metadata": session.metadata()})
                    # Запускаем Telegram sink
                    tg_sink = TelegramSink(session_id=session.session_id)
                    try:
                        await tg_sink.start()
                    except Exception as exc:
                        log.warning("Telegram sink start failed: %s", exc)
                        tg_sink = None

                    if STT_ENABLED:
                        def _stt_event(event: dict[str, Any]) -> None:
                            assert session is not None
                            _write_event(session, event)
                            evt_name = event.get("event", "")
                            if evt_name in {"transcript_delta", "transcript_completed", "stt_error"}:
                                payload = {k: v for k, v in event.items() if k != "event"}
                                asyncio.create_task(_send(ws, evt_name, **payload))
                            # Отправляем в Telegram
                            if tg_sink:
                                if evt_name == "transcript_delta":
                                    asyncio.create_task(
                                        tg_sink.on_transcript_delta(
                                            event.get("delta", ""),
                                            item_id=event.get("item_id"),
                                        )
                                    )
                                elif evt_name == "transcript_completed":
                                    asyncio.create_task(
                                        tg_sink.on_transcript_completed(
                                            event.get("transcript", ""),
                                            item_id=event.get("item_id"),
                                        )
                                    )

                        try:
                            transcriber = _create_transcriber(session, _stt_event)
                            await asyncio.wait_for(transcriber.start(), timeout=20)
                        except Exception as exc:
                            transcriber = None
                            _write_event(session, {"event": "stt_start_error", "message": str(exc)})
                            await _send(ws, "stt_start_error", message=str(exc))
                    await _send(ws, "started", **session.metadata())

                elif command == "pause":
                    if not session:
                        await _send(ws, "error", code="not_started")
                        continue
                    session.paused = True
                    _write_event(session, {"event": "pause"})
                    await _send(ws, "paused", **session.metadata())

                elif command == "resume":
                    if not session:
                        await _send(ws, "error", code="not_started")
                        continue
                    session.paused = False
                    _write_event(session, {"event": "resume"})
                    await _send(ws, "resumed", **session.metadata())

                elif command == "stop":
                    if not session:
                        await _send(ws, "error", code="not_started")
                        continue
                    session.stopped = True
                    if transcriber:
                        await transcriber.stop()
                        transcriber = None
                    if tg_sink:
                        if audio_fp:
                            audio_fp.flush()
                        await tg_sink.stop(
                            transcript_path=session.transcript_path,
                            audio_path=session.audio_path,
                            sample_rate=session.sample_rate,
                            channels=session.channels,
                        )
                        tg_sink = None
                    _write_event(session, {"event": "stop", "metadata": session.metadata()})
                    await _send(ws, "stopped", **session.metadata())
                    await ws.close()

                elif command == "ping":
                    await _send(ws, "pong")

                elif command == "client_status":
                    if not session:
                        await _send(ws, "error", code="not_started")
                        continue
                    _write_event(
                        session,
                        {
                            "event": "client_status",
                            "status": str(payload.get("status") or "")[:300],
                            "details": payload.get("details"),
                        },
                    )
                    await _send(ws, "client_status_ack", status=str(payload.get("status") or "")[:120])

                elif command == "audio":
                    if not session or not audio_fp:
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
            transcriber=transcriber,
            data=audio_data,
        )

                else:
                    await _send(ws, "error", code="unknown_command", command=command)

            elif msg.type == WSMsgType.BINARY:
                if not session or not audio_fp:
                    await _send(ws, "error", code="not_started")
                    continue
                if session.paused:
                    await _send(ws, "audio_ignored", reason="paused")
                    continue
                await _handle_audio_chunk(
                    ws=ws,
                    session=session,
                    audio_fp=audio_fp,
            transcriber=transcriber,
            data=msg.data,
        )

            elif msg.type == WSMsgType.ERROR:
                log.warning("WebSocket error: %s", ws.exception())

    finally:
        if transcriber:
            await transcriber.stop()
        if tg_sink:
            if audio_fp:
                audio_fp.flush()
            await tg_sink.stop(
                transcript_path=session.transcript_path if session else None,
                audio_path=session.audio_path if session else None,
                sample_rate=session.sample_rate if session else 24000,
                channels=session.channels if session else 1,
            )
        if audio_fp:
            audio_fp.flush()
            audio_fp.close()
        if session and not session.stopped:
            _write_event(session, {"event": "disconnect", "metadata": session.metadata()})
        log.info("WebSocket closed: session=%s", session.session_id if session else "-")

    return ws


async def http_start(request: web.Request) -> web.Response:
    if not _check_token(request):
        raise web.HTTPUnauthorized(text="missing or invalid DICTAPHONE_TOKEN")
    try:
        payload = await request.json()
    except Exception as exc:
        return _json_response({"ok": False, "error": "bad_json", "message": str(exc)}, status=400)

    session = _create_session(payload)
    audio_fp = session.audio_path.open("ab")
    _write_event(
        session,
        {
            "event": "start",
            "transport": "http",
            "client_version": str(payload.get("client_version") or "")[:80],
            "metadata": session.metadata(),
        },
    )
    recording = ActiveHttpRecording(
        session=session,
        audio_fp=audio_fp,
        transcriber=None,
        tg_sink=None,
        lock=asyncio.Lock(),
    )
    HTTP_RECORDINGS[session.session_id] = recording
    asyncio.create_task(_start_http_outputs_later(recording))
    return _json_response({"ok": True, **session.metadata()})


async def http_audio(request: web.Request) -> web.Response:
    if not _check_token(request):
        raise web.HTTPUnauthorized(text="missing or invalid DICTAPHONE_TOKEN")
    session_id = safe_session_id(request.match_info["session_id"])
    recording = HTTP_RECORDINGS.get(session_id)
    if not recording:
        return _json_response({"ok": False, "error": "session_not_found"}, status=404)

    if request.content_type == "application/json":
        try:
            payload = await request.json()
            data = base64.b64decode(str(payload.get("audio") or ""), validate=True)
        except Exception as exc:
            return _json_response({"ok": False, "error": "bad_audio_json", "message": str(exc)}, status=400)
    else:
        data = await request.read()
    if not data:
        return _json_response({"ok": False, "error": "empty_audio"}, status=400)
    if len(data) > MAX_AUDIO_MESSAGE_BYTES:
        return _json_response({"ok": False, "error": "audio_too_large", "max_bytes": MAX_AUDIO_MESSAGE_BYTES}, status=413)

    async with recording.lock:
        if recording.session.stopped or recording.closing:
            return _json_response({"ok": False, "error": "session_stopped"}, status=409)
        transcriber = recording.transcriber
        if not transcriber and len(recording.pending_stt) < 40:
            recording.pending_stt.append(data)
        await _handle_audio_chunk(
            ws=None,
            session=recording.session,
            audio_fp=recording.audio_fp,
            transcriber=transcriber,
            data=data,
            wait_for_transcriber=False,
        )
        return _json_response(
            {
                "ok": True,
                "session_id": recording.session.session_id,
                "bytes_received": recording.session.bytes_received,
                "chunks_received": recording.session.chunks_received,
                "stt_active": bool(recording.transcriber),
            }
        )


async def http_client_status(request: web.Request) -> web.Response:
    """Принимает статусные сообщения от APK для диагностики."""
    if not _check_token(request):
        raise web.HTTPUnauthorized(text="missing or invalid DICTAPHONE_TOKEN")
    session_id = safe_session_id(request.match_info["session_id"])
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    status = str(payload.get("status") or "")[:500]
    log.info("CLIENT STATUS [%s]: %s", session_id, status)
    # Запишем в events.jsonl если сессия существует
    recording = HTTP_RECORDINGS.get(session_id)
    if recording:
        _write_event(recording.session, {"event": "client_status", "status": status})
    else:
        # Попробуем найти session dir
        for date_dir in sorted(SESSIONS_DIR.iterdir(), reverse=True):
            candidate = date_dir / session_id
            if candidate.exists():
                events_path = candidate / "events.jsonl"
                try:
                    with events_path.open("a", encoding="utf-8") as fp:
                        import json as _json
                        fp.write(_json.dumps({"event": "client_status", "status": status, "ts": utc_now_iso()}, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                break
    return _json_response({"ok": True})


async def http_status(request: web.Request) -> web.Response:
    if not _check_token(request):
        raise web.HTTPUnauthorized(text="missing or invalid DICTAPHONE_TOKEN")
    session_id = safe_session_id(request.match_info["session_id"])
    recording = HTTP_RECORDINGS.get(session_id)
    if recording:
        return _json_response(
            {
                "ok": True,
                "active": True,
                "closing": recording.closing,
                "stt_active": bool(recording.transcriber),
                **recording.session.metadata(),
            }
        )
    for date_dir in sorted(SESSIONS_DIR.iterdir(), reverse=True):
        candidate = date_dir / session_id
        if candidate.exists():
            audio_path = candidate / "audio.pcm"
            transcript_path = candidate / "transcript.txt"
            return _json_response(
                {
                    "ok": True,
                    "active": False,
                    "session_id": session_id,
                    "audio_path": str(audio_path),
                    "audio_bytes": audio_path.stat().st_size if audio_path.exists() else 0,
                    "transcript_path": str(transcript_path),
                    "transcript_exists": transcript_path.exists(),
                }
            )
    return _json_response({"ok": False, "error": "session_not_found"}, status=404)


async def http_stop(request: web.Request) -> web.Response:
    if not _check_token(request):
        raise web.HTTPUnauthorized(text="missing or invalid DICTAPHONE_TOKEN")
    session_id = safe_session_id(request.match_info["session_id"])
    recording = HTTP_RECORDINGS.pop(session_id, None)
    if not recording:
        return _json_response({"ok": False, "error": "session_not_found"}, status=404)

    async with recording.lock:
        recording.closing = True
        recording.session.stopped = True
        recording.audio_fp.flush()
        recording.audio_fp.close()
        _write_event(recording.session, {"event": "stop", "transport": "http", "metadata": recording.session.metadata()})
    asyncio.create_task(_stop_outputs_later(recording))
    return _json_response({"ok": True, **recording.session.metadata()})


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/v1/stream", stream_ws)
    app.router.add_post("/v1/http/start", http_start)
    app.router.add_post("/v1/http/audio/{session_id}", http_audio)
    app.router.add_post("/v1/http/client-status/{session_id}", http_client_status)
    app.router.add_get("/v1/http/status/{session_id}", http_status)
    app.router.add_post("/v1/http/stop/{session_id}", http_stop)
    return app


async def _shutdown(app: web.Application) -> None:
    log.info("Останавливаю dictaphone server")
    recordings = list(HTTP_RECORDINGS.values())
    HTTP_RECORDINGS.clear()
    for recording in recordings:
        recording.closing = True
        recording.session.stopped = True
        try:
            recording.audio_fp.flush()
            recording.audio_fp.close()
        except Exception:
            pass
        await _stop_outputs_later(recording)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("DICTAPHONE_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if not TOKEN and not ALLOW_INSECURE:
        raise SystemExit("DICTAPHONE_TOKEN is required. For local dev only: DICTAPHONE_ALLOW_INSECURE=1")
    app = create_app()
    app.on_shutdown.append(_shutdown)
    web.run_app(app, host=HOST, port=PORT, handle_signals=True)


if __name__ == "__main__":
    main()
