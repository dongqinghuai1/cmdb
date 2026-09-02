"""飞书 SSO 端点：公开授权（login-url/callback）+ 应用管理/组织同步（system.sso.*）。"""
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.system import feishu as feishu_svc
from apps.system.models import FeishuApp
from apps.system.serializers import FeishuAppSerializer
from apps.system.views import BaseModelViewSet
from common.audit import write_audit
from common.permissions import has_perm


class LoginUrlView(APIView):
    """GET /auth/feishu/login-url/?app=<pk|name>&state=xx —— 返回 OAuth 授权跳转 URL（公开）。"""

    permission_classes = [AllowAny]

    def get(self, request):
        app = feishu_svc.active_app(request.query_params.get("app") or None)
        if not app:
            return Response({"detail": "未配置启用的飞书应用（system.sso.edit 可管理）"}, status=400)
        origin = request.build_absolute_uri("/").rstrip("/")
        url = feishu_svc.build_login_url(app, origin, request.query_params.get("state", ""))
        return Response({"url": url, "app": app.name, "app_id": app.app_id,
                         "mock_mode": app.mock_mode})


class CallbackView(APIView):
    """GET /auth/feishu/callback/?app=&code=&state=&sso_name= —— 授权码换登录态。

    身份定位/自动建号成功后签发与普通登录一致的 JWT（access/refresh）。
    """

    permission_classes = [AllowAny]

    def get(self, request):
        app = feishu_svc.active_app(request.query_params.get("app") or None)
        if not app:
            return Response({"detail": "未配置启用的飞书应用"}, status=400)
        code = (request.query_params.get("code") or "").strip()
        if not code:
            return Response({"detail": "缺少 code"}, status=400)
        try:
            identity = feishu_svc.exchange_identity(
                app, code, sso_name=request.query_params.get("sso_name", ""))
        except feishu_svc.RequiresCalibration as e:
            return Response({"detail": str(e), "calibration": True}, status=400)
        try:
            user, created = feishu_svc.provision_or_bind(app, identity)
        except PermissionError as e:
            return Response({"detail": str(e)}, status=403)
        if not user.is_active:
            return Response({"detail": "账号已停用"}, status=403)
        tokens = RefreshToken.for_user(user)
        from apps.system.models import UserProfile
        prof, _ = UserProfile.objects.get_or_create(user=user)
        write_audit(user, "login", "User", user.pk,
                    after={"channel": "feishu", "unionid": identity["union_id"],
                           "name": identity.get("name", "")},
                    source_ip=request.META.get("REMOTE_ADDR", ""))
        return Response({
            "access": str(tokens.access_token), "refresh": str(tokens),
            "user": {"id": user.pk, "username": user.username,
                     "name": user.first_name or user.username,
                     "feishu_unionid": prof.feishu_unionid,
                     "dept_id": prof.dept_id},
            "first_login": created})


class FeishuAppViewSet(BaseModelViewSet):
    """飞书应用管理（SSO 配置/组织同步触发）。"""

    queryset = FeishuApp.objects.all()
    serializer_class = FeishuAppSerializer
    required_perm = "system.sso.view"
    search_fields = ["name", "app_id", "remark"]
    filterset_fields = ["enabled", "mock_mode"]

    def _need_edit(self):
        if not (self.request.user.is_superuser or has_perm(self.request.user, "system.sso.edit")):
            raise PermissionDenied("无飞书 SSO 配置权限（system.sso.edit）")

    def perform_create(self, serializer):
        self._need_edit()
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._need_edit()
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        self._need_edit()
        super().perform_destroy(instance)

    @action(detail=True, methods=["post"], url_path="contacts-sync")
    def contacts_sync(self, request, pk=None):
        """组织通讯录同步（幂等）。app.mock_mode=True 走确定性样例；真实 contact API 未校准前
        raise calibration 提示。"""
        self._need_edit()
        app = self.get_object()
        try:
            r = feishu_svc.sync_contacts(
                app, sso_name_prefix=(request.data.get("sso_name") or "").strip() or None)
            app = FeishuApp.objects.get(pk=app.pk)
            write_audit(request.user, "execute", "FeishuContactsSync", app.pk,
                        after={**r, "app": app.name},
                        source_ip=request.META.get("REMOTE_ADDR", ""))
            return Response(r)
        except feishu_svc.RequiresCalibration as e:
            return Response({"ok": False, "calibration": True, "detail": str(e)[:200]},
                            status=400)
