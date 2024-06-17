"""
Django settings for rosak project.

Generated by 'django-admin startproject' using Django 4.0.5.

For more information on this file, see
https://docs.djangoproject.com/en/4.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.0/ref/settings/
"""

import os
from pathlib import Path

from corsheaders.defaults import default_headers

from rosak.sentry import filter_transactions
from rosak.util import strtobool

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-al9720%e_7+k_))6dn76=z5$39u-&nqhtx#4@7lnb0zet_(2fw",
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = bool(strtobool(os.getenv("DEBUG", "false")))
ENVIRONMENT = os.environ.get("ENVIRONMENT", "local")

# LOGGING = {
#     "version": 1,
#     "disable_existing_loggers": False,
#     "filters": {
#         "require_debug_true": {
#             "()": "django.utils.log.RequireDebugTrue",
#         }
#     },
#     "handlers": {
#         "console": {
#             "level": "DEBUG",
#             "filters": ["require_debug_true"],
#             "class": "logging.StreamHandler",
#         }
#     },
#     "loggers": {
#         "django.db.backends": {
#             "level": "DEBUG",
#             "handlers": ["console"],
#         }
#     },
# }

ALLOWED_HOSTS = ["*"]

LOGIN_REDIRECT_URL = os.getenv("LOGIN_REDIRECT_URL", "admin/")

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.gis",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "location_field.apps.DefaultConfig",
    "hijack",
    "hijack.contrib.admin",
    "colorfield",
    "advanced_filters",
    "rangefilter",
    "strawberry_django",
    "corsheaders",
    "django_extensions",
    "ordered_model",
    "mdeditor",
    "health_check",  # required
    "health_check.db",  # stock Django health checkers
    "health_check.cache",
    "health_check.storage",
    "health_check.contrib.migrations",
    "health_check.contrib.celery",  # requires celery
    "health_check.contrib.celery_ping",  # requires celery
    "health_check.contrib.psutil",  # disk and memory utilization; requires psutil
    # "health_check.contrib.s3boto3_storage",  # requires boto3 and S3BotoStorage backend
    # "health_check.contrib.rabbitmq",  # requires RabbitMQ broker
    "health_check.contrib.redis",  # requires Redis broker
    "cachalot",
    "operation",
    "common",
    "reporting",
    "generic",
    "spotting",
    "incident",
    "mlptf",
    "chartography",
    "telegram_provider",
    "django_celery_beat",
    "django_celery_results",
    # Must be at bottom
    "django_cleanup.apps.CleanupConfig",
]

MIDDLEWARE = [
    # This must be the first
    "django.middleware.cache.UpdateCacheMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "hijack.middleware.HijackUserMiddleware",
    # "django_asgi_lifespan.middleware.AsyncMiddleware",
    "django_asgi_lifespan.middleware.LifespanStateMiddleware",
    # This must be the last
    "django.middleware.cache.FetchFromCacheMiddleware",
]


if DEBUG is not True:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.redis import RedisIntegration
    from sentry_sdk.integrations.strawberry import StrawberryIntegration

    sentry_sdk.init(
        dsn=os.environ.get("SENTRY_DSN", None),
        environment=ENVIRONMENT,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            StrawberryIntegration(
                async_execution=True,
            ),
            RedisIntegration(),
        ],
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        # We recommend adjusting this value in production.
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLING_RATE", "1.0")),
        # Refer: https://docs.sentry.io/platforms/python/guides/django/configuration/filtering/#using-platformidentifier-namebefore-send-transaction-
        before_send_transaction=filter_transactions,
        # If you wish to associate users to errors (assuming you are using
        # django.contrib.auth) you may enable sending PII data.
        send_default_pii=True,
        profiles_sample_rate=float(
            os.environ.get("SENTRY_PROFILES_SAMPLING_RATE", "1.0")
        ),
    )

else:
    INSTALLED_APPS.insert(0, "debug_toolbar")
    MIDDLEWARE.insert(
        1, "strawberry_django.middlewares.debug_toolbar.DebugToolbarMiddleware"
    )

CSRF_TRUSTED_ORIGINS = [
    "https://rosak-7223b--pr8-ng-zorro-antd-l1wpy6qj.web.app",
    "https://community.mlptf.org.my",
    "https://staging-community.mlptf.org.my",
    "https://api-community.mlptf.org.my",
    "http://localhost:8000",
    "https://*.kwongtn.xyz",
]

CORS_ALLOWED_ORIGINS = [
    "https://rosak-7223b--pr8-ng-zorro-antd-l1wpy6qj.web.app",
    "https://community.mlptf.org.my",
    "http://localhost:4200",
    "https://staging-community.mlptf.org.my",
]

CORS_ALLOWED_ORIGIN_REGEXES = [
    "^https://rosak-7223b--staging-.*\\.web\\.app$",
    "^https://rosak-7223b\\.web\\.app$",
    "^https://.*\\.kwongtn\\.xyz$",
]

CORS_ALLOW_HEADERS = list(default_headers) + [
    "g-recaptcha-response",
    "firebase-auth-key",
]

INTERNAL_IPS = [
    "127.0.0.1",
    "localhost",
]

DEBUG_TOOLBAR_CONFIG = {"SHOW_TOOLBAR_CALLBACK": lambda _request: DEBUG}

ROOT_URLCONF = "rosak.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "rosak.wsgi.application"


# Database
# https://docs.djangoproject.com/en/4.0/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "HOST": os.environ.get("DATABASE_HOST", "localhost"),
        "NAME": os.environ.get("DATABASE_NAME", "postgres"),
        "USER": os.environ.get("DATABASE_USER", "postgres"),
        "PASSWORD": os.environ.get("DATABASE_PASSWORD", None),
        "PORT": os.environ.get("DATABASE_PORT", 5432),
        "TEST": {"SERIALIZE": False},
    }
}

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_USERNAME = os.environ.get("REDIS_USERNAME", None)
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)
REDIS_PORT = os.environ.get("REDIS_PORT", "6379")
REDIS_DB = os.environ.get("REDIS_DB", "0")

redis_cred_prefix = ""
if REDIS_USERNAME and REDIS_PASSWORD:
    redis_cred_prefix = f"{REDIS_USERNAME}:{REDIS_PASSWORD}@"

REDIS_URL = f"redis://{redis_cred_prefix}{REDIS_HOST}:{REDIS_PORT}"
REDIS_REPLICAS = os.getenv("REDIS_REPLICAS", [])

if REDIS_REPLICAS:
    replicas = []
    for redis_url in REDIS_REPLICAS.split(","):
        replicas.append(f"redis://{redis_cred_prefix}{REDIS_REPLICAS}")
    REDIS_REPLICAS = [REDIS_URL] + replicas

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_REPLICAS if REDIS_REPLICAS else REDIS_URL,
        "KEY_PREFIX": ENVIRONMENT,
        "OPTIONS": {
            "db": REDIS_DB,
        },
    }
    if not DEBUG
    else {
        "BACKEND": "django.core.cache.backends.dummy.DummyCache",
    },
    "celery": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "celery_cache",
    },
}


# Password validation
# https://docs.djangoproject.com/en/4.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "Asia/Kuala_Lumpur"

USE_I18N = True

USE_TZ = False


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.0/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = os.path.join(BASE_DIR, "static/")

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Default primary key field type
# https://docs.djangoproject.com/en/4.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DEBUG_TOOLBAR_PANELS = [
    "debug_toolbar.panels.history.HistoryPanel",
    "debug_toolbar.panels.versions.VersionsPanel",
    "debug_toolbar.panels.timer.TimerPanel",
    "debug_toolbar.panels.settings.SettingsPanel",
    "debug_toolbar.panels.headers.HeadersPanel",
    "debug_toolbar.panels.request.RequestPanel",
    "debug_toolbar.panels.sql.SQLPanel",
    "debug_toolbar.panels.staticfiles.StaticFilesPanel",
    "debug_toolbar.panels.templates.TemplatesPanel",
    "debug_toolbar.panels.cache.CachePanel",
    "debug_toolbar.panels.signals.SignalsPanel",
    "debug_toolbar.panels.logging.LoggingPanel",
    "debug_toolbar.panels.redirects.RedirectsPanel",
    "debug_toolbar.panels.profiling.ProfilingPanel",
    "cachalot.panels.CachalotPanel",
]

# Recaptcha Configuration
RECAPTCHA_KEY = os.environ.get("RECAPTCHA_SECRET")
RECAPTCHA_MIN_SCORE = 0.85

# Django Imgur
IMGUR_CONSUMER_ID = os.environ.get("IMGUR_CONSUMER_ID", "")
IMGUR_CONSUMER_SECRET = os.environ.get("IMGUR_CONSUMER_SECRET", "")
IMGUR_USERNAME = os.environ.get("IMGUR_USERNAME", "")
IMGUR_ACCESS_TOKEN = os.environ.get("IMGUR_ACCESS_TOKEN", "")
IMGUR_ACCESS_TOKEN_REFRESH = os.environ.get("IMGUR_ACCESS_TOKEN_REFRESH", "")
IMGUR_ALBUM = os.environ.get("IMGUR_ALBUM", "media")
IMGUR_PROXY_AUTH_KEY = os.environ.get("IMGUR_PROXY_AUTH_KEY", "")
IMGUR_PROXY_API_URL = os.environ.get("IMGUR_PROXY_API_URL", "")

DISCORD_MEDIA_WEBHOOK_URL = os.environ.get("DISCORD_MEDIA_WEBHOOK_URL", "")
DISCORD_MEDIA_WEBHOOK_CHANNEL = os.environ.get("DISCORD_MEDIA_WEBHOOK_CHANNEL", "")
DISCORD_MEDIA_WEBHOOK_EMBED_COLOR = os.environ.get(
    "DISCORD_MEDIA_WEBHOOK_EMBED_COLOR", "03b2f8"
)


# Celery
# http://docs.celeryproject.org/en/latest/userguide/configuration.html
if USE_TZ:
    CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_URL = f"{REDIS_URL}/{REDIS_DB}"
CELERY_REDIS_DB = REDIS_DB
CELERY_RESULT_BACKEND = "django-db"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_TIME_LIMIT = 5 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 60
CELERY_CACHE_BACKEND = "celery"
CELERY_RESULT_EXTENDED = True
CELERY_BROKER_CONNECTION_TIMEOUT = 2
CELERY_BROKER_CONNECTION_MAX_RETRY = 1
CELERY_BROKER_CONNECTION_RETRY = False

# AWS Boto
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME", "")
AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME", "")

ORACLE_NAMESPACE = os.environ.get("ORACLE_NAMESPACE", "")

AWS_S3_ENDPOINT_URL = f"https://{ORACLE_NAMESPACE}.compat.objectstorage.{AWS_S3_REGION_NAME}.oraclecloud.com"
AWS_S3_OBJECT_PARAMETERS = {
    "CacheControl": "max-age=86400",
}

MEDIA_URL = f"{AWS_S3_ENDPOINT_URL}/{AWS_STORAGE_BUCKET_NAME}/media/"

VERIFICATION_CODE_EXPIRE_MINUTES = 1

# RapidAPI Stuff
RAPID_API_KEY = os.environ.get("RAPID_API_KEY", "")
RAPID_API_NSFW_TEST_URL = "https://nsfw-image-classification1.p.rapidapi.com/img/nsfw"
RAPID_API_NSFW_HOST = "nsfw-image-classification1.p.rapidapi.com"
RAPID_API_NSFW_THRESHOLD = 0.5

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", None)
TELEGRAM_TLD = os.environ.get("TELEGRAM_TLD", None)
TELEGRAM_ADMIN_CHAT_ID = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
TELEGRAM_CLEANUP_DAYS = os.environ.get("TELEGRAM_CLEANUP_DAYS", 30)
