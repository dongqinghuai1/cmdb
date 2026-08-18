"""
nops - 智能运维 CMDB 平台（Django 配置）
约定：UTC 存储（PRD 12.2-15）；全部配置走环境变量，docker-compose 注入。
"""
import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 三方
    "rest_framework",
    "rest_framework_simplejwt",
    "django_filters",
    "drf_spectacular",
    # 平台 apps（PRD 7.2.1 模块化；跨 App 只走 services，模型互不 import）
    "apps.system",
    "apps.dcim",
    "apps.cmdb",
    "apps.monitor",
    "apps.usage",
    "apps.alert",
    "apps.inspect",
    "apps.topo",
    "apps.ncm",
    "apps.ipam",
    "apps.automate",
    "apps.change",
    "apps.ai",
    "apps.report",
    "common",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

# 数据库：PostgreSQL（ER 设计依赖 JSONB/inet/EXCLUDE，开发期无 PG 时退化 SQLite 仅做语法检查）
if os.environ.get("NOPS_DB", "postgres") == "sqlite":
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3",
    }}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "nops"),
        "USER": os.environ.get("POSTGRES_USER", "nops"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "nops"),
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "UTC"          # UTC 存储，前端本地化（ER D12）
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------- DRF ----------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "common.exception_handler.api_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=int(os.environ.get("JWT_HOURS", "8"))),
    "ROTATE_REFRESH_TOKENS": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "nops API", "VERSION": "0.1.0",
    "DESCRIPTION": "智能运维 CMDB 平台开放接口（PRD 5.16）",
}

# ---------------- Celery / Redis ----------------
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
CELERY_TASK_DEFAULT_QUEUE = "nops"
CELERY_BEAT_SCHEDULE = {}  # 由各 app 的 tasks.py 通过共享 schedule 注册（见 config/celery.py）

# ---------------- 基础设施地址 ----------------
VICTORIAMETRICS_URL = os.environ.get("VM_URL", "http://victoriametrics:8428")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "")  # 一期直查模式（PRD 5.6.3 A）
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")

# 凭据加密主密钥（仅环境注入，永不入库；ER 4.3）
CRYPTO_KEY = os.environ.get("NOPS_CRYPTO_KEY", "dev-crypto-key-change-me-in-prod")

# LLM 网关（公司自建 newapi，OpenAI 兼容端点；PRD 11.1-6）
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://api.memblaze.com/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
