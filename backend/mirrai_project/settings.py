import os
from pathlib import Path

import environ


env = environ.Env(
    DEBUG=(bool, False),
    SUPABASE_USE_REMOTE_DB=(bool, False),
    SUPABASE_USE_REMOTE_STORAGE=(bool, False),
    MIRRAI_PERSIST_CAPTURE_IMAGES=(bool, False),
    MIRRAI_REQUIRE_CLIENT_AUTH=(bool, False),
    SUPABASE_BUCKET_PUBLIC=(bool, False),
    SUPABASE_SIGNED_URL_EXPIRES_IN=(int, 3600),
    SUPABASE_BUCKET_FILE_SIZE_LIMIT=(int, 10 * 1024 * 1024),
)

BASE_DIR = Path(__file__).resolve().parent.parent
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

SECRET_KEY = env("SECRET_KEY", default="django-insecure-mock-key-for-dev")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = ["*"]

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
MIRRAI_REQUIRE_CLIENT_AUTH = env.bool("MIRRAI_REQUIRE_CLIENT_AUTH", default=False)
BUSINESS_VERIFICATION_API_URL = env("BUSINESS_VERIFICATION_API_URL", default="")
BUSINESS_VERIFICATION_SERVICE_KEY = env("BUSINESS_VERIFICATION_SERVICE_KEY", default="")

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
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
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
