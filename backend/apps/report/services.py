"""apps.report 服务层：指标聚合（各 app 只读统计，不新起采集）→ 报表快照持久化/推送。

聚合全部使用各 app 模型 ORM 轻查询（sqlite/PG 通用）；时间窗由调用方定，默认今天。
跨 App 引用一律函数内延迟导入（仓库纪律）。
"""
import logging
import time
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

logger = logging.getLogger(__name__)


def _today_start():
    now = timezone.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


# ============ 各类型聚合 ============

def _snapshot_inventory(start, end):
    """设备台账：总量/在线/厂商/站点/今日新增。"""
    from apps.cmdb.models import Device
    total = Device.objects.count()
    by_status = dict(Device.objects.order_by()
                     .values_list("online_status").annotate(c=Count("id")))
    by_vendor = list(Device.objects.order_by()
                     .values("vendor").annotate(c=Count("id")).order_by("-c")[:8])
    by_site = list(Device.objects.order_by()
                   .values("site").annotate(c=Count("id")).order_by("-c")[:8])
    added = Device.objects.filter(created_at__gte=start, created_at__lte=end).count()
    summary = f"设备总数 {total}（在线 {by_status.get('online', 0)} / 离线 {by_status.get('offline', 0)}），今日新增 {added}"
    return {"summary": summary, "total": total, "by_status": by_status,
            "by_vendor": by_vendor, "by_site": by_site, "added_today": added}


def _snapshot_alerts(start, end):
    """告警态势：状态/级别分布、周期新增与恢复、抑制数、Top 规则。"""
    from apps.alert.models import AlertEvent, AlertRule
    total = AlertEvent.objects.count()
    by_status = dict(AlertEvent.objects.order_by().values_list("status").annotate(c=Count("id")))
    by_sev = dict(AlertEvent.objects.order_by().values_list("severity").annotate(c=Count("id")))
    new_in_period = AlertEvent.objects.filter(first_fired_at__gte=start, first_fired_at__lte=end).count()
    resolved_in_period = AlertEvent.objects.filter(
        status="resolved", resolved_at__gte=start, resolved_at__lte=end).count()
    suppressed_active = AlertEvent.objects.filter(
        status__in=("firing", "acknowledged", "processing"),
        suppressed_by_id__isnull=False).count()
    top = list(AlertEvent.objects.order_by()
               .values("rule_id").annotate(c=Count("id")).order_by("-c")[:5])
    rule_names = {r["id"]: r["name"] for r in
                  AlertRule.objects.filter(id__in=[t["rule_id"] for t in top if t["rule_id"]])
                  .values("id", "name")}
    top_rules = [{"rule_id": t["rule_id"], "rule": rule_names.get(t["rule_id"], "-"),
                  "count": t["c"]} for t in top]
    active = sum(by_status.get(s, 0) for s in ("firing", "acknowledged", "processing"))
    summary = (f"告警事件共 {total}（活跃 {active} / 已恢复 {by_status.get('resolved', 0)}），"
               f"周期内新增 {new_in_period} / 恢复 {resolved_in_period}，"
               f"根因抑制中 {suppressed_active}")
    return {"summary": summary, "total": total, "by_status": by_status,
            "by_severity": by_sev, "new_in_period": new_in_period,
            "resolved_in_period": resolved_in_period, "suppressed_active": suppressed_active,
            "top_rules": top_rules}


def _snapshot_changes(start, end):
    """变更/事件：变更单与事件单状态分布、周期新增/收尾。"""
    from apps.change.models import ChangeTicket, IncidentTicket
    ct_by = dict(ChangeTicket.objects.order_by().values_list("status").annotate(c=Count("id")))
    it_by = dict(IncidentTicket.objects.order_by().values_list("status").annotate(c=Count("id")))
    ct_new = ChangeTicket.objects.filter(created_at__gte=start, created_at__lte=end).count()
    it_new = IncidentTicket.objects.filter(created_at__gte=start, created_at__lte=end).count()
    summary = (f"变更单共 {sum(ct_by.values())}（审批中 {ct_by.get('approving', 0)} / "
               f"实施中 {ct_by.get('implementing', 0)} / 关闭 {ct_by.get('closed', 0)}），"
               f"事件单共 {sum(it_by.values())}，周期内新增变更 {ct_new} / 事件 {it_new}")
    return {"summary": summary, "change_by_status": ct_by, "incident_by_status": it_by,
            "change_new_in_period": ct_new, "incident_new_in_period": it_new}


def _snapshot_ncm(start, end):
    """配置/基线：备份覆盖设备、周期内备份数、基线最近合规率、配置变更事件。"""
    from apps.ncm.models import (BaselineCheckResult, ConfigBackup,
                                 ConfigChangeEvent)
    backed = len(set(ConfigBackup.objects.order_by()
                     .values_list("device_id", flat=True)))
    backups_in_period = ConfigBackup.objects.filter(
        created_at__gte=start, created_at__lte=end).count()
    change_events_in_period = ConfigChangeEvent.objects.filter(
        created_at__gte=start, created_at__lte=end).count()
    recent = list(BaselineCheckResult.objects.order_by("-id")[:500])
    bl_total, bl_ok = len(recent), sum(1 for r in recent if r.compliant)
    rule_hits = BaselineCheckResult.objects.order_by().values("rule_id") \
        .annotate(c=Count("id")).order_by("-c")[:5]
    summary = (f"配置备份覆盖 {backed} 台设备（周期内新增 {backups_in_period} 次），"
               f"基线抽查 {bl_total} 项、合规 {bl_ok} 项"
               + (f"（合规率 {round(100.0 * bl_ok / bl_total, 1)}%）" if bl_total else ""))
    return {"summary": summary, "backed_device_count": backed,
            "backups_in_period": backups_in_period,
            "change_events_in_period": change_events_in_period,
            "baseline_checked": bl_total, "baseline_compliant": bl_ok}


_BUILDERS = {
    "inventory": _snapshot_inventory,
    "alerts": _snapshot_alerts,
    "changes": _snapshot_changes,
    "ncm": _snapshot_ncm,
}


def build_snapshot(report_type, start=None, end=None):
    """聚合一种报表（不落库）。"""
    from apps.report.models import ReportSnapshot
    if report_type not in ReportSnapshot.Type.values:
        raise ValueError(f"报表类型不合法: {report_type}")
    start = start or _today_start()
    end = end or timezone.now()
    builder = _BUILDERS.get(report_type)
    content = builder(start, end) if builder else {"summary": "no builder", "empty": True}
    return {"report_type": report_type, "period_start": start, "period_end": end,
            "content": content}


def save_snapshot(report_type, period_start=None, built_by="manual", remark=""):
    """构建并按 (type, period_start) 幂等落库。"""
    from apps.report.models import ReportSnapshot
    t0 = time.monotonic()
    built = build_snapshot(report_type, period_start)
    start = built["period_start"]
    snap, _ = ReportSnapshot.objects.update_or_create(
        report_type=report_type, period_start=start,
        defaults={"period_end": built["period_end"], "content": built["content"],
                  "built_by": built_by, "remark": remark,
                  "duration_ms": int((time.monotonic() - t0) * 1000)})
    return {"id": snap.pk, "report_type": report_type,
            "period_start": snap.period_start.isoformat(), "content": snap.content,
            "built_by": snap.built_by, "remark": snap.remark}


# ============ 周期任务 ============

def daily_snapshot_task():
    """每日：为每个启用订阅生成当日快照并推送到其通知渠道（best-effort）。"""
    from apps.report.models import ReportSchedule, ReportSnapshot
    built = []
    now = timezone.now()
    for s in ReportSchedule.objects.filter(enabled=True).order_by("id"):
        try:
            r = save_snapshot(s.report_type, built_by="auto",
                              remark=f"订阅[{s.name}] 每日快照")
            s.last_run_at = now
            s.save(update_fields=["last_run_at", "updated_at"])
            built.append({"schedule": s.name, "report_type": s.report_type,
                          "id": r["id"]})
            # 通知（失败不影响主流程）
            for cid in s.notify_channel_ids or []:
                try:
                    from apps.system.models import NotifyChannel
                    from apps.system.services import send_notification
                    ch = NotifyChannel.objects.filter(pk=cid).first()
                    if ch:
                        send_notification(ch, f"[报表] {s.name} {r['content'].get('summary', '')}")
                except Exception:  # noqa: BLE001
                    logger.warning("report notify failed sched=%s chan=%s", s.id, cid)
        except Exception as e:  # noqa: BLE001
            logger.exception("report daily failed sched=%s", s.id)
            built.append({"schedule": s.name, "error": str(e)[:200]})
    return {"built": len(built), "items": built, "ts": str(now)}
