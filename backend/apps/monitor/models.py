"""apps.monitor -- collector nodes / prometheus link / logs (ER 4.4)."""
from django.db import models

from common.models import TimeStampedModel


class CollectorNode(TimeStampedModel):
    name = models.CharField(max_length=64, unique=True)
    region_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    address = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=16, default="active")
    capacity = models.IntegerField(default=300)
    current_load = models.IntegerField(default=0)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)


class PrometheusTarget(TimeStampedModel):
    device_id = models.BigIntegerField(db_index=True)
    instance_label = models.CharField(max_length=128)
    job_label = models.CharField(max_length=64, default="node")
    last_scrape_at = models.DateTimeField(null=True, blank=True)
    last_scrape_ok = models.BooleanField(default=True)

    class Meta:
        unique_together = ("device_id", "instance_label")


class LogRecord(models.Model):
    """monthly partition via migration RunSQL later (ER D12)."""
    device_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    source = models.CharField(max_length=16, default="syslog")
    severity = models.SmallIntegerField(default=6, db_index=True)
    facility = models.CharField(max_length=32, blank=True)
    message = models.TextField()
    occurred_at = models.DateTimeField(db_index=True)


class TerminalSession(TimeStampedModel):
    user_id = models.BigIntegerField(null=True, blank=True)
    device_id = models.BigIntegerField(db_index=True)
    channel = models.CharField(max_length=16, default="web_cli")
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    command_count = models.IntegerField(default=0)


class TerminalCommand(models.Model):
    session_id = models.BigIntegerField(db_index=True)
    command = models.TextField()
    output_url = models.CharField(max_length=512, blank=True)
    executed_at = models.DateTimeField(auto_now_add=True)
