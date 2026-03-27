import os
from pathlib import Path

import environ


env = environ.Env(
    DEBUG=(bool, False),
    SUPABASE_USE_REMOTE_DB=(bool, False),
    SUPABASE_USE_REMOTE_STORAGE=(bool, False),
    MIRRAI_PERSIST_CAPTURE_IMAGES=(bool, False),
    TREND_REFRESH_ENABLED=(bool, False),
    TREND_REFRESH_INTERVAL_MINUTES=(int, 0),
    TREND_REFRESH_SOURCES=(list, []),
    SUPABASE_BUCKET_PUBLIC=(bool, False),
    SUPABASE_SIGNED_URL_EXPIRES_IN=(int, 3600),
    SUPABASE_BUCKET_FILE_SIZE_LIMIT=(int, 10 * 1024 * 1024),
)

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
environ.Env.read_env(os.path.join(PROJECT_ROOT, ".env"))
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

SECRET_KEY = env("SECRET_KEY", default="django-insecure-mock-key-for-dev")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

SUPABASE_DB_URL = env("SUPABASE_DB_URL", default="")
LOCAL_DATABASE_URL = env("LOCAL_DATABASE_URL", default="sqlite:///db.sqlite3")
SUPABASE_USE_REMOTE_DB = env.bool("SUPABASE_USE_REMOTE_DB", default=False)
ACTIVE_DATABASE_URL = SUPABASE_DB_URL if SUPABASE_USE_REMOTE_DB and SUPABASE_DB_URL else LOCAL_DATABASE_URL
DATABASES = {
    "default": environ.Env.db_url_config(ACTIVE_DATABASE_URL)
}

SUPABASE_URL = env("SUPABASE_URL", default="")
SUPABASE_ANON_KEY = env("SUPABASE_ANON_KEY", default="")
SUPABASE_SECRET_KEY = env("SUPABASE_SECRET_KEY", default="")
SUPABASE_SERVICE_ROLE_KEY = env("SUPABASE_SERVICE_ROLE_KEY", default="")
SUPABASE_SERVER_KEY = SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY
SUPABASE_BUCKET = env("SUPABASE_BUCKET", default="mirrai-assets")
SUPABASE_USE_REMOTE_STORAGE = env.bool("SUPABASE_USE_REMOTE_STORAGE", default=False)
SUPABASE_BUCKET_PUBLIC = env.bool("SUPABASE_BUCKET_PUBLIC", default=False)
SUPABASE_SIGNED_URL_EXPIRES_IN = env.int("SUPABASE_SIGNED_URL_EXPIRES_IN", default=3600)
SUPABASE_BUCKET_FILE_SIZE_LIMIT = env.int("SUPABASE_BUCKET_FILE_SIZE_LIMIT", default=10 * 1024 * 1024)
SUPABASE_ALLOWED_MIME_TYPES = [item.strip() for item in env.list("SUPABASE_ALLOWED_MIME_TYPES", default=["image/jpeg", "image/png", "image/webp"]) if item.strip()]
MIRRAI_PERSIST_CAPTURE_IMAGES = env.bool("MIRRAI_PERSIST_CAPTURE_IMAGES", default=False)
TREND_REFRESH_ENABLED = env.bool("TREND_REFRESH_ENABLED", default=False)
TREND_REFRESH_INTERVAL_MINUTES = env.int("TREND_REFRESH_INTERVAL_MINUTES", default=0)
TREND_REFRESH_SOURCE = env("TREND_REFRESH_SOURCE", default="ai_repo_refresh_trends")
TREND_REFRESH_SOURCES = [item.strip() for item in env.list("TREND_REFRESH_SOURCES", default=[]) if item.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    "app.apps.AppConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mirrai_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "mirrai_project.wsgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise storage for compressed and cached static files
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "storage")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "MirrAI API",
    "DESCRIPTION": "MirrAI Django-first backend with Supabase-ready storage and data contracts.",
    "VERSION": "1.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOW_ALL_ORIGINS = True

RUNPOD_BASE_URL = env("RUNPOD_BASE_URL", default="https://api.runpod.ai/v2").rstrip("/")
RUNPOD_API_KEY = env("RUNPOD_API_KEY", default="")
RUNPOD_TRENDS_ENDPOINT_ID = env(
    "RUNPOD_TRENDS_ENDPOINT_ID",
    default=env("RUNPOD_ENDPOINT_ID", default=""),
)
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")
TREND_REFINER_MODEL = env("TREND_REFINER_MODEL", default="gemini-2.5-flash")
