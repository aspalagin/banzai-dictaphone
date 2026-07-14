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

Сервер ожидает `DICTAPHONE_TOKEN` и принимает его в `X-Dictaphone-Token` или
`Authorization: Bearer <token>`. Без токена он не запускается, если только
явно не включён `DICTAPHONE_ALLOW_INSECURE=1`; этот режим предназначен только
для локальной разработки. Встроенный сервер не настраивает TLS и по умолчанию
слушает `127.0.0.1`. Для доступа из сети используйте защищённый reverse proxy
или туннель с TLS и не публикуйте порт напрямую.

Каждая запись сохраняется в `sessions/<дата>/<session_id>/`: как минимум
`audio.pcm`, `events.jsonl` и при успешной расшифровке `transcript.txt`.
Код не реализует автоматическое удаление локальных сессий: настроить срок
хранения и удаление должен оператор. В batch-режиме временный OGG загружается
в Yandex Object Storage; объект удаляется после обработки по умолчанию
(`DICTAPHONE_YANDEX_STT_DELETE_OBJECT=1`). При включённой доставке в Telegram
текст и подготовленный аудиофайл отправляются в указанный чат. Подробности —
в [SECURITY.md](SECURITY.md).

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
pip install -r ../requirements.lock
cp ../.env.example .env
set -a
. ./.env
set +a
python3 server.py
```

Прямые зависимости зафиксированы в `requirements.txt`, а полный набор с
транзитивными версиями — в `requirements.lock`. Для повторяемой установки
используйте lock-файл без неограниченного обновления пакетов.

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

## Разработка

Быстрые проверки не требуют ключей облачных провайдеров или Android SDK:

```bash
python3 -m unittest discover -s server/tests -v
bash -n android/build-apk.sh
```

Правила вклада — в [CONTRIBUTING.md](CONTRIBUTING.md), условия сообщества — в
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), история изменений — в
[CHANGELOG.md](CHANGELOG.md).
