# Banzai Dictaphone

Android-диктофон и Python-сервер для записи голоса, потоковой STT и доставки
результата в Telegram.

Текущая архитектура:
- Android отправляет raw PCM через HTTP `application/octet-stream`.
- Сервер сначала пишет `audio.pcm` на диск и быстро отвечает клиенту.
- STT работает фоном, основной режим - Yandex AI Studio Realtime.
- После остановки записи сервер отправляет в Telegram `transcript.txt` и `audio.ogg`.

## Структура

```text
android/  Native Android Java app без Gradle
server/   Python aiohttp server, STT clients, Telegram sink
```

## Безопасность

В репозитории нет рабочих токенов, APK, keystore, аудиосессий, транскриптов,
`tunnel.conf` и локальных `.env` файлов. Для запуска скопируйте `.env.example`
в `.env` и заполните значения локально.

Android-клиент тоже не содержит дефолтный токен и URL. Их нужно указать в
настройках приложения после установки.

## Сборка Android

Нужен Android SDK с `platforms/android-34` и `build-tools/36.0.0`.

```bash
cd android
./build-apk.sh
```

Результат будет в:

```text
android/banzai-dictaphone.apk
```

## Запуск сервера

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

## Smoke test

```bash
cd server
python3 http_smoke.py \
  --base-url http://127.0.0.1:8097 \
  --token "$DICTAPHONE_TOKEN" \
  --pcm /path/to/audio.pcm \
  --chunk-bytes 96000 \
  --chunk-delay 2.0 \
  --wait-transcript 80
```

## Systemd

Примеры unit-файлов лежат в `server/systemd/`. Они рассчитаны на установку
проекта в `/opt/banzai-dictaphone` и env-файл `/etc/banzai-dictaphone.env`.
