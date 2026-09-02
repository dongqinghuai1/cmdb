"""apps.report API：快照查询/手动生成 + 报表订阅 CRUD/立即运行。"""
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.report.models import ReportSchedule, ReportSnapshot
from apps.report import services
from common.permissions import RbacPermission, has_perm


class ReportSnapshotSerializer(serializers.ModelSerializer):
    report_type_label = serializers.CharField(source="get_report_type_display", read_only=True)

    class Meta:
        model = ReportSnapshot
        fields = ["id", "report_type", "report_type_label", "period_start", "period_end",
                  "content", "built_by", "duration_ms", "remark", "created_at"]


class ReportScheduleSerializer(serializers.ModelSerializer):
    report_type_label = serializers.CharField(source="get_report_type_display", read_only=True)

    class Meta:
        model = ReportSchedule
        fields = ["id", "name", "report_type", "report_type_label", "hour", "enabled",
                  "notify_channel_ids", "receivers", "remark", "last_run_at",
                  "created_by_id", "created_at", "updated_at"]
        read_only_fields = ["last_run_at", "created_by_id"]


class ReportSnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ReportSnapshot.objects.all()
    serializer_class = ReportSnapshotSerializer
    permission_classes = [RbacPermission]
    required_perm = "report.snapshot.view"
    filterset_fields = ["report_type", "built_by"]

    def get_queryset(self):
        qs = super().get_queryset()
        after = self.request.query_params.get("period_after")
        if after:
            qs = qs.filter(period_start__gte=after)
        return qs

    @action(detail=False, methods=["post"])
    def generate(self, request):
        """手动生成快照（幂等覆盖当日同类型）。body: {report_type, period_start?, remark?}"""
        if not (request.user.is_superuser or has_perm(request.user, "report.snapshot.edit")):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("无报表生成权限（report.snapshot.edit）")
        rtype = request.data.get("report_type")
        try:
            r = services.save_snapshot(rtype, request.data.get("period_start") or None,
                                       built_by="manual", remark=request.data.get("remark", ""))
        except ValueError as e:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(str(e))
        return Response(r, status=201)

    @action(detail=False, methods=["get"], url_path="latest")
    def latest(self, request):
        """每种报表最近一份（看板用）。body query: report_type=? 可选限定。"""
        types = request.query_params.get("report_type")
        wanted = [types] if types else list(ReportSnapshot.Type.values)
        out = {}
        for t in wanted:
            snap = ReportSnapshot.objects.filter(report_type=t).first()
            if snap:
                out[t] = ReportSnapshotSerializer(snap).data
        return Response(out)


class ReportScheduleViewSet(viewsets.ModelViewSet):
    queryset = ReportSchedule.objects.all()
    serializer_class = ReportScheduleSerializer
    permission_classes = [RbacPermission]
    required_perm = "report.snapshot.view"
    search_fields = ["name", "remark"]

    def _need_edit(self):
        if not (self.request.user.is_superuser or has_perm(self.request.user, "report.snapshot.edit")):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("无报表订阅编辑权限（report.snapshot.edit）")

    def perform_create(self, serializer):
        self._need_edit()
        serializer.save(created_by_id=self.request.user.id)

    def perform_update(self, serializer):
        self._need_edit()
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        self._need_edit()
        super().perform_destroy(instance)

    @action(detail=True, methods=["post"])
    def run(self, request, pk=None):
        """立即为该订阅生成当日快照。"""
        self._need_edit()
        sched = self.get_object()
        try:
            r = services.save_snapshot(sched.report_type, built_by="manual",
                                       remark=f"订阅[{sched.name}] 手动触发")
        except ValueError as e:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(str(e))
        from django.utils import timezone
        sched.last_run_at = timezone.now()
        sched.save(update_fields=["last_run_at", "updated_at"])
        return Response(r, status=201)

    @action(detail=False, methods=["get"], url_path="overview")
    def overview(self, request):
        """订阅总览：订阅数 + 启用数 + 各类型最近快照时间。"""
        snaps = {}
        for snap in ReportSnapshot.objects.order_by("-period_start"):
            if snap.report_type not in snaps:
                snaps[snap.report_type] = snap.period_start.isoformat()
        return Response({
            "schedules": ReportSchedule.objects.count(),
            "enabled": ReportSchedule.objects.filter(enabled=True).count(),
            "latest_per_type": snaps,
        })
