"""apps.system 视图：认证 + RBAC/凭据/通知/审计 CRUD（required_perm 驱动功能权限）。"""
import hashlib
import secrets

import django_filters

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.system.models import (ApiToken, AuditLog, Credential, DutySchedule,
                                NotifyChannel, OrgDept, Permission, Role,
                                RoleDataScope, SystemConfig)
from apps.system.serializers import (ApiTokenSerializer, AuditLogSerializer,
                                     CredentialSerializer, DutyScheduleSerializer,
                                     NotifyChannelSerializer,
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


class AuditLogFilter(django_filters.FilterSet):
    """审计日志检索：动作/对象类型/操作人/来源IP 等值 + created_at 区间(created_at_after/before)。"""
    created_at = django_filters.DateFromToRangeFilter()

    class Meta:
        model = AuditLog
        fields = ["action", "resource_type", "user", "source_ip"]


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related("user").order_by("-id")
    serializer_class = AuditLogSerializer
    permission_classes = [RbacPermission]
    required_perm = "system.audit.view"
    filterset_class = AuditLogFilter
    search_fields = ["resource_type", "resource_id", "source_ip"]

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        """审计概览：近 N 小时（默认 24）总量 + 动作/对象/人 TOP + 近 7 日趋势。"""
        from datetime import timedelta
        from django.db.models import Count
        from django.utils import timezone
        hours = int(request.query_params.get("hours", 24))
        since = timezone.now() - timedelta(hours=hours)
        qs = AuditLog.objects.filter(created_at__gte=since)
        top = (lambda field: list(qs.order_by()
              .values(field).annotate(c=Count("id")).order_by("-c")[:6]))
        days = list(qs.filter(created_at__date__gte=(timezone.now() - timedelta(days=6)).date())
                    .order_by().values("created_at__date")
                    .annotate(c=Count("id")).order_by("created_at__date"))
        return Response({
            "hours": hours, "total": qs.count(),
            "by_action": top("action"),
            "by_resource": [x for x in top("resource_type") if x.get("resource_type")],
            "by_user": [x for x in top("user__username") if x.get("user__username")],
            "days": [{"date": str(d["created_at__date"]), "count": d["c"]} for d in days],
        })

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        """导出当前筛选结果为 CSV（≤5000 行；列含变更前后 JSON）。"""
        import csv
        import json
        from django.http import HttpResponse
        from django.utils import timezone as _tz
        qs = self.filter_queryset(self.get_queryset())[:5000]
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = ('attachment; filename="audit_{}.csv"'
                                       .format(_tz.now().strftime("%Y%m%d_%H%M%S")))
        w = csv.writer(resp)
        w.writerow(["created_at", "user", "action", "resource_type", "resource_id",
                    "source_ip", "before", "after"])
        for o in qs:
            w.writerow([o.created_at.isoformat() if o.created_at else "",
                        (o.user.username if o.user else ""), o.action, o.resource_type,
                        o.resource_id or "", o.source_ip or "",
                        json.dumps(o.before or {}, ensure_ascii=False),
                        json.dumps(o.after or {}, ensure_ascii=False)])
        return resp


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


class DutyScheduleViewSet(BaseModelViewSet):
    """值班排班（ER V1.1#23）：主班/备班按天排人；同人同日同班次唯一(DB+校验)。
    读需 system.duty.view；写（排班/交班/删除）另需 system.duty.edit。"""
    queryset = DutySchedule.objects.select_related("user", "region").order_by("duty_date", "shift")
    serializer_class = DutyScheduleSerializer
    required_perm = "system.duty.view"
    filterset_fields = ["duty_date", "shift"]

    def _need_edit(self, request):
        from common.permissions import has_perm
        from rest_framework.exceptions import PermissionDenied
        if not (request.user.is_superuser or has_perm(request.user, "system.duty.edit")):
            raise PermissionDenied("无值班排班管理权限(system.duty.edit)")

    def perform_create(self, serializer):
        self._need_edit(self.request)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._need_edit(self.request)
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        self._need_edit(self.request)
        super().perform_destroy(instance)

    @action(detail=False, methods=["get"], url_path="calendar")
    def calendar(self, request):
        """值班日历：?month=YYYY-MM（默认当月）。返回 {month, days:[{date, primary, backup}]}，
        primary/backup={id,user_id,user_name,region,region_name,handover_note,handed_off_at}|None；
        同人同日重复班次(备份挡主班)按 created_at 最新优先展示，row 留全量。"""
        import calendar as _cal
        from datetime import date, datetime
        month = (request.query_params.get("month") or datetime.now().strftime("%Y-%m"))
        try:
            y, m = (int(x) for x in month.split("-"))
            first = date(y, m, 1)
        except Exception:
            return Response({"detail": "month must be YYYY-MM"}, status=400)
        last_day = _cal.monthrange(y, m)[1]
        start, end = first, date(y, m, last_day)
        rows = list(DutySchedule.objects.filter(duty_date__range=(start, end))
                    .select_related("user", "region").order_by("-created_at"))
        days = {}
        for d in range(1, last_day + 1):
            days[d] = {"date": date(y, m, d).isoformat(), "primary": None, "backup": None,
                       "all": []}
        for r in rows:
            slot = days.get(r.duty_date.day, {}).get("all")
            if slot is None:
                continue
            slot.append({
                "id": r.id, "user_id": r.user_id,
                "user_name": getattr(r.user, "username", "") or "",
                "region": r.region_id, "region_name": getattr(r.region, "name", None),
                "handover_note": r.handover_note, "handed_off_at": r.handed_off_at})
            if days[r.duty_date.day][r.shift] is None:
                days[r.duty_date.day][r.shift] = slot[-1]
        return Response({"month": f"{y:04d}-{m:02d}", "days": list(days.values())})

    @action(detail=True, methods=["post"], url_path="handoff")
    def handoff(self, request, pk=None):
        """交班确认：置 handed_off_at=now + 交班备注（写需 system.duty.edit）。"""
        from django.utils import timezone
        self._need_edit(request)
        obj = self.get_object()
        note = (request.data.get("note") if request.data else None)
        obj.handed_off_at = timezone.now()
        if note is not None:
            obj.handover_note = str(note)[:2000]
        obj.save(update_fields=["handed_off_at", "handover_note", "updated_at"])
        from common.audit import write_audit
        write_audit(request.user, "execute", "DutySchedule", obj.pk,
                    after={"duty_date": str(obj.duty_date), "shift": obj.shift,
                           "handed_off": True, "note": obj.handover_note},
                    source_ip=request.META.get("REMOTE_ADDR", ""))
        return Response(DutyScheduleSerializer(obj).data)
