"""cmdb 保修到期快照/提醒（5.5.7 待办收尾：30/60/90/180 + 已过期 → 通知推送）。"""
from datetime import date, timedelta


def warranty_snapshot(within_days=90, today=None):
    """保修汇总口径与清单（与 GET warranty-expiring 一致；today 注入便于测试）。"""
    from apps.cmdb.models import Device
    today = today or date.today()
    days = min(int(within_days), 730)
    qs = Device.objects.filter(deleted_at__isnull=True, warranty_until__isnull=False)
    expired_qs = qs.filter(warranty_until__lt=today)
    expiring = qs.filter(warranty_until__gte=today,
                         warranty_until__lte=today + timedelta(days=days))
    summary = {"expired": expired_qs.count(),
               **{str(d): qs.filter(warranty_until__gt=today,
                                    warranty_until__lte=today + timedelta(days=d)).count()
                  for d in (30, 60, 90, 180)}}
    rows = []
    for dev in list(expiring.order_by("warranty_until")[:200]) \
             + list(expired_qs.order_by("-warranty_until")[:100]):
        rows.append({
            "id": dev.id, "name": dev.name, "manage_ip": str(dev.manage_ip or ""),
            "vendor": dev.vendor, "hw_model": dev.hw_model,
            "warranty_until": dev.warranty_until,
            "days_left": (dev.warranty_until - today).days,
            "owner": dev.owner.username if dev.owner else None,
            "region_name": dev.region.name if dev.region else None,
            "site_name": dev.site.name if dev.site else None,
        })
    return {"summary": summary, "within_days": days, "rows": rows}


def build_message(snap: dict) -> str:
    s = snap["summary"]
    lines = [
        "【CMDB 保修到期提醒】",
        f"已过期 {s['expired']} 台；30 天内 {s['30']} 台，60 天内 {s['60']} 台，"
        f"90 天内 {s['90']} 台，180 天内 {s['180']} 台。",
    ]
    if snap["rows"]:
        head = [r for r in snap["rows"] if r["days_left"] <= 30 or r["days_left"] < 0][:20]
        for r in head:
            flag = "已过期" if r["days_left"] < 0 else f"{r['days_left']} 天后"
            lines.append(f"- {r['name']}（{r.get('vendor') or '?'} "
                         f"{r.get('hw_model') or '?'}）：{r['warranty_until']}（{flag}）")
    return "\n".join(lines)


def notify_warranty(within_days=90, dry=False, channels=None, today=None):
    """推送保修提醒。channels=None 取全部 enabled 通知渠道；dry=True 只回显不实发。"""
    from apps.system.models import NotifyChannel
    snap = warranty_snapshot(within_days=within_days, today=today)
    text = build_message(snap)
    chs = list(channels) if channels is not None else list(
        NotifyChannel.objects.filter(enabled=True))
    results = []
    for ch in chs:
        if dry:
            results.append({"channel_id": ch.pk, "channel_type": ch.channel_type,
                            "dry": True, "sent": True})
            continue
        try:
            from apps.system.services import send_notification
            ok = send_notification(ch, text)
        except Exception as e:  # noqa: BLE001 —— 单个渠道失败不影响其余
            ok = False
        results.append({"channel_id": ch.pk, "channel_type": ch.channel_type,
                        "dry": False, "sent": bool(ok)})
    return {"summary": snap["summary"], "within_days": snap["within_days"],
            "rows": snap["rows"], "channels": results}
