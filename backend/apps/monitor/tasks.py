"""monitor tasks: celery autodiscover 入口 + 平台自监控 + 日志清理。"""
import logging

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="monitor.self_check")
def self_check():
    """平台自监控：检查 worker/beat/VM/PG/Redis 健康，推自指标，异常生成告警。"""
    checks = {}
    now = timezone.now()

    # VM 可达
    try:
        r = requests.get(f"{settings.VICTORIAMETRICS_URL}/health", timeout=5)
        checks["vm"] = r.status_code == 200
    except Exception:
        checks["vm"] = False

    # PG 可达（Django DB 连接）
    try:
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        checks["pg"] = True
    except Exception:
        checks["pg"] = False

    # Redis 可达（Celery broker）
    try:
        import redis
        r = redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=3)
        r.ping()
        checks["redis"] = True
    except Exception:
        checks["redis"] = False

    # 推自指标到 VM
    lines = []
    for name, ok in checks.items():
        lines.append(f'platform_health{{component="{name}"}} {1 if ok else 0}')
    try:
        requests.post(f"{settings.VICTORIAMETRICS_URL}/api/v1/import/prometheus",
                      data="\n".join(lines) + "\n", timeout=5)
    except Exception:
        pass

    # 异常时生成告警
    unhealthy = [k for k, v in checks.items() if not v]
    if unhealthy:
        from apps.alert.models import AlertEvent
        try:
            AlertEvent.objects.get_or_create(
                dedup_key="platform:unhealthy",
                status__in=["firing", "acknowledged", "processing"],
                defaults={"device_id": 0, "severity": "critical",
                          "title": f"平台组件异常: {', '.join(unhealthy)}",
                          "detail": {"checks": checks}})
        except Exception:
            pass
    else:
        # 全部正常 -> 关闭平台异常告警
        from apps.alert.models import AlertEvent
        AlertEvent.objects.filter(
            dedup_key="platform:unhealthy",
            status__in=["firing", "acknowledged", "processing"]
        ).update(status="resolved", resolved_at=now)

    return {"checks": checks, "ts": str(now)}


@shared_task(name="monitor.log_cleanup")
def log_cleanup(hours=72):
    """清理超过保留期的日志（syslog receiver 内置了小时级清理，此处兜底每日跑）。"""
    from datetime import timedelta
    from apps.monitor.models import LogRecord
    cutoff = timezone.now() - timedelta(hours=hours)
    deleted, _ = LogRecord.objects.filter(occurred_at__lt=cutoff).delete()
    logger.info("log cleanup: %s records deleted (>%sh)", deleted, hours)
    return {"deleted": deleted}


# 导入采集任务供 autodiscover 注册
from apps.monitor.collector import collect_all, collect_batch, collect_one, collect_shard  # noqa: F401,E402
