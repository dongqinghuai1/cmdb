from celery import shared_task
from django.utils import timezone


@shared_task(name="ncm.backup_all")
def backup_all():
    """Daily scheduled: fetch running-config for all managed devices with credentials."""
    from django.db import connection
    from apps.ncm.services import fetch_via_ssh, save_backup
    done = skipped = failed = 0
    with connection.cursor() as cur:
        cur.execute("""SELECT id FROM cmdb_device
                       WHERE deleted_at IS NULL AND credential_id IS NOT NULL AND manage_ip IS NOT NULL""")
        ids = [r[0] for r in cur.fetchall()]
    for dev_id in ids:
        cfg = fetch_via_ssh(dev_id)
        if cfg:
            save_backup(dev_id, cfg, trigger="scheduled")
            done += 1
        else:
            failed += 1
    return {"ts": str(timezone.now()), "devices": len(ids), "backed_up": done, "failed": failed}


@shared_task(name="ncm.backup_device")
def backup_device(device_id):
    from apps.ncm.services import fetch_via_ssh, save_backup
    cfg = fetch_via_ssh(device_id)
    if not cfg:
        return {"device": device_id, "ok": False, "reason": "ssh fetch failed / no credential"}
    backup, changed = save_backup(device_id, cfg, trigger="manual")
    return {"device": device_id, "ok": True, "backup": backup.id, "changed": changed}


@shared_task(name="ncm.baseline_check")
def baseline_check():
    """每日基线核查（beat 06:30）：全规则×最新备份，结果留痕 + 不合规联动告警。"""
    from apps.ncm.services import run_baseline
    r = run_baseline()
    return {"ts": r["ts"], "checked": r["checked"], "violations": r["violations"],
            "alerts_opened": r["alerts_opened"], "alerts_resolved": r["alerts_resolved"]}
