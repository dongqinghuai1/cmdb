"""告警引擎完整版：fire + auto-resolve + 升级 + 通知重试 + 风暴抑制。"""
import logging
import re
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.db.models import F
from django.utils import timezone

from apps.alert.models import (AlertEvent, AlertNotification, AlertRule,
                               AlertSilence)
from apps.system.services import send_notification

logger = logging.getLogger(__name__)


def silenced_device_ids() -> set:
    now = timezone.now()
    qs = (AlertSilence.objects.filter(started_at__lte=now, ended_at__isnull=True) |
          AlertSilence.objects.filter(started_at__lte=now, ended_at__gt=now)).distinct()
    all_muted = False
    ids = set()
    for s in qs:
        scope = s.scope or {}
        if scope.get("all"):
            all_muted = True
        ids.update(scope.get("device_ids") or [])
    return {"*"} if all_muted else ids


def _is_muted(dev_id, muted):
    return "*" in muted or dev_id in muted


def fire_event(rule, device_id, detail=None, title=None):
    """并发安全：filter -> create -> IntegrityError 捕获重查。"""
    dedup = f"{device_id}:{rule.id}"
    ev = AlertEvent.objects.filter(
        dedup_key=dedup, status__in=("firing", "acknowledged", "processing")).first()
    if ev:
        AlertEvent.objects.filter(pk=ev.pk).update(
            fired_count=F("fired_count") + 1, last_fired_at=timezone.now())
        return ev, False
    try:
        ev = AlertEvent.objects.create(
            dedup_key=dedup, rule_id=rule.id, device_id=device_id,
            severity=rule.severity,
            title=title or f"[{rule.name}] threshold breach",
            detail=detail or {})
        return ev, True
    except Exception:
        ev = AlertEvent.objects.filter(
            dedup_key=dedup, status__in=("firing", "acknowledged", "processing")).first()
        if ev:
            return ev, False
        raise


def notify(event, rule):
    """通知带 3 次重试 + 每次写 AlertNotification。"""
    from apps.system.models import NotifyChannel
    for cid in rule.notify_channels or []:
        ch = NotifyChannel.objects.filter(pk=cid).first()
        if not ch:
            continue
        for attempt in range(3):
            ok = send_notification(ch, f"{event.title} device={event.device_id}")
            AlertNotification.objects.create(
                event=event, channel_id=cid, target=ch.name,
                status="sent" if ok else "failed", retry_count=attempt,
                sent_at=timezone.now() if ok else None,
                error="" if ok else f"attempt {attempt + 1}/3 failed")
            if ok:
                break
        else:
            logger.error("notify failed 3x event=%s channel=%s", event.id, cid)


def vm_query(promql):
    try:
        r = requests.get(f"{settings.VICTORIAMETRICS_URL}/api/v1/query",
                         params={"query": promql}, timeout=10)
        return r.json().get("data", {}).get("result", [])
    except Exception:
        logger.exception("vm query failed")
        return []


def eval_compare(left, op, right):
    return {">": left > right, "<": left < right, ">=": left >= right,
            "<=": left <= right, "==": left == right, "!=": left != right}.get(op, False)


@shared_task(name="alert.evaluate_rules")
def evaluate_alert_rules():
    fired = 0
    muted = silenced_device_ids()
    now = timezone.now()

    for rule in AlertRule.objects.filter(enabled=True):
        if rule.rule_type == AlertRule.RuleType.METRIC:
            for item in vm_query(rule.metric):
                dev = (item.get("metric") or {}).get("device_id")
                if not dev or _is_muted(int(dev), muted):
                    continue
                if eval_compare(float(item["value"][1]), rule.operator, float(rule.threshold)):
                    ev, new = fire_event(rule, int(dev))
                    if new:
                        notify(ev, rule); fired += 1

        elif rule.rule_type == AlertRule.RuleType.STATE and rule.metric == "offline":
            from django.db import connection
            with connection.cursor() as cur:
                cur.execute("SELECT id FROM cmdb_device WHERE online_status='offline' AND deleted_at IS NULL")
                for (dev_id,) in cur.fetchall():
                    if _is_muted(dev_id, muted):
                        continue
                    ev, new = fire_event(rule, dev_id)
                    if new:
                        notify(ev, rule); fired += 1

        elif rule.rule_type == AlertRule.RuleType.LOG:
            from apps.monitor.models import LogRecord
            window = max(rule.for_duration_s, 300)
            since = now - timedelta(seconds=window)
            try:
                pattern = re.compile(rule.log_pattern or rule.metric or "")
            except re.error:
                continue
            hits = {}
            for rec in (LogRecord.objects
                        .filter(occurred_at__gte=since, device_id__isnull=False)
                        .only("device_id", "message")[:1000]):
                if pattern.search(rec.message or ""):
                    hits.setdefault(rec.device_id, rec.message[:200])
            for dev_id, sample in hits.items():
                if _is_muted(dev_id, muted):
                    continue
                ev, new = fire_event(rule, dev_id, detail={"sample": sample})
                if new:
                    notify(ev, rule); fired += 1

    return {"fired_new": fired, "ts": str(now)}


# ---------- 自动恢复 ----------

@shared_task(name="alert.auto_resolve")
def auto_resolve():
    resolved_count = 0
    now = timezone.now()

    for ev in AlertEvent.objects.filter(status__in=("firing", "acknowledged", "processing")):
        rule = AlertRule.objects.filter(pk=ev.rule_id).first()
        if not rule:
            continue
        should = False
        if rule.rule_type == AlertRule.RuleType.STATE and rule.metric == "offline":
            from django.db import connection
            with connection.cursor() as cur:
                cur.execute("SELECT online_status FROM cmdb_device WHERE id=%s", [ev.device_id])
                row = cur.fetchone()
            if row and row[0] != "offline":
                should = True
        elif rule.rule_type == AlertRule.RuleType.METRIC:
            results = vm_query(rule.metric)
            still = False
            for item in results:
                dev = (item.get("metric") or {}).get("device_id")
                if dev and int(dev) == ev.device_id:
                    if eval_compare(float(item["value"][1]), rule.operator, float(rule.threshold)):
                        still = True
                    break
            if not still:
                should = True
        elif rule.rule_type == AlertRule.RuleType.LOG:
            from apps.monitor.models import LogRecord
            window = max(rule.for_duration_s, 300)
            since = now - timedelta(seconds=window)
            try:
                pattern = re.compile(rule.log_pattern or rule.metric or "")
                recent = LogRecord.objects.filter(
                    occurred_at__gte=since, device_id=ev.device_id).only("message")[:100]
                if not any(pattern.search(r.message or "") for r in recent):
                    should = True
            except re.error:
                pass

        if should:
            ev.status = "resolved"
            ev.resolved_at = now
            ev.save(update_fields=["status", "resolved_at"])
            resolved_count += 1
            for cid in rule.notify_channels or []:
                from apps.system.models import NotifyChannel
                ch = NotifyChannel.objects.filter(pk=cid).first()
                if ch:
                    send_notification(ch, f"[恢复] {ev.title} device={ev.device_id} 已恢复正常")

    return {"resolved": resolved_count, "ts": str(now)}


# ---------- 升级检查 ----------

@shared_task(name="alert.check_escalation")
def check_escalation():
    from apps.alert.models import AlertEscalationRule
    escalated = 0
    now = timezone.now()
    for esc_rule in AlertEscalationRule.objects.all():
        cutoff = now - timedelta(minutes=esc_rule.timeout_min)
        for ev in AlertEvent.objects.filter(
                status="firing", severity=esc_rule.severity,
                acked_at__isnull=True, first_fired_at__lt=cutoff):
            if esc_rule.last_fired_at and \
               (now - esc_rule.last_fired_at).total_seconds() < esc_rule.timeout_min * 60:
                continue
            for cid in esc_rule.channel_ids or []:
                from apps.system.models import NotifyChannel
                ch = NotifyChannel.objects.filter(pk=cid).first()
                if ch:
                    send_notification(ch, f"[升级] {ev.title} device={ev.device_id} "
                                       f"超过 {esc_rule.timeout_min} 分钟未确认")
            AlertEscalationRule.objects.filter(pk=esc_rule.pk).update(
                fired_count=F("fired_count") + 1, last_fired_at=now)
            escalated += 1
    return {"escalated": escalated, "ts": str(now)}
