"""apps.system -- 用户/角色/RBAC/凭据/通知/审计（ER 4.14/4.3）。"""
from django.contrib.auth.models import User
from django.db import models

from common.crypto import EncryptedTextField
from common.models import SoftDeleteModel, TimeStampedModel


class OrgDept(TimeStampedModel):
    parent = models.ForeignKey("self", null=True, blank=True,
                               on_delete=models.CASCADE, related_name="children")
    name = models.CharField(max_length=64)
    feishu_dept_id = models.CharField(max_length=64, null=True, blank=True)
    sort = models.IntegerField(default=0)

    class Meta:
        ordering = ["sort", "id"]


class UserProfile(models.Model):
    """扩展 django auth_user：飞书绑定 + 登录安全（V1.1 评审 #4）。"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    feishu_unionid = models.CharField(max_length=64, null=True, blank=True, unique=True)
    phone = models.CharField(max_length=32, null=True, blank=True)
    dept = models.ForeignKey(OrgDept, null=True, blank=True, on_delete=models.SET_NULL)
    login_fail_count = models.IntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = EncryptedTextField(null=True, blank=True)
    password_expired_at = models.DateField(null=True, blank=True)
    last_password_change = models.DateField(null=True, blank=True)


class Permission(TimeStampedModel):
    code = models.CharField(max_length=128, unique=True)   # 如 cmdb.device.execute
    name = models.CharField(max_length=128)
    menu = models.CharField(max_length=64, blank=True)
    action = models.CharField(max_length=16,
                              choices=[("view", "view"), ("add", "add"),
                                       ("edit", "edit"), ("delete", "delete"),
                                       ("execute", "execute")])


class Role(TimeStampedModel):
    name = models.CharField(max_length=64)
    code = models.CharField(max_length=64, unique=True)
    builtin = models.BooleanField(default=False)
    permissions = models.ManyToManyField(Permission, blank=True)
    users = models.ManyToManyField(User, blank=True, related_name="roles")


class RoleDataScope(TimeStampedModel):
    class ScopeType(models.TextChoices):
        ALL = "all"; REGION = "region"; SITE = "site"
        MODEL = "model"; DEVICE_GROUP = "device_group"

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="data_scopes")
    scope_type = models.CharField(max_length=16, choices=ScopeType.choices)
    scope_ref_id = models.BigIntegerField(null=True, blank=True)  # ALL 时为空


class Credential(SoftDeleteModel):
    class CredType(models.TextChoices):
        SSH_PASSWORD = "ssh_password"; SSH_KEY = "ssh_key"; SNMP_V1 = "snmp_v1"
        SNMP_V2C = "snmp_v2c"; SNMP_V3 = "snmp_v3"; API_TOKEN = "api_token"

    name = models.CharField(max_length=64, unique=True)
    cred_type = models.CharField(max_length=16, choices=CredType.choices)
    username = models.CharField(max_length=64, null=True, blank=True)
    secret = EncryptedTextField()                       # 密码/密钥/community/token
    params = models.JSONField(default=dict, blank=True)  # {"port":22,"auth_proto":"SHA"...}
    scope = models.JSONField(default=dict, blank=True)   # 凭据分组（V1.1 #2）
    last_rotated_at = models.DateTimeField(null=True, blank=True)
    expire_at = models.DateTimeField(null=True, blank=True)
    remark = models.CharField(max_length=255, blank=True)


class NotifyChannel(TimeStampedModel):
    class ChannelType(models.TextChoices):
        FEISHU = "feishu"; EMAIL = "email"; WEBHOOK = "webhook"
        WECHAT = "wechat"; DINGTALK = "dingtalk"; SMS = "sms"

    name = models.CharField(max_length=64)
    channel_type = models.CharField(max_length=16, choices=ChannelType.choices)
    config = models.JSONField(default=dict)  # {"webhook_url":...,"app_id":...} 敏感项加密后放 secret
    secret = EncryptedTextField(null=True, blank=True)
    enabled = models.BooleanField(default=True)


class ApiToken(TimeStampedModel):
    name = models.CharField(max_length=64)
    token_hash = models.CharField(max_length=64, unique=True)  # sha256
    scopes = models.JSONField(default=list, blank=True)
    is_readonly = models.BooleanField(default=True)            # AI 只读 Token（12.3-6）
    rate_limit_per_min = models.IntegerField(default=60)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)


class AuditLog(models.Model):
    """按月分区在迁移 RunSQL 中处理（D12）；一期先普通表+索引，量级到位再转分区。"""
    class ActionChoices(models.TextChoices):
        LOGIN = "login"; LOGOUT = "logout"; CREATE = "create"; UPDATE = "update"
        DELETE = "delete"; EXECUTE = "execute"
        CREDENTIAL_USE = "credential_use"; API_CALL = "api_call"

    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=16, choices=ActionChoices.choices)
    resource_type = models.CharField(max_length=64)
    resource_id = models.CharField(max_length=64)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class SystemConfig(TimeStampedModel):
    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField(default=dict)
    description = models.CharField(max_length=255, blank=True)


class DataImportJob(TimeStampedModel):
    class Status(models.TextChoices):
        VALIDATING = "validating"; RUNNING = "running"; PARTIAL = "partial"
        SUCCESS = "success"; FAILED = "failed"

    biz_type = models.CharField(max_length=16, default="device")
    file_url = models.CharField(max_length=512, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.VALIDATING)
    total_cnt = models.IntegerField(default=0)
    success_cnt = models.IntegerField(default=0)
    fail_cnt = models.IntegerField(default=0)
    error_report_url = models.CharField(max_length=512, blank=True)
    dedup_strategy = models.CharField(max_length=8, default="skip")  # skip / update
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    result = models.JSONField(default=dict, blank=True)  # 逐行错误回执


class DutySchedule(TimeStampedModel):
    shift = models.CharField(max_length=16, choices=[("primary", "primary"), ("backup", "backup")])
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    duty_date = models.DateField()
    region = models.ForeignKey("dcim.Region", null=True, blank=True, on_delete=models.SET_NULL)
    handover_note = models.TextField(blank=True)
    handed_off_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("user", "duty_date", "shift")


class WebhookSubscription(TimeStampedModel):
    name = models.CharField(max_length=64)
    url = models.CharField(max_length=512)
    events = models.JSONField(default=list)  # ["device.offline","alert.fired",...]
    secret = EncryptedTextField(null=True, blank=True)
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
