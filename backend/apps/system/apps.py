import hashlib
import time

from django.apps import AppConfig


class SystemConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.system"

    def ready(self):
        from config import celery as _celery  # noqa: F401 注册 beat（system 无周期任务则空）
