"""Celery 应用。共享 beat schedule 由各 app 的 tasks.register_schedule() 注入。"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_SECRET_KEY", "dev-insecure-key")

app = Celery("nops")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

BEAT_SCHEDULE = {}


def register_beat(name, task, schedule, **kwargs):
    """各 app 启动时注册周期任务（避免集中硬编码）。"""
    BEAT_SCHEDULE[name] = {"task": task, "schedule": schedule, **kwargs}


app.conf.beat_schedule = BEAT_SCHEDULE  # tasks import 后由 AppConfig.ready 刷新
