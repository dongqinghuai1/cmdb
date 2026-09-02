"""NCM services: backup save with sha256 dedup + change-event diff; SSH fetch; baseline check."""
import difflib
import hashlib
import logging
import re

from django.utils import timezone

logger = logging.getLogger(__name__)

# netmiko device_type map per platform driver (PRD 5.6.1)
DRIVER_MAP = {
    "h3c_comware": "hp_comware",
    "cisco_asa": "cisco_asa",
    "cisco_wlc_3504": "cisco_wlc",
    "cisco_wlc_9800": "cisco_wlc",
    "fortigate": "fortinet",
}


def save_backup(device_id, content, trigger="manual", backup_type="running"):
    """Dedup by sha256; create change event with unified diff when content changed."""
    from apps.ncm.models import ConfigBackup, ConfigChangeEvent
    content = content or ""
    h = hashlib.sha256(content.encode()).hexdigest()
    last = ConfigBackup.objects.filter(device_id=device_id).first()
    if last and last.file_hash == h:
        return last, False  # unchanged
    backup = ConfigBackup.objects.create(
        device_id=device_id, backup_type=backup_type, trigger=trigger,
        content=content, size=len(content), file_hash=h)
    if last:
        old = (last.content or "").splitlines()
        new = content.splitlines()
        diff = "\n".join(difflib.unified_diff(old, new, fromfile="previous", tofile="current", lineterm=""))
        changed = sum(1 for l in diff.splitlines() if l[:1] in "+-" and l[:3] not in ("+++", "---"))
        event = ConfigChangeEvent.objects.create(
            device_id=device_id, old_backup_id=last.id, new_backup_id=backup.id,
            changed_lines=changed, diff_text=diff)
        _fire_change_alert(device_id, event, changed)
    return backup, True


def _fire_change_alert(device_id, event, changed_lines):
    """Config change -> info alert event via shared dedup table (PRD 12.2-14 思路)."""
    try:
        from apps.alert.models import AlertEvent
        from apps.system.services import send_notification
        from apps.system.models import NotifyChannel
        dedup = f"{device_id}:config_change:{event.id}"
        AlertEvent.objects.create(
            dedup_key=dedup, device_id=device_id, severity="warning",
            title=f"配置变更：{changed_lines} 行变化", detail={"event": event.id})
        for ch in NotifyChannel.objects.filter(enabled=True, channel_type="feishu"):
            send_notification(ch, f"[nops] 设备 {device_id} 配置变更 {changed_lines} 行")
    except Exception:
        logger.exception("config change alert failed")


def fetch_via_ssh(device_id):
    """Best-effort config fetch via netmiko. Returns config text or None."""
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute("""SELECT manage_ip, driver_type, credential_id FROM cmdb_device WHERE id=%s""", [device_id])
        row = cur.fetchone()
    if not row or not row[0] or not row[2]:
        return None
    host, driver_type, cred_id = row
    try:
        from netmiko import ConnectHandler
        from apps.system.models import Credential
        cred = Credential.objects.filter(pk=cred_id).first()
        if not cred:
            return None
        conn = {
            "device_type": DRIVER_MAP.get(driver_type, "cisco_ios"),
            "host": host,
            "username": cred.username or "admin",
            "password": cred.secret,
            "timeout": 15, "global_delay_factor": 2,
        }
        show = "display current-configuration" if conn["device_type"] == "hp_comware" else "show running-config"
        with ConnectHandler(**conn) as net:
            return net.send_command(show)
    except Exception:
        logger.exception("SSH config fetch failed device=%s", device_id)
        return None


def _device_meta(device_ids):
    """CMDB 设备元信息（跨域只读：函数内导入，仓库既有先例）。"""
    if not device_ids:
        return {}
    from apps.cmdb.models import Device
    return {d.id: {"name": d.name, "driver_type": d.driver_type, "region_id": d.region_id}
            for d in Device.objects.filter(id__in=list(device_ids), deleted_at__isnull=True)}


def _in_scope(rule, meta, device_id):
    """规则 scope（JSON）：device_ids / driver_types / regions 任一存在即须命中；空 scope=全量。"""
    scope = rule.scope or {}
    if scope.get("device_ids") and device_id not in scope["device_ids"]:
        return False
    if scope.get("driver_types") and (meta or {}).get("driver_type") not in scope["driver_types"]:
        return False
    if scope.get("regions") and (meta or {}).get("region_id") not in scope["regions"]:
        return False
    return True


def _sync_baseline_alert(rule, device_id, result):
    """基线结果 -> AlertEvent（dedup: {device}:baseline:{rule}）。violation 开/续、合规即关。"""
    try:
        from apps.alert.models import AlertEvent
        from django.utils import timezone
        key = f"{device_id}:baseline:{rule.id}"
        active = AlertEvent.objects.filter(
            dedup_key=key, status__in=("firing", "acknowledged", "processing")).first()
        if not result.compliant:
            detail = {"result_id": result.id, "rule_name": rule.name,
                      "severity": rule.severity,
                      "matched": (result.matched_content or "")[:400]}
            title = f"安全基线不合规[{rule.name}] device={device_id}"
            if active:
                AlertEvent.objects.filter(pk=active.pk).update(
                    fired_count=active.fired_count + 1, title=title[:255],
                    detail=detail, last_fired_at=timezone.now())
                return "updated"
            AlertEvent.objects.create(
                dedup_key=key, device_id=device_id, rule_id=rule.id,
                severity=rule.severity, title=title[:255], detail=detail, status="firing")
            return "opened"
        if active:
            AlertEvent.objects.filter(pk=active.pk).update(
                status="resolved", resolved_at=timezone.now())
            return "resolved"
    except Exception:
        logger.exception("baseline alert sync failed rule=%s device=%s", rule.id, device_id)
    return None


def run_baseline(rule_ids=None, device_ids=None):
    """安全基线核查：每设备最新备份 × 每条规则 → 结果留痕 + 不合规联动告警。

    rule.scope（device_ids/driver_types/regions）生效；device_ids 参数额外限定设备。
    返回 {checked, devices, violations, by_rule, alerts_opened/updated/resolved, ts}。
    """
    from apps.ncm.models import BaselineCheckResult, BaselineRule, ConfigBackup
    rules = list(BaselineRule.objects.filter(pk__in=rule_ids)
                 if rule_ids else BaselineRule.objects.all())
    backups = {}
    for b in ConfigBackup.objects.order_by("-created_at"):
        backups.setdefault(b.device_id, b)   # setdefault 首见即最新
    dev_ids = sorted(set(backups) - {None})
    if device_ids:
        wanted = set(int(x) for x in device_ids)
        dev_ids = [d for d in dev_ids if d in wanted]
    meta = _device_meta(dev_ids)
    checked = violations = compliant_n = opened = updated = resolved = 0
    viol_rows, by_rule = [], []
    for rule in rules:
        rule_viol = 0
        for dev_id in dev_ids:
            if not _in_scope(rule, meta.get(dev_id), dev_id):
                continue
            content = backups[dev_id].content or ""
            hit_lines = [l for l in content.splitlines() if re.search(rule.pattern, l)]
            ok = bool(hit_lines) if rule.rule_type == "must_present" else not hit_lines
            res = BaselineCheckResult.objects.create(
                rule=rule, device_id=dev_id, compliant=ok,
                matched_content="\n".join(hit_lines[:20]))
            act = _sync_baseline_alert(rule, dev_id, res)
            opened += act == "opened"; updated += act == "updated"; resolved += act == "resolved"
            checked += 1
            if ok:
                compliant_n += 1
            else:
                violations += 1; rule_viol += 1
                if len(viol_rows) < 50:
                    m = meta.get(dev_id) or {}
                    viol_rows.append({"rule_id": rule.id, "rule_name": rule.name,
                                      "severity": rule.severity, "device_id": dev_id,
                                      "device_name": m.get("name"), "result_id": res.id})
        if rule_viol:
            by_rule.append({"rule_id": rule.id, "rule_name": rule.name,
                            "severity": rule.severity, "violations": rule_viol})
    return {"checked": checked, "devices": len(dev_ids), "compliant": compliant_n,
            "violations": violations, "by_rule": by_rule[:20], "violation_rows": viol_rows,
            "alerts_opened": opened, "alerts_updated": updated, "alerts_resolved": resolved,
            "ts": str(timezone.now())}
