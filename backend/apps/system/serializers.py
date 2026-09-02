from rest_framework import serializers

from apps.system.models import (ApiToken, AuditLog, Credential, DutySchedule,
                                NotifyChannel, OrgDept, Permission, Role,
                                RoleDataScope, SystemConfig, UserProfile)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class UserSerializer(serializers.ModelSerializer):
    dept_name = serializers.CharField(source="profile.dept.name", read_only=True, default="")
    roles = serializers.PrimaryKeyRelatedField(many=True, queryset=Role.objects.all(), required=False)

    class Meta:
        model = __import__("django.contrib.auth.models", fromlist=["User"]).User
        fields = ["id", "username", "email", "is_active", "first_name", "roles", "dept_name"]


class OrgDeptSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrgDept
        fields = "__all__"


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = "__all__"


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.PrimaryKeyRelatedField(many=True, queryset=Permission.objects.all(), required=False)

    class Meta:
        model = Role
        fields = ["id", "name", "code", "builtin", "permissions"]


class RoleDataScopeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoleDataScope
        fields = "__all__"


class CredentialSerializer(serializers.ModelSerializer):
    secret = serializers.CharField(write_only=True)   # 只写；读取时脱敏
    secret_masked = serializers.SerializerMethodField()

    class Meta:
        model = Credential
        fields = ["id", "name", "cred_type", "username", "secret", "secret_masked",
                  "params", "scope", "last_rotated_at", "expire_at", "remark"]
        read_only_fields = ["last_rotated_at"]

    def get_secret_masked(self, obj):
        return "****" if obj.secret else ""


class NotifyChannelSerializer(serializers.ModelSerializer):
    secret = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = NotifyChannel
        fields = "__all__"


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True, default="")

    class Meta:
        model = AuditLog
        fields = ["id", "username", "action", "resource_type", "resource_id",
                  "before", "after", "source_ip", "created_at"]


class SystemConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemConfig
        fields = "__all__"


class ApiTokenSerializer(serializers.ModelSerializer):
    plain_token = serializers.CharField(read_only=True)  # 创建时返回一次

    class Meta:
        model = ApiToken
        fields = ["id", "name", "token_hash", "scopes", "is_readonly",
                  "rate_limit_per_min", "expires_at", "revoked_at", "plain_token"]


class DutyScheduleSerializer(serializers.ModelSerializer):
    """值班排班（ER V1.1#23）：user/region 传 id，读侧附 user_name/region_name。"""
    user_name = serializers.SerializerMethodField()
    region_name = serializers.SerializerMethodField()

    class Meta:
        model = DutySchedule
        fields = ["id", "shift", "user", "user_name", "duty_date", "region",
                  "region_name", "handover_note", "handed_off_at",
                  "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def get_user_name(self, o):
        return getattr(o.user, "username", "") or ""

    def get_region_name(self, o):
        return getattr(o.region, "name", None)
