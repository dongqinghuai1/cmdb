from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.ncm.models import (BaselineCheckResult, BaselineRule, ConfigBackup,
                             ConfigChangeEvent)
from apps.ncm.services import run_baseline
from apps.system.views import BaseModelViewSet
from common.permissions import RbacPermission


class ConfigBackupSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfigBackup
        fields = ["id", "device_id", "backup_type", "trigger", "size", "file_hash", "created_at"]


class ConfigChangeEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfigChangeEvent
        fields = "__all__"


class BaselineRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = BaselineRule
        fields = "__all__"


class BaselineResultSerializer(serializers.ModelSerializer):
    rule_name = serializers.CharField(source="rule.name", read_only=True)

    class Meta:
        model = BaselineCheckResult
        fields = ["id", "rule", "rule_name", "device_id", "compliant", "matched_content", "created_at"]


class ConfigBackupViewSet(viewsets.ModelViewSet):
    http_method_names = ["get", "post"]
    queryset = ConfigBackup.objects.order_by("-created_at")
    serializer_class = ConfigBackupSerializer
    permission_classes = [RbacPermission]
    required_perm = "cmdb.device.view"
    filterset_fields = ["device_id", "trigger", "backup_type"]

    @action(detail=True, methods=["get"])
    def content(self, request, pk=None):
        return Response({"content": self.get_object().content or ""})

    @action(detail=False, methods=["get"])
    def diff(self, request):
        """GET /ncm/backups/diff/?a=<id>&b=<id> -> unified diff."""
        a = ConfigBackup.objects.filter(pk=request.query_params.get("a")).first()
        b = ConfigBackup.objects.filter(pk=request.query_params.get("b")).first()
        if not a or not b:
            return Response({"detail": "a/b backup ids required"}, status=400)
        import difflib
        diff = "\n".join(difflib.unified_diff(
            (a.content or "").splitlines(), (b.content or "").splitlines(),
            fromfile=f"#{a.id}", tofile=f"#{b.id}", lineterm=""))
        return Response({"diff": diff, "changed_lines": diff.count("\n+") + diff.count("\n-")})

    @action(detail=False, methods=["post"], url_path="trigger")
    def trigger_backup(self, request):
        dev = request.data.get("device")
        if not dev:
            return Response({"detail": "device required"}, status=400)
        from apps.ncm.tasks import backup_device
        r = backup_device.delay(int(dev))
        return Response({"task": r.id, "msg": "已下发备份任务（SSH 失败可用导入）"})

    @action(detail=False, methods=["post"], url_path="import")
    def import_config(self, request):
        """手工粘贴配置（SSH 不通/演示用）。body: {device, content, backup_type?}"""
        dev, content = request.data.get("device"), request.data.get("content", "")
        if not dev or not content:
            return Response({"detail": "device/content required"}, status=400)
        from apps.ncm.services import save_backup
        backup, changed = save_backup(int(dev), content, trigger="import",
                                      backup_type=request.data.get("backup_type", "running"))
        return Response({"backup": backup.id, "changed": changed,
                         "dedup": backup.file_hash[:12]})


class ConfigChangeEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ConfigChangeEvent.objects.order_by("-detected_at")
    serializer_class = ConfigChangeEventSerializer
    permission_classes = [RbacPermission]
    required_perm = "cmdb.device.view"
    filterset_fields = ["device_id"]


class BaselineRuleViewSet(BaseModelViewSet):
    queryset = BaselineRule.objects.all()
    serializer_class = BaselineRuleSerializer
    required_perm = "cmdb.device.view"

    @action(detail=False, methods=["post"], url_path="check")
    def check(self, request):
        n = run_baseline(request.data.get("rule_ids"))
        return Response({"checked": n})


class BaselineResultViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BaselineCheckResult.objects.order_by("-id")
    serializer_class = BaselineResultSerializer
    permission_classes = [RbacPermission]
    required_perm = "cmdb.device.view"
    filterset_fields = ["rule", "device_id", "compliant"]
