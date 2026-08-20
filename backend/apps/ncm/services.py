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


def run_baseline(rule_ids=None):
    """must_present/must_absent regex per line against latest backup of each device."""
    from apps.ncm.models import BaselineCheckResult, BaselineRule, ConfigBackup
    results = []
    rules = BaselineRule.objects.filter(pk__in=rule_ids) if rule_ids else BaselineRule.objects.all()
    backups = {b.device_id: b for b in ConfigBackup.objects.order_by("device_id", "-created_at")}
    seen = set()
    for b in ConfigBackup.objects.order_by("-created_at"):
        if b.device_id not in backups and b.device_id not in seen:
            backups[b.device_id] = b
            seen.add(b.device_id)
    for rule in rules:
        for dev_id, backup in backups.items():
            hit_lines = [l for l in (backup.content or "").splitlines() if re.search(rule.pattern, l)]
            ok = bool(hit_lines) if rule.rule_type == "must_present" else not hit_lines
            results.append(BaselineCheckResult.objects.create(
                rule=rule, device_id=dev_id, compliant=ok,
                matched_content="\n".join(hit_lines[:20])))
    return len(results)
