"""apps.inspect -- inspection templates/tasks/results (ER 4.7)."""
from django.db import models

from common.models import TimeStampedModel


class InspectTemplate(TimeStampedModel):
    name = models.CharField(max_length=64, unique=True)
    description = models.CharField(max_length=255, blank=True)
    enabled = models.BooleanField(default=True)


class InspectItem(TimeStampedModel):
    class CheckType(models.TextChoices):
        THRESHOLD = "threshold"; STATUS_EXPECT = "status_expect"; SCRIPT = "script"; COMPOSITE = "composite"

    template = models.ForeignKey(InspectTemplate, on_delete=models.CASCADE, related_name="items")
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=128)
    check_type = models.CharField(max_length=16, choices=CheckType.choices, default=CheckType.THRESHOLD)
    metric = models.CharField(max_length=128, blank=True)
    operator = models.CharField(max_length=8, default=">")
    threshold_value = models.DecimalField(max_digits=16, decimal_places=3, null=True, blank=True)
    expected_value = models.CharField(max_length=128, blank=True)
    weight = models.IntegerField(default=1)
    severity = models.CharField(max_length=8, default="warning")

    class Meta:
        unique_together = ("template", "code")


class InspectTask(TimeStampedModel):
    name = models.CharField(max_length=64)
    template = models.ForeignKey(InspectTemplate, on_delete=models.CASCADE, related_name="tasks")
    cron = models.CharField(max_length=32, blank=True)
    scope = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)


class InspectRun(TimeStampedModel):
    task = models.ForeignKey(InspectTask, null=True, blank=True, on_delete=models.SET_NULL, related_name="runs")
    template = models.ForeignKey(InspectTemplate, on_delete=models.PROTECT)
    trigger_type = models.CharField(max_length=8, default="cron")
    status = models.CharField(max_length=8, default="running")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    total_devices = models.IntegerField(default=0)
    abnormal_devices = models.IntegerField(default=0)
    health_score_avg = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    report_url = models.CharField(max_length=512, blank=True)


class InspectRunDevice(models.Model):
    run = models.ForeignKey(InspectRun, on_delete=models.CASCADE, related_name="device_results")
    device_id = models.BigIntegerField(db_index=True)
    health_score = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    pass_count = models.IntegerField(default=0)
    warn_count = models.IntegerField(default=0)
    fail_count = models.IntegerField(default=0)

    class Meta:
        unique_together = ("run", "device_id")


class InspectResult(models.Model):
    run = models.ForeignKey(InspectRun, on_delete=models.CASCADE, related_name="results")
    device_id = models.BigIntegerField()
    item = models.ForeignKey(InspectItem, on_delete=models.PROTECT)
    status = models.CharField(max_length=8, default="pass")  # pass/warn/fail/skip
    actual_value = models.CharField(max_length=255, blank=True)
    message = models.TextField(blank=True)
