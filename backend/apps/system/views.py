"""apps.system 视图：认证 + RBAC/凭据/通知/审计 CRUD（required_perm 驱动功能权限）。"""
import hashlib
import secrets

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.system.models import (ApiToken, AuditLog, Credential, NotifyChannel,
                                OrgDept, Permission, Role, RoleDataScope,
                                SystemConfig)
from apps.system.serializers import (ApiTokenSerializer, AuditLogSerializer,
                                     CredentialSerializer, NotifyChannelSerializer,
                                     OrgDeptSerializer, PermissionSerializer,
                                     RoleDataScopeSerializer, RoleSerializer,
                                     SystemConfigSerializer, UserSerializer)
from common.audit import write_audit
from common.permissions import RbacPermission


class LoginView(TokenObtainPairView):
    """登录（登录失败锁定逻辑由 UserProfile.login_fail_count 驱动，hooks 后续版本）。"""


class MeView(APIView):
    def get(self, request):
        data = UserSerializer(request.user).data
        from common.permissions import user_perm_codes
        data["perm_codes"] = sorted(user_perm_codes(request.user))
        return Response(data)


class BaseModelViewSet(viewsets.ModelViewSet):
    permission_classes = [RbacPermission]
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def perform_create(self, serializer):
        obj = serializer.save()
        write_audit(self.request.user, "create", obj.__class__.__name__, obj.pk,
                    after=self._snapshot(serializer), source_ip=self._ip())

    def perform_update(self, serializer):
        # 修复：before 取数据库旧值，而非 validated_data（两者相同导致审计失真）
        instance = serializer.instance
        before = {f.name: getattr(instance, f.name, None) for f in instance._meta.fields
                  if f.name not in ("created_at", "updated_at")} if instance else {}
        obj = serializer.save()
        after = {k: v for k, v in serializer.validated_data.items()}
        write_audit(self.request.user, "update", obj.__class__.__name__, obj.pk,
                    before=before, after=after, source_ip=self._ip())

    def perform_destroy(self, instance):
        from django.db.models import ProtectedError
        before = self._snapshot(instance)
        name, pk = instance.__class__.__name__, instance.pk
        try:
            instance.delete()
        except ProtectedError as e:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(f"存在引用对象，无法删除：{str(e)[:300]}")
        write_audit(self.request.user, "delete", name, pk, before=before, source_ip=self._ip())

    @staticmethod
    def _snapshot(serializer_or_obj):
        try:
            return dict(serializer_or_obj.validated_data) if hasattr(serializer_or_obj, "validated_data") else {}
        except Exception:
            return {}

    def _ip(self):
        return (getattr(self.request, "META", {}).get("HTTP_X_FORWARDED_FOR", "").split(",")[0]
                or self.request.META.get("REMOTE_ADDR", ""))


class UserViewSet(BaseModelViewSet):
    queryset = User.objects.filter(is_active=True)
    serializer_class = UserSerializer
    required_perm = "system.user.view"
    search_fields = ["username", "email"]

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        roles = data.pop("roles", [])
        pwd = data.pop("password", None) or secrets.token_urlsafe(12)
        ser = self.get_serializer(data=data)
        ser.is_valid(raise_exception=True)
        attrs = {k: v for k, v in ser.validated_data.items()
                 if k not in ("roles", "dept_name")}
        user = User.objects.create_user(password=pwd, **attrs)
        user.roles.set(roles)
        return Response({"id": user.id, "initial_password": pwd}, status=201)


class OrgDeptViewSet(BaseModelViewSet):
    queryset = OrgDept.objects.all()
    serializer_class = OrgDeptSerializer
    required_perm = "system.dept.view"


class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [RbacPermission]


class RoleViewSet(BaseModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    required_perm = "system.role.view"

    @action(detail=True, methods=["get", "post"])
    def scopes(self, request, pk=None):
        role = self.get_object()
        if request.method == "POST":
            ser = RoleDataScopeSerializer(data=request.data)
            ser.is_valid(raise_exception=True)
            ser.save(role=role)
            return Response(ser.data, status=201)
        return Response(RoleDataScopeSerializer(role.data_scopes.all(), many=True).data)


class CredentialViewSet(BaseModelViewSet):
    queryset = Credential.objects.filter(deleted_at__isnull=True)
    serializer_class = CredentialSerializer
    required_perm = "system.credential.view"
    search_fields = ["name"]

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        obj = ser.save()
        write_audit(request.user, "create", "Credential", obj.pk, after={"name": obj.name})
        return Response(CredentialSerializer(obj).data, status=201)


class NotifyChannelViewSet(BaseModelViewSet):
    queryset = NotifyChannel.objects.all()
    serializer_class = NotifyChannelSerializer
    required_perm = "system.channel.view"

    @action(detail=True, methods=["post"])
    def test(self, request, pk=None):
        from apps.system.services import send_notification
        ok = send_notification(self.get_object(), "nops 测试通知：渠道连通性 OK")
        return Response({"ok": ok})


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related("user").order_by("-id")
    serializer_class = AuditLogSerializer
    permission_classes = [RbacPermission]
    required_perm = "system.audit.view"
    filterset_fields = ["action", "resource_type", "user"]


class SystemConfigViewSet(BaseModelViewSet):
    queryset = SystemConfig.objects.all()
    serializer_class = SystemConfigSerializer
    required_perm = "system.config.view"


class ApiTokenViewSet(BaseModelViewSet):
    queryset = ApiToken.objects.all()
    serializer_class = ApiTokenSerializer
    required_perm = "system.token.view"
    http_method_names = ["get", "post", "delete"]

    def create(self, request, *args, **kwargs):
        plain = "nops_" + secrets.token_urlsafe(32)
        data = request.data.copy()
        ser = self.get_serializer(data=data)
        ser.is_valid(raise_exception=True)
        obj = ser.save(token_hash=hashlib.sha256(plain.encode()).hexdigest(),
                       created_by=request.user, plain_token=plain)
        return Response(ApiTokenSerializer(obj).data, status=201)
