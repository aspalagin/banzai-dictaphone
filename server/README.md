# Сервер диктофона

Python-сервер принимает raw PCM-аудио от Android-клиента, пишет сессии на диск,
отправляет аудио в STT-провайдер и публикует итоговые файлы в Telegram.

Поддерживаемые STT-провайдеры:
- `yandex_realtime` - Yandex AI Studio Realtime через WebSocket.
- `yandex` - Yandex SpeechKit batch STT v3 после остановки записи.
- `openai` - OpenAI Realtime transcription.
- `none` - только запись аудио на диск.

Batch-провайдер `yandex` кодирует сохранённый `audio.pcm` в OGG/Opus и запускает
SpeechKit v3 `recognizeFileAsync` с нормализацией текста и `literatureText`.

## Локальный запуск

```bash
cd server
python3 -m venv .venv
. .venv/bin/activate
pip install -r ../requirements.txt
cp ../.env.example .env
set -a
. ./.env
set +a
python3 server.py
```

Проверка:

```bash
curl http://127.0.0.1:8097/health
```

## HTTP API

- `POST /v1/http/start`
- `POST /v1/http/audio/{session_id}` with `application/octet-stream`
- `POST /v1/http/stop/{session_id}`
- `GET /v1/http/status/{session_id}`

Все запросы, кроме `/health`, требуют:

```text
Authorization: Bearer <DICTAPHONE_TOKEN>
```

## Сессии

По умолчанию сессии пишутся в `server/sessions/YYYY-MM-DD/<session_id>/`.
Каталог `sessions/` не должен попадать в git: там аудио, события и транскрипты.
