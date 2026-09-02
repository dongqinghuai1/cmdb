"""apps.change -- 轻量事件单（ER 4.13 / PRD 11.1-14）：报障->分派->处理->反馈->关闭，与告警/巡检联动。

设计约定：
- 跨 App 不建外键：reporter/handler/device/alert_event 等引用一律裸 BigIntegerField
  （同 automate/ncm 惯例），归属校验在 services 层。
- 时间线 IncidentEvent 与工单同表存储（comment/assign/status_change/sla_warning）。
- ChangeTicket（轻量变更单 12.2-5）为二期欠账，后续里程碑落地（复用 automate.Approval biz_type=change_ticket）。
"""
from django.db import models

from common.models import TimeStampedModel


class IncidentTicket(TimeStampedModel):
    class Source(models.TextChoices):
        MANUAL = "manual", "人工报障"
        ALERT = "alert", "告警联动"
        INSPECT = "inspect", "巡检异常"

    class Priority(models.TextChoices):
        URGENT = "urgent", "紧急"
        HIGH = "high", "高"
        MID = "mid", "中"
        LOW = "low", "低"

    class Status(models.TextChoices):
        NEW = "new", "待分派"
        ASSIGNED = "assigned", "处理中(已分派)"
        PROCESSING = "processing", "处理中"
        FEEDBACK = "feedback", "待反馈确认"
        CLOSED = "closed", "已关闭"

    # SLA 小时数：priority -> 处理时限（服务层据此计算 sla_deadline）
    SLA_HOURS = {Priority.URGENT: 2, Priority.HIGH: 4, Priority.MID: 8, Priority.LOW: 24}

    ticket_no = models.CharField(max_length=32, unique=True, db_index=True)
    title = models.CharField(max_length=255)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL, db_index=True)
    reporter_id = models.BigIntegerField(db_index=True)
    handler_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.MID, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW, db_index=True)
    related_alert_event_id = models.BigIntegerField(null=True, blank=True)
    device_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    sla_deadline = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    description = models.TextField(blank=True)
    resolution = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "事件单"

    def __str__(self):
        return f"{self.ticket_no} {self.title} [{self.status}]"


class IncidentEvent(TimeStampedModel):
    class EventType(models.TextChoices):
        COMMENT = "comment", "评论"
        ASSIGN = "assign", "分派"
        STATUS_CHANGE = "status_change", "状态变更"
        SLA_WARNING = "sla_warning", "SLA 超时提醒"

    ticket = models.ForeignKey(IncidentTicket, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=16, choices=EventType.choices, default=EventType.COMMENT)
    actor_id = models.BigIntegerField(null=True, blank=True)
    content = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"#{self.ticket_id} {self.event_type} by {self.actor_id}"
