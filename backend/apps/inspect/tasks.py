"""Inspect engine: threshold/status checks on PG snapshots; abnormal -> alert event (ER 12.2-14)."""
from celery import shared_task
from django.utils import timezone


@shared_task(name="inspect.run")
def run_inspect(task_id=None, template_id=None):
    from apps.alert.models import AlertRule
    from apps.inspect.models import (InspectItem, InspectResult, InspectRun,
                                     InspectRunDevice, InspectTask)
    from django.db import connection
    task = InspectTask.objects.filter(pk=task_id).first() if task_id else None
    if task:
        template = task.template
    else:
        from apps.inspect.models import InspectTemplate
        template = InspectTemplate.objects.get(pk=template_id)
    run = InspectRun.objects.create(task=task, template=template,
                                    trigger_type="cron" if task else "manual")
    with connection.cursor() as cur:
        cur.execute("""SELECT id, online_status FROM cmdb_device
                       WHERE deleted_at IS NULL AND lifecycle_status='deployed'""")
        devices = cur.fetchall()
    run.total_devices = len(devices)
    items = list(template.items.all())
    abnormal = 0
    for dev_id, online in devices:
        passes = fails = 0
        for it in items:
            status, actual = "pass", ""
            if it.check_type == InspectItem.CheckType.STATUS_EXPECT and it.metric == "online":
                actual = online
                if it.expected_value and online != it.expected_value:
                    status = "fail"
            elif it.check_type == InspectItem.CheckType.THRESHOLD and it.metric == "interface_errors_rate":
                with connection.cursor() as cur:
                    cur.execute("""SELECT COALESCE(MAX(GREATEST(s.in_errors_rate, s.out_errors_rate)),0)
                                   FROM cmdb_deviceinterfacestat s JOIN cmdb_deviceinterface i ON i.id=s.interface_id
                                   WHERE i.device_id=%s""", [dev_id])
                    actual = str(float(cur.fetchone()[0]))
                    if float(actual) > float(it.threshold_value or 0):
                        status = "warn"
            InspectResult.objects.create(run=run, device_id=dev_id, item=it,
                                         status=status, actual_value=actual)
            fails += status == "fail"
            passes += status == "pass"
        if fails:
            abnormal += 1
        InspectRunDevice.objects.create(run=run, device_id=dev_id,
                                        pass_count=passes, fail_count=fails,
                                        health_score=100 * passes // max(len(items), 1))
    run.abnormal_devices = abnormal
    run.status = "success"
    run.finished_at = timezone.now()
    run.save(update_fields=["abnormal_devices", "status", "finished_at", "total_devices"])
    return {"run": run.id, "total": run.total_devices, "abnormal": abnormal}
