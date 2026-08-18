"""apps.alert -- rules / events with dedup key (ER 4.6 / D3)."""
from django.db import models

from common.models import TimeStampedModel


class AlertRule(TimeStampedModel):
    class RuleType(models.TextChoices):
        METRIC = "metric_threshold"; STATE = "state"; LOG = "log_keyword"; TRAP = "trap"

    name = models.CharField(max_length=64, unique=True)
    rule_type = models.CharField(max_length=16, choices=RuleType.choices, default=RuleType.METRIC)
    scope = models.JSONField(default=dict, blank=True)
    metric = models.CharField(max_length=128, blank=True)
    operator = models.CharField(max_length=8, default=">")
    threshold = models.DecimalField(max_digits=16, decimal_places=3, default=0)
    for_duration_s = models.IntegerField(default=300)
    severity = models.CharField(max_length=8, default="warning")
    log_pattern = models.CharField(max_length=512, blank=True)
    notify_channels = models.JSONField(default=list, blank=True)
    notify_users = models.JSONField(default=list, blank=True)
    dedup_window_s = models.IntegerField(default=600)
    enabled = models.BooleanField(default=True)


class AlertEvent(TimeStampedModel):
    class Status(models.TextChoices):
        FIRING = "firing"; ACKNOWLEDGED = "acknowledged"; PROCESSING = "processing"
        RESOLVED = "resolved"; CLOSED = "closed"

    dedup_key = models.CharField(max_length=128, db_index=True)  # device_id:rule_id / :item_id
    rule_id = models.BigIntegerField(null=True, blank=True)
    inspect_item_id = models.BigIntegerField(null=True, blank=True)
    device_id = models.BigIntegerField(db_index=True)
    interface_id = models.BigIntegerField(null=True, blank=True)
    severity = models.CharField(max_length=8, default="warning")
    title = models.CharField(max_length=255)
    detail = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.FIRING, db_index=True)
    fired_count = models.IntegerField(default=1)
    first_fired_at = models.DateTimeField(auto_now_add=True)
    last_fired_at = models.DateTimeField(auto_now=True)
    acked_by_id = models.BigIntegerField(null=True, blank=True)
    acked_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_by_id = models.BigIntegerField(null=True, blank=True)
    process_note = models.TextField(blank=True)
    suppressed_by_id = models.BigIntegerField(null=True, blank=True)
    # active-event partial unique on dedup_key -> docker/constraints.sql (D3)


class AlertNotification(TimeStampedModel):
    event = models.ForeignKey(AlertEvent, on_delete=models.CASCADE, related_name="notifications")
    channel_id = models.BigIntegerField(null=True, blank=True)
    target = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=8, default="queued")
    error = models.CharField(max_length=255, blank=True)
    retry_count = models.IntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    channel_msg_id = models.CharField(max_length=64, blank=True)  # feishu card callback (V1.1 #18)
    interaction_status = models.CharField(max_length=16, blank=True)


class AlertSilence(TimeStampedModel):
    scope = models.JSONField(default=dict, blank=True)
    silence_type = models.CharField(max_length=16, default="maintenance")  # maintenance / occupation
    device_usage_id = models.BigIntegerField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    created_by_id = models.BigIntegerField(null=True, blank=True)


class AlertEscalationRule(TimeStampedModel):
    severity = models.CharField(max_length=8)
    timeout_min = models.IntegerField(default=15)
    escalate_role_id = models.BigIntegerField(null=True, blank=True)
    channel_ids = models.JSONField(default=list, blank=True)
    fired_count = models.IntegerField(default=0)
    last_fired_at = models.DateTimeField(null=True, blank=True)
