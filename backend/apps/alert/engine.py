"""Alert engine: evaluate metric rules against VictoriaMetrics, dedup via active event (ER D3)."""
import logging

import requests
from celery import shared_task
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.alert.models import AlertEvent, AlertNotification, AlertRule
from apps.system.services import send_notification

logger = logging.getLogger(__name__)


def fire_event(rule, device_id, detail=None):
    """Create-or-bump active event; dedup_key = device:rule (partial unique in PG)."""
    dedup = f"{device_id}:{rule.id}"
    ev = AlertEvent.objects.filter(
        dedup_key=dedup, status__in=("firing", "acknowledged", "processing")).first()
    if ev:
        AlertEvent.objects.filter(pk=ev.pk).update(
            fired_count=ev.fired_count + 1, last_fired_at=timezone.now())
        return ev, False
    ev = AlertEvent.objects.create(
        dedup_key=dedup, rule_id=rule.id, device_id=device_id,
        severity=rule.severity, title=f"[{rule.name}] threshold breach",
        detail=detail or {})
    return ev, True


def notify(event, rule):
    from apps.system.models import NotifyChannel
    for cid in rule.notify_channels or []:
        ch = NotifyChannel.objects.filter(pk=cid).first()
        if ch:
            ok = send_notification(ch, f"{event.title} device={event.device_id}")
            AlertNotification.objects.create(
                event=event, channel_id=cid, target=ch.name,
                status="sent" if ok else "failed", sent_at=timezone.now() if ok else None)


def vm_query(promql) -> list:
    try:
        r = requests.get(f"{settings.VICTORIAMETRICS_URL}/api/v1/query",
                         params={"query": promql}, timeout=10)
        return r.json().get("data", {}).get("result", [])
    except Exception:
        logger.exception("vm query failed")
        return []


@shared_task(name="alert.evaluate_rules")
def evaluate_alert_rules():
    """Beat: every 60s. State rules (offline) evaluated against cmdb_device snapshot."""
    fired = 0
    now = timezone.now()
    for rule in AlertRule.objects.filter(enabled=True):
        if rule.rule_type == AlertRule.RuleType.METRIC:
            for item in vm_query(rule.metric):
                dev = (item.get("metric") or {}).get("device_id")
                if dev and eval_compare(float(item["value"][1]), rule.operator, float(rule.threshold)):
                    ev, new = fire_event(rule, int(dev))
                    if new:
                        notify(ev, rule); fired += 1
        elif rule.rule_type == AlertRule.RuleType.STATE and rule.metric == "offline":
            from django.db import connection
            with connection.cursor() as cur:
                cur.execute("SELECT id FROM cmdb_device WHERE online_status='offline' AND deleted_at IS NULL")
                for (dev_id,) in cur.fetchall():
                    ev, new = fire_event(rule, dev_id)
                    if new:
                        notify(ev, rule); fired += 1
        elif rule.rule_type == AlertRule.RuleType.LOG:
            # 日志关键字规则：近 for_duration_s(默认5min) 窗口内正则命中 -> 按设备触发
            import re as _re
            from datetime import timedelta
            from apps.monitor.models import LogRecord
            window = max(rule.for_duration_s, 300)
            since = now - timedelta(seconds=window)
            try:
                pattern = _re.compile(rule.log_pattern or rule.metric or "")
            except _re.error:
                continue
            hits = {}
            for rec in (LogRecord.objects.filter(occurred_at__gte=since, device_id__isnull=False)
                        .only("device_id", "message").iterator()):
                if pattern.search(rec.message or ""):
                    hits.setdefault(rec.device_id, rec.message[:200])
            for dev_id, sample in hits.items():
                ev, new = fire_event(rule, dev_id)
                if new:
                    ev.detail = {"sample": sample}
                    ev.save(update_fields=["detail"])
                    notify(ev, rule); fired += 1
        # silence check: skip devices inside silence window
    return {"fired_new": fired, "ts": str(now)}


def eval_compare(left, op, right):
    return {">": left > right, "<": left < right, ">=": left >= right,
            "<=": left <= right, "==": left == right, "!=": left != right}.get(op, False)
