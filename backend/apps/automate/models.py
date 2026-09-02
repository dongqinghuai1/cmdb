"""apps.automate -- 自动化运维（ER 4.12）：脚本库 / 批量执行(灰度+审批) / 通用审批 / 逐台执行明细。

设计约定（不推翻，均有原因）：
- 跨 App 不建外键：script/approval/run 里的 device_id/user_id/script_id 一律裸 BigIntegerField
  （对齐 ncm/ipam 惯例，DB 层无约束，归属校验在 services/views 层做）。
- script_run.content_snapshot 与 detail.output 先内联加密存 PG（EncryptedTextField，同 NCM
  配置备份思路）；MinIO 对象存储接入后迁 output_url（见 HANDOVER 技术债）。
- Job/JobRun（任务编排）与 FirmwareUpgradePlan（固件升级作业）为 ER P2 骨架，后续里程碑再落地。
"""
from django.db import models

from common.crypto import EncryptedTextField
from common.models import TimeStampedModel


class Script(TimeStampedModel):
    """命令/脚本库。danger_level=high 的脚本执行强制走审批（PRD 5.12）。"""

    class ScriptType(models.TextChoices):
        CLI_COMMAND = "cli_command", "网络 CLI 命令"
        PYTHON = "python", "Python 脚本"
        SHELL = "shell", "Shell 脚本"
        ANSIBLE = "ansible", "Ansible Playbook"

    class DangerLevel(models.TextChoices):
        LOW = "low", "低危"
        MID = "mid", "中危"
        HIGH = "high", "高危"

    name = models.CharField(max_length=128, db_index=True)
    category = models.CharField(max_length=64, blank=True, help_text="分类，如 配置备份/端口操作/巡检处理")
    script_type = models.CharField(max_length=16, choices=ScriptType.choices, default=ScriptType.CLI_COMMAND)
    content = EncryptedTextField(help_text="脚本/命令内容（AES-256-GCM 密文存储）")
    params_schema = models.JSONField(default=dict, blank=True,
                                     help_text="参数定义 [{key,label,default,required}]，执行时 {{key}} 插值")
    danger_level = models.CharField(max_length=8, choices=DangerLevel.choices, default=DangerLevel.LOW)
    enabled = models.BooleanField(default=True)
    remark = models.TextField(blank=True)
    created_by_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "脚本库"

    @property
    def requires_approval(self) -> bool:
        return self.danger_level == self.DangerLevel.HIGH

    def __str__(self):
        return f"{self.name}({self.get_danger_level_display()})"


class Approval(TimeStampedModel):
    """通用审批单（多业务复用：脚本执行 / 变更单）。"""

    class BizType(models.TextChoices):
        SCRIPT_RUN = "script_run", "脚本执行"
        CHANGE_TICKET = "change_ticket", "变更单"

    class Status(models.TextChoices):
        PENDING = "pending", "待审批"
        APPROVED = "approved", "已通过"
        REJECTED = "rejected", "已驳回"

    biz_type = models.CharField(max_length=16, choices=BizType.choices, default=BizType.SCRIPT_RUN)
    biz_id = models.BigIntegerField(db_index=True)
    applicant_id = models.BigIntegerField(db_index=True)
    approver_id = models.BigIntegerField(db_index=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING, db_index=True)
    comment = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.biz_type}#{self.biz_id} {self.status}"


class ScriptRun(TimeStampedModel):
    """批量执行记录。状态机：
    pending -> running -> success / failed / partial_success
    approving ->(批准) pending /(驳回) cancelled
    pending/approving/running -> cancelled（申请/超管）
    """

    class Trigger(models.TextChoices):
        MANUAL = "manual", "手动"
        SCHEDULE = "schedule", "周期任务"

    class Status(models.TextChoices):
        PENDING = "pending", "待执行"
        APPROVING = "approving", "待审批"
        RUNNING = "running", "执行中"
        PARTIAL_SUCCESS = "partial_success", "部分成功"
        SUCCESS = "success", "成功"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    script_id = models.BigIntegerField(db_index=True)
    script_name_snapshot = models.CharField(max_length=128, blank=True)
    script_type_snapshot = models.CharField(max_length=16, blank=True)
    danger_snapshot = models.CharField(max_length=8, blank=True)
    content_snapshot = EncryptedTextField(blank=True, default="", help_text="执行时刻渲染后的内容快照（加密）")
    params = models.JSONField(default=dict, blank=True)
    trigger = models.CharField(max_length=8, choices=Trigger.choices, default=Trigger.MANUAL)
    executed_by_id = models.BigIntegerField(db_index=True)
    approval_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    scope = models.JSONField(default=dict, blank=True,
                             help_text="目标范围 {device_ids:[], gray_first:bool, reason:str}")
    gray_batch = models.JSONField(default=dict, blank=True,
                                  help_text="灰度进度 {enabled, total, dispatched}")
    summary = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def target_count(self) -> int:
        return len(self.scope.get("device_ids") or [])

    def __str__(self):
        return f"#{self.id} {self.script_name_snapshot} [{self.status}]"


class ScriptRunDetail(TimeStampedModel):
    """逐台执行明细。"""

    class Status(models.TextChoices):
        PENDING = "pending", "排队中"
        RUNNING = "running", "执行中"
        SUCCESS = "success", "成功"
        FAILED = "failed", "失败"

    run = models.ForeignKey(ScriptRun, on_delete=models.CASCADE, related_name="details")
    device_id = models.BigIntegerField(db_index=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING, db_index=True)
    output_url = models.CharField(max_length=255, blank=True, help_text="MinIO 接入后存储回显对象 URL")
    output = EncryptedTextField(blank=True, default="", help_text="回显全文（加密内联存储，偏差见文件头注释）")
    error = models.TextField(blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["run", "device_id"], name="detail_run_dev_idx")]

    def __str__(self):
        return f"run#{self.run_id} dev#{self.device_id} {self.status}"
