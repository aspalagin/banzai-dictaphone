import os
from pathlib import Path


def env_or_file(name: str, default: str = "") -> str:
    value = os.getenv(name, "")
    if value:
        return value
    file_path = os.getenv(f"{name}_FILE", "")
    if not file_path:
        return default
    try:
        return Path(file_path).read_text(encoding="utf-8").strip()
    except OSError:
        return default


BASE_DIR = Path(env_or_file("DICTAPHONE_BASE_DIR", str(Path(__file__).resolve().parent)))
SESSIONS_DIR = Path(env_or_file("DICTAPHONE_SESSIONS_DIR", str(BASE_DIR / "sessions")))

HOST = env_or_file("DICTAPHONE_HOST", "127.0.0.1")
PORT = int(env_or_file("DICTAPHONE_PORT", "8097"))
TOKEN = env_or_file("DICTAPHONE_TOKEN")
ALLOW_INSECURE = env_or_file("DICTAPHONE_ALLOW_INSECURE") == "1"

TELEGRAM_CHAT_ID = env_or_file("DICTAPHONE_TELEGRAM_CHAT_ID")
TELEGRAM_STOP_TIMEOUT_SECONDS = float(env_or_file("DICTAPHONE_TG_STOP_TIMEOUT_SECONDS", "180"))

MAX_AUDIO_MESSAGE_BYTES = int(env_or_file("DICTAPHONE_MAX_AUDIO_MESSAGE_BYTES", "262144"))
PING_INTERVAL_SECONDS = int(env_or_file("DICTAPHONE_PING_INTERVAL_SECONDS", "20"))

OPENAI_REALTIME_URL = env_or_file("DICTAPHONE_OPENAI_REALTIME_URL", "wss://api.openai.com/v1/realtime")
OPENAI_STT_MODEL = env_or_file("DICTAPHONE_OPENAI_STT_MODEL", "gpt-realtime-whisper")
OPENAI_STT_LANGUAGE = env_or_file("DICTAPHONE_OPENAI_STT_LANGUAGE", "ru")
OPENAI_TOKEN_FILE = Path(env_or_file("DICTAPHONE_OPENAI_TOKEN_FILE"))
OPENAI_REFRESH_SCRIPT = env_or_file("DICTAPHONE_OPENAI_REFRESH_SCRIPT")
STT_ENABLED = env_or_file("DICTAPHONE_STT_ENABLED", "1") != "0"
STT_PROVIDER = env_or_file("DICTAPHONE_STT_PROVIDER", "openai").strip().lower()
STT_DEFAULT_SAMPLE_RATE = int(env_or_file("DICTAPHONE_STT_DEFAULT_SAMPLE_RATE", "24000"))
STT_COMMIT_INTERVAL_SECONDS = float(env_or_file("DICTAPHONE_STT_COMMIT_INTERVAL_SECONDS", "1.2"))

YANDEX_STT_LANGUAGE = env_or_file("DICTAPHONE_YANDEX_STT_LANGUAGE", "ru-RU")
YANDEX_STT_MODEL = env_or_file("DICTAPHONE_YANDEX_STT_MODEL", "deferred-general:rc")
YANDEX_STT_POLL_INTERVAL_SECONDS = float(env_or_file("DICTAPHONE_YANDEX_STT_POLL_INTERVAL_SECONDS", "5"))
YANDEX_STT_TIMEOUT_SECONDS = float(env_or_file("DICTAPHONE_YANDEX_STT_TIMEOUT_SECONDS", "300"))
YANDEX_STT_DELETE_OBJECT = env_or_file("DICTAPHONE_YANDEX_STT_DELETE_OBJECT", "1") != "0"

YANDEX_REALTIME_URL = env_or_file("DICTAPHONE_YANDEX_REALTIME_URL", "wss://ai.api.cloud.yandex.net/v1/realtime")
YANDEX_REALTIME_MODEL = env_or_file("DICTAPHONE_YANDEX_REALTIME_MODEL", "speech-realtime-250923")
YANDEX_REALTIME_FOLDER_ID = env_or_file(
    "DICTAPHONE_YANDEX_FOLDER_ID",
    env_or_file("YC_FOLDER_ID", env_or_file("YANDEX_CLOUD_FOLDER_ID")),
)
YANDEX_REALTIME_API_KEY = env_or_file(
    "DICTAPHONE_YANDEX_API_KEY",
    env_or_file("YC_API_KEY", env_or_file("YANDEX_CLOUD_API_KEY")),
)
YANDEX_REALTIME_LANGUAGE = env_or_file("DICTAPHONE_YANDEX_REALTIME_LANGUAGE", "ru-RU")
YANDEX_REALTIME_VOICE = env_or_file("DICTAPHONE_YANDEX_REALTIME_VOICE", "dasha")
YANDEX_REALTIME_SILENCE_MS = int(env_or_file("DICTAPHONE_YANDEX_REALTIME_SILENCE_MS", "600"))
YANDEX_REALTIME_STOP_GRACE_SECONDS = float(env_or_file("DICTAPHONE_YANDEX_REALTIME_STOP_GRACE_SECONDS", "4"))
