"""apps.report -- 报表中心（ER ch.4 报表/统计）。

设计：
- ReportSnapshot：按 (report_type, period_start) 幂等覆盖的指标快照 JSON，供日报/看板回放。
  内容由 report.services.build_snapshot 从各 app 既有表聚合（不新起采集、纯只读统计）。
- ReportSchedule：报表订阅（生成/推送计划）。v1 每日由 beat 任务 report.daily_snapshot
  逐条生成并推送通知渠道；hour 仅作展示与未来粒度扩展。
"""
from django.db import models

from common.models import TimeStampedModel


class ReportSnapshot(TimeStampedModel):
    class Type(models.TextChoices):
        INVENTORY = "inventory", "设备台账快照"
        ALERTS = "alerts", "告警态势快照"
        CHANGES = "changes", "变更/事件快照"
        NCM = "ncm", "配置/基线快照"

    report_type = models.CharField(max_length=16, choices=Type.choices, db_index=True)
    period_start = models.DateTimeField(db_index=True)
    period_end = models.DateTimeField()
    content = models.JSONField(default=dict, blank=True)
    built_by = models.CharField(max_length=8, default="manual")  # manual / auto
    duration_ms = models.IntegerField(default=0)
    remark = models.CharField(max_length=128, blank=True)

    class Meta:
        unique_together = ("report_type", "period_start")
        ordering = ["-period_start"]
        verbose_name = "报表快照"

    def __str__(self):
        return f"{self.report_type} @ {self.period_start:%m-%d %H:%M}"


class ReportSchedule(TimeStampedModel):
    name = models.CharField(max_length=64, unique=True)
    report_type = models.CharField(max_length=16, choices=ReportSnapshot.Type.choices,
                                   db_index=True)
    hour = models.IntegerField(default=7, help_text="期望生成小时（0-23，展示用；v1 每日批任务统一触发）")
    enabled = models.BooleanField(default=True)
    notify_channel_ids = models.JSONField(default=list, blank=True)
    receivers = models.JSONField(default=list, blank=True, help_text="站内接收人 user_id 列表（占位）")
    remark = models.CharField(max_length=255, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_by_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "报表订阅"

    def __str__(self):
        return f"{self.name} [{self.report_type}]"
