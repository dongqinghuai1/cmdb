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


class ChangeTicket(TimeStampedModel):
    """轻量变更单（ER 4.13 / 12.2-5）：申请->审批->实施->验证->关闭/驳回/回滚。

    审批复用 automate.Approval（biz_type=change_ticket，本模块创建并维护该审批行）；
    申请/实施/验证三人分离（applicant/implementer/verifier）；不做重型 ITSM。
    状态机：draft -> approving -> approved -> implementing -> verifying -> closed
                     |(驳)         |(回滚)         |(回滚)
                     v             v              v
                   rejected     rolledback      rolledback
    """

    class ChangeType(models.TextChoices):
        CONFIG = "config", "配置变更"
        DEVICE = "device", "设备变更"
        SW_UPGRADE = "sw_upgrade", "软件升级"
        NETWORK = "network", "网络变更"

    class RiskLevel(models.TextChoices):
        HIGH = "high", "高危"
        MID = "mid", "中危"
        LOW = "low", "低危"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        APPROVING = "approving", "待审批"
        APPROVED = "approved", "已批准"
        IMPLEMENTING = "implementing", "实施中"
        VERIFYING = "verifying", "验证中"
        CLOSED = "closed", "已关闭"
        REJECTED = "rejected", "已驳回"
        ROLLEDBACK = "rolledback", "已回滚"

    ticket_no = models.CharField(max_length=32, unique=True, db_index=True)
    title = models.CharField(max_length=255)
    change_type = models.CharField(max_length=16, choices=ChangeType.choices,
                                   default=ChangeType.CONFIG, db_index=True)
    risk_level = models.CharField(max_length=8, choices=RiskLevel.choices,
                                  default=RiskLevel.MID, db_index=True)
    plan_start = models.DateTimeField(null=True, blank=True)
    plan_end = models.DateTimeField(null=True, blank=True)
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices,
                              default=Status.DRAFT, db_index=True)
    applicant_id = models.BigIntegerField(db_index=True)
    implementer_id = models.BigIntegerField(null=True, blank=True)
    verifier_id = models.BigIntegerField(null=True, blank=True)
    approver_id = models.BigIntegerField(null=True, blank=True)
    approval_id = models.BigIntegerField(null=True, blank=True)
    content = models.JSONField(default=dict, blank=True,
                               help_text="变更内容与影响面 {summary, impact, steps, affected_device_ids}")
    related_script_run_id = models.BigIntegerField(null=True, blank=True)
    related_config_event_id = models.BigIntegerField(null=True, blank=True)
    rollback_plan = models.TextField(blank=True)
    result_desc = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "变更单"

    def __str__(self):
        return f"{self.ticket_no} {self.title} [{self.status}]"
