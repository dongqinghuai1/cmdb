"""apps.usage -- device occupation & login audit (ER 4.5 / PRD 5.17)."""
from django.contrib.auth.models import User
from django.db import models

from common.models import TimeStampedModel


class DeviceUsage(TimeStampedModel):
    class UsageType(models.TextChoices):
        RESERVE = "reserve"; OCCUPY = "occupy"

    class Status(models.TextChoices):
        RESERVED = "reserved"; ACTIVE = "active"; RELEASED = "released"
        EXPIRED = "expired"; CANCELLED = "cancelled"

    device_id = models.BigIntegerField(db_index=True)  # cmdb.Device bare FK
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    usage_type = models.CharField(max_length=8, choices=UsageType.choices, default=UsageType.RESERVE)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RESERVED, db_index=True)
    planned_start = models.DateTimeField()
    planned_end = models.DateTimeField()
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)
    purpose = models.CharField(max_length=255, blank=True)
    ticket_no = models.CharField(max_length=64, blank=True)
    released_by_id = models.BigIntegerField(null=True, blank=True)
    release_reason = models.CharField(max_length=255, blank=True)
    # window EXCLUDE constraint -> docker/constraints.sql (D4)


class LoginEvent(models.Model):
    """monthly partition via RunSQL later (ER D12); PK(id, login_at) on partitioning."""
    device_id = models.BigIntegerField(db_index=True)
    username = models.CharField(max_length=64, db_index=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    login_at = models.DateTimeField(db_index=True)
    logout_at = models.DateTimeField(null=True, blank=True)
    session_type = models.CharField(max_length=16, default="ssh")
    result = models.CharField(max_length=8, default="success")
    source = models.CharField(max_length=16, default="syslog")  # syslog/jumpserver/cli_pull/platform
