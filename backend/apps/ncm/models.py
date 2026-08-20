"""apps.ncm -- config backup / change events / baseline (ER 4.9).

Deviation note: config content stored encrypted in PG for now (EncryptedTextField);
MinIO encrypted-bucket migration deferred (see HANDOVER.md tech-debt)."""
from django.db import models

from common.crypto import EncryptedTextField
from common.models import TimeStampedModel


class ConfigBackup(TimeStampedModel):
    class BackupType(models.TextChoices):
        RUNNING = "running"; STARTUP = "startup"; FULL = "full"

    class Trigger(models.TextChoices):
        SCHEDULED = "scheduled"; EVENT = "event"; MANUAL = "manual"; IMPORT = "import"

    device_id = models.BigIntegerField(db_index=True)
    backup_type = models.CharField(max_length=16, choices=BackupType.choices, default=BackupType.RUNNING)
    trigger = models.CharField(max_length=16, choices=Trigger.choices, default=Trigger.MANUAL)
    content = EncryptedTextField()          # running-config ciphertext
    size = models.IntegerField(default=0)
    file_hash = models.CharField(max_length=64, db_index=True)  # sha256, content dedup

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "config backup"


class ConfigChangeEvent(TimeStampedModel):
    device_id = models.BigIntegerField(db_index=True)
    detected_at = models.DateTimeField(auto_now_add=True, db_index=True)
    old_backup_id = models.BigIntegerField(null=True, blank=True)
    new_backup_id = models.BigIntegerField()
    changed_lines = models.IntegerField(default=0)
    diff_text = models.TextField(blank=True)
    related_alert_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-detected_at"]


class BaselineRule(TimeStampedModel):
    class RuleType(models.TextChoices):
        MUST_PRESENT = "must_present"; MUST_ABSENT = "must_absent"

    name = models.CharField(max_length=64, unique=True)
    rule_type = models.CharField(max_length=16, choices=RuleType.choices, default=RuleType.MUST_PRESENT)
    pattern = models.TextField(help_text="regex, applied per line")
    scope = models.JSONField(default=dict, blank=True)
    severity = models.CharField(max_length=8, default="warning")
    remark = models.CharField(max_length=255, blank=True)


class BaselineCheckResult(TimeStampedModel):
    rule = models.ForeignKey(BaselineRule, on_delete=models.CASCADE, related_name="results")
    device_id = models.BigIntegerField(db_index=True)
    compliant = models.BooleanField(default=True)
    matched_content = models.TextField(blank=True)
