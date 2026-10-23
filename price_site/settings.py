"""Настройки price.interalex.pro.

Всё, что отличается между сервером и разработкой, берётся из переменных окружения.
Секретный ключ Django генерируется при первом запуске и хранится в каталоге данных.
"""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("PRICE_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _secret_key() -> str:
    path = DATA_DIR / "secret_key"
    if not path.exists():
        old_umask = os.umask(0o077)
        try:
            path.write_text(secrets.token_urlsafe(64))
        finally:
            os.umask(old_umask)
    return path.read_text().strip()


SECRET_KEY = _secret_key()
DEBUG = os.environ.get("DJANGO_DEBUG") == "1"
ALLOWED_HOSTS = os.environ.get(
    "DJANGO_ALLOWED_HOSTS", "price.interalex.pro,www.price.interalex.pro,127.0.0.1,localhost"
).split(",")
CSRF_TRUSTED_ORIGINS = ["https://price.interalex.pro", "https://www.price.interalex.pro"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "core",
    "pricing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "accounts.middleware.AccessListMiddleware",
]

ROOT_URLCONF = "price_site.urls"
WSGI_APPLICATION = "price_site.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Kyiv"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = Path(os.environ.get("PRICE_STATIC_ROOT", BASE_DIR / "staticfiles"))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"

# Сессия живёт 30 дней; доступ при этом перепроверяется по списку на каждом запросе.
SESSION_COOKIE_AGE = 30 * 24 * 3600
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Вход через Telegram
PRICE_BOT_TOKEN = os.environ.get("PRICE_BOT_TOKEN", "")
PRICE_BOT_USERNAME = os.environ.get("PRICE_BOT_USERNAME", "priceIAPRO_bot")
LOGIN_TOKEN_TTL_SECONDS = 300
# Список доступа выгружает из Google Таблицы root-скрипт (deploy/price_access_sync.py).
ACCESS_LIST_FILE = DATA_DIR / "allowed.json"
# Сюда бот дописывает успешные входы; root-скрипт переносит их в таблицу.
AUTH_EVENTS_FILE = DATA_DIR / "auth_events.jsonl"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
