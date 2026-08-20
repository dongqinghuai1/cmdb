from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.monitor.models import CollectorNode, LogRecord
from common.permissions import RbacPermission
from django.utils import timezone


class CollectorNodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CollectorNode
        fields = "__all__"


class LogRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = LogRecord
        fields = ["id", "device_id", "source", "severity", "facility", "message", "occurred_at"]


SEV_NAMES = {0: "emerg", 1: "alert", 2: "crit", 3: "error", 4: "warning",
             5: "notice", 6: "info", 7: "debug"}


class CollectorNodeViewSet(viewsets.ModelViewSet):
    queryset = CollectorNode.objects.all()
    serializer_class = CollectorNodeSerializer
    permission_classes = [RbacPermission]
    required_perm = "monitor.collector.view"

    @action(detail=True, methods=["post"])
    def heartbeat(self, request, pk=None):
        node = self.get_object()
        node.last_heartbeat_at = timezone.now()
        node.status = "active"
        node.save(update_fields=["last_heartbeat_at", "status", "updated_at"])
        return Response({"ok": True, "ts": node.last_heartbeat_at})


class LogRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """日志检索：severity_lte（如 =3 只看 error 及以上）、occurred_after/before、
    keyword(message 包含)、device_id。"""
    queryset = LogRecord.objects.order_by("-occurred_at")
    serializer_class = LogRecordSerializer
    permission_classes = [RbacPermission]
    required_perm = "monitor.log.view"
    filterset_fields = ["device_id", "source", "facility"]

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("severity_lte"):
            qs = qs.filter(severity__lte=int(p["severity_lte"]))
        if p.get("keyword"):
            qs = qs.filter(message__icontains=p["keyword"])
        if p.get("occurred_after"):
            qs = qs.filter(occurred_at__gte=p["occurred_after"])
        if p.get("occurred_before"):
            qs = qs.filter(occurred_at__lte=p["occurred_before"])
        return qs

    @action(detail=False, methods=["post"], url_path="test-write")
    def test_write(self, request):
        """写入一条测试日志（演示/联调 syslog 链路）。body: {message, severity?, device?}"""
        rec = LogRecord.objects.create(
            device_id=request.data.get("device"),
            source="platform", facility="user",
            severity=int(request.data.get("severity", 6)),
            message=str(request.data.get("message", "nops test log"))[:8000])
        return Response({"id": rec.id, "occurred_at": rec.occurred_at})

    @action(detail=False, methods=["get"])
    def severity_choices(self, request):
        return Response(SEV_NAMES)
