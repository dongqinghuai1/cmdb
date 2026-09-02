"""alert 服务层：跨 app 联动静默（ER D4：占用/维护窗口自动静默）。

占用(借出)自动静默：cmdb usage-claim borrow/return 经本层创建/结束 occupation 静默，
使借出的设备在占用期间不进告警（scope.device_ids 对 evaluate 生效）。
"""
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def occupation_begin(device_id, usage_event_id, user_id, counterparty=""):
    """借出占用 → 建 occupation 静默（幂等：同设备已有未结束占用静默则不重复建）。"""
    from apps.alert.models import AlertSilence
    device_id = int(device_id)
    existing = AlertSilence.objects.filter(
        silence_type="occupation", ended_at__isnull=True).order_by("-id")
    for s in existing:
        if device_id in (s.scope or {}).get("device_ids", []):
            return s.pk  # 已静默（重复借出已被 usage-claim 拦截，兜底幂等）
    reason = "设备借出占用自动静默"
    if counterparty:
        reason += f"（{counterparty}）"
    s = AlertSilence.objects.create(
        scope={"device_ids": [device_id]}, silence_type="occupation",
        device_usage_id=usage_event_id, reason=reason[:255],
        started_at=timezone.now(), created_by_id=user_id)
    return s.pk


def occupation_end(device_id, user_id=None):
    """归还 → 结束该设备全部未结束的 occupation 静默（幂等，可反复执行）。"""
    from apps.alert.models import AlertSilence
    device_id = int(device_id)
    ended = 0
    for s in AlertSilence.objects.filter(
            silence_type="occupation", ended_at__isnull=True).order_by("-id"):
        if device_id in (s.scope or {}).get("device_ids", []):
            s.ended_at = timezone.now()
            s.save(update_fields=["ended_at", "updated_at"])
            ended += 1
    return ended
