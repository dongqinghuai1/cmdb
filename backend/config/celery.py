"""Celery 应用与周期任务调度（beat）。"""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_SECRET_KEY", "dev-insecure-key")

app = Celery("nops")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    # 告警评估（指标阈值/离线状态/日志关键字）：每 60 秒
    "alert-evaluate-rules": {"task": "alert.evaluate_rules", "schedule": 60.0},
    # NCM 全量配置备份：每日 02:30
    "ncm-backup-all": {"task": "ncm.backup_all", "schedule": crontab(hour=2, minute=30)},
}


def register_beat(name, task, schedule, **kwargs):
    """各 App 动态注册入口（追加后需重启 beat 生效）。"""
    app.conf.beat_schedule[name] = {"task": task, "schedule": schedule, **kwargs}
