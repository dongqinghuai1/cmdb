"""apps.automate views -- 脚本库 / 执行单(灰度+审批闭环) / 通用审批 API。

权限点（init_nops_data 同步）：automate.script.view|edit、automate.run.view|execute、automate.approve。
视图声明单一 required_perm；编辑/执行/审批等细粒度在动作内二次校验 has_perm 或身份。
"""
from django.db.models import Count, Q
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.automate import services
from apps.automate.models import (Approval, FirmwarePackage, FirmwareUpgradePlan,
                                  Script, ScriptRun, ScriptRunDetail)
from apps.system.views import BaseModelViewSet
from common.audit import write_audit
from common.permissions import RbacPermission, has_perm


def _request_ip(request) -> str:
    meta = getattr(request, "META", {}) or {}
    return (meta.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            or meta.get("REMOTE_ADDR", ""))


def _run_view_call(fn, *args, **kwargs):
    """把业务层异常映射为 DRF 4xx：ValueError->400，PermissionError->403。"""
    try:
        return fn(*args, **kwargs)
    except PermissionError as e:
        raise PermissionDenied(str(e))
    except ValueError as e:
        raise ValidationError(str(e))


# ============ 序列化器 ============

class ScriptSerializer(serializers.ModelSerializer):
    danger_label = serializers.CharField(source="get_danger_level_display", read_only=True)
    type_label = serializers.CharField(source="get_script_type_display", read_only=True)
    requires_approval = serializers.BooleanField(read_only=True)

    class Meta:
        model = Script
        fields = ["id", "name", "category", "script_type", "type_label", "content",
                  "params_schema", "danger_level", "danger_label", "requires_approval",
                  "enabled", "remark", "created_by_id", "created_at", "updated_at"]


class ScriptRunSerializer(serializers.ModelSerializer):
    executed_by_name = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()
    gray_remaining = serializers.SerializerMethodField()

    class Meta:
        model = ScriptRun
        fields = ["id", "script_id", "script_name_snapshot", "script_type_snapshot",
                  "danger_snapshot", "trigger", "executed_by_id", "executed_by_name",
                  "approval_id", "status", "scope", "gray_batch", "gray_remaining",
                  "summary", "started_at", "finished_at", "created_at", "stats"]

    def get_executed_by_name(self, obj):
        return (self.context.get("users") or {}).get(obj.executed_by_id, "")

    def get_stats(self, obj):
        return (self.context.get("stats") or {}).get(obj.id, {})

    def get_gray_remaining(self, obj):
        gb = obj.gray_batch or {}
        if not gb.get("enabled"):
            return 0
        return max(int(gb.get("total", 0)) - int(gb.get("dispatched", 0)), 0)


class ScriptRunDetailSerializer(serializers.ModelSerializer):
    device_name = serializers.SerializerMethodField()

    class Meta:
        model = ScriptRunDetail
        fields = ["id", "device_id", "device_name", "status", "output", "error", "executed_at"]

    def get_device_name(self, obj):
        return (self.context.get("devices") or {}).get(obj.device_id, {}).get("name", "-")


class ApprovalSerializer(serializers.ModelSerializer):
    applicant_name = serializers.SerializerMethodField()
    approver_name = serializers.SerializerMethodField()
    biz_title = serializers.SerializerMethodField()
    run_status = serializers.SerializerMethodField()
    run_danger = serializers.SerializerMethodField()

    class Meta:
        model = Approval
        fields = ["id", "biz_type", "biz_id", "applicant_id", "applicant_name",
                  "approver_id", "approver_name", "status", "comment",
                  "created_at", "decided_at", "biz_title", "run_status", "run_danger"]

    def get_applicant_name(self, obj):
        return (self.context.get("users") or {}).get(obj.applicant_id, "")

    def get_approver_name(self, obj):
        return (self.context.get("users") or {}).get(obj.approver_id, "")

    def get_biz_title(self, obj):
        run = (self.context.get("runs") or {}).get(obj.biz_id) or {}
        return run.get("script_name", "")

    def get_run_status(self, obj):
        run = (self.context.get("runs") or {}).get(obj.biz_id) or {}
        return run.get("status", "")

    def get_run_danger(self, obj):
        run = (self.context.get("runs") or {}).get(obj.biz_id) or {}
        return run.get("danger", "")


# ============ 脚本库 ============

class ScriptViewSet(BaseModelViewSet):
    queryset = Script.objects.all()
    serializer_class = ScriptSerializer
    required_perm = "automate.script.view"
    search_fields = ["name", "category", "remark"]
    filterset_fields = ["category", "script_type", "danger_level", "enabled"]

    def _guard_edit(self):
        if not (self.request.user.is_superuser or has_perm(self.request.user, "automate.script.edit")):
            raise PermissionDenied("无脚本编辑权限（automate.script.edit）")

    def perform_create(self, serializer):
        self._guard_edit()
        obj = serializer.save(created_by_id=self.request.user.id)
        write_audit(self.request.user, "create", "Script", obj.pk,
                    after={"name": obj.name, "danger": obj.danger_level})

    def perform_update(self, serializer):
        self._guard_edit()
        before = {f.name: getattr(serializer.instance, f.name, None)
                  for f in serializer.instance._meta.fields
                  if f.name not in ("created_at", "updated_at")}
        before.pop("content", None)
        obj = serializer.save()
        after = dict(serializer.validated_data)
        after.pop("content", None)
        write_audit(self.request.user, "update", "Script", obj.pk,
                    before=before, after=after)

    def perform_destroy(self, instance):
        self._guard_edit()
        if ScriptRun.objects.filter(script_id=instance.pk).exists():
            raise ValidationError("该脚本已有执行记录，不能删除（可改为停用 enabled=false）")
        name = instance.name
        super().perform_destroy(instance)
        write_audit(self.request.user, "delete", "Script", instance.pk,
                    before={"name": name})


# ============ 批量执行 ============

class ScriptRunViewSet(viewsets.ReadOnlyModelViewSet):
    http_method_names = ["get", "post", "head", "options"]
    queryset = ScriptRun.objects.all()
    serializer_class = ScriptRunSerializer
    permission_classes = [RbacPermission]
    required_perm = "automate.run.view"
    filterset_fields = ["script_id", "status", "trigger", "executed_by_id"]

    # ---------- 数据装配 ----------

    @staticmethod
    def _stats_map(run_ids):
        """每 run 的 {pending,running,success,failed,total,done} 计数。"""
        rows = (ScriptRunDetail.objects.filter(run_id__in=run_ids)
                .values("run_id", "status").order_by()
                .annotate(cnt=Count("id")))
        out: dict[int, dict] = {}
        for r in rows:
            out.setdefault(r["run_id"], {})[r["status"]] = r["cnt"]
        for rid in run_ids:
            s = out.setdefault(rid, {})
            s["total"] = sum(s.values())
            s["done"] = s.get("success", 0) + s.get("failed", 0)
        return out

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        items = page if page is not None else self.filter_queryset(self.get_queryset())
        ser = self.get_serializer(items, many=True, context=self._context(items))
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        ser = self.get_serializer(obj, context=self._context([obj]))
        return Response(ser.data)

    def _context(self, runs):
        runs = list(runs)
        return {"users": services.fetch_users([r.executed_by_id for r in runs]),
                "stats": self._stats_map([r.id for r in runs])}

    # ---------- 创建（含高危审批分支） ----------

    def create(self, request, *args, **kwargs):
        run, need_approval, approval = _run_view_call(
            services.create_run, request.user, request.data, source_ip=_request_ip(request))
        ser = self.get_serializer(run, context=self._context([run]))
        return Response({"run": ser.data, "need_approval": need_approval,
                         "approval_id": approval.id if approval else None,
                         "approver_id": approval.approver_id if approval else None},
                        status=status.HTTP_201_CREATED)

    # ---------- 状态动作 ----------

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        run = self.get_object()
        res = _run_view_call(services.start_run, request.user, run,
                             source_ip=_request_ip(request),
                             gray_first=request.data.get("gray_first"))
        return Response(res)

    @action(detail=True, methods=["post"], url_path="continue")
    def continue_run(self, request, pk=None):
        run = self.get_object()
        res = _run_view_call(services.continue_run, request.user, run,
                             source_ip=_request_ip(request))
        return Response(res)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        run = self.get_object()
        res = _run_view_call(services.cancel_run, request.user, run,
                             source_ip=_request_ip(request),
                             reason=request.data.get("reason", ""))
        return Response(res)

    @action(detail=True, methods=["get"])
    def details(self, request, pk=None):
        run = self.get_object()
        qs = run.details.all()
        page = self.paginate_queryset(qs)
        items = page if page is not None else qs
        devices = services.fetch_devices_brief([d.device_id for d in items])
        ser = ScriptRunDetailSerializer(items, many=True, context={"devices": devices})
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)


# ============ 通用审批 ============

class ApprovalViewSet(viewsets.ReadOnlyModelViewSet):
    http_method_names = ["get", "post", "head", "options"]
    queryset = Approval.objects.all()
    serializer_class = ApprovalSerializer
    permission_classes = [RbacPermission]
    # 审批入口对登录用户开放，行级过滤（approver/applicant 可见），细粒度身份校验在 decide_approval
    required_perm = None
    filterset_fields = ["status", "biz_type"]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser or has_perm(user, "automate.approve"):
            return qs
        return qs.filter(Q(approver_id=user.id) | Q(applicant_id=user.id))

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        items = page if page is not None else self.filter_queryset(self.get_queryset())
        ser = self.get_serializer(items, many=True, context=self._context(items))
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        ser = self.get_serializer(obj, context=self._context([obj]))
        return Response(ser.data)

    def _context(self, approvals):
        approvals = list(approvals)
        user_ids = {uid for a in approvals for uid in (a.applicant_id, a.approver_id)}
        run_ids = [a.biz_id for a in approvals if a.biz_type == Approval.BizType.SCRIPT_RUN]
        runs = {}
        for r in ScriptRun.objects.filter(pk__in=run_ids).only(
                "id", "script_name_snapshot", "danger_snapshot", "status"):
            runs[r.id] = {"script_name": r.script_name_snapshot,
                          "danger": r.danger_snapshot, "status": r.status}
        return {"users": services.fetch_users(user_ids), "runs": runs}

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        return self._decide(request, approved=True)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        return self._decide(request, approved=False)

    def _decide(self, request, approved: bool):
        obj = self.get_object()
        res = _run_view_call(services.decide_approval, request.user, obj, approved,
                             comment=request.data.get("comment", ""),
                             source_ip=_request_ip(request))
        return Response(res)


# ============ 固件版本库 ============

class FirmwarePackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = FirmwarePackage
        fields = ["id", "name", "vendor", "hw_model", "version", "file_name",
                  "file_size", "sha256", "notes", "created_by_id",
                  "created_at", "updated_at"]


class FirmwarePackageViewSet(BaseModelViewSet):
    queryset = FirmwarePackage.objects.all()
    serializer_class = FirmwarePackageSerializer
    required_perm = "automate.run.view"
    search_fields = ["name", "vendor", "hw_model", "version"]
    filterset_fields = ["vendor", "hw_model"]

    def _guard(self):
        if not (self.request.user.is_superuser
                or has_perm(self.request.user, "automate.script.edit")):
            raise PermissionDenied("无固件库编辑权限（automate.script.edit）")

    def perform_create(self, serializer):
        self._guard()
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._guard()
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        self._guard()
        if FirmwareUpgradePlan.objects.filter(package_id=instance.pk).exists():
            raise ValidationError("该固件已被升级计划引用，不能删除（历史快照依赖登记信息）")
        super().perform_destroy(instance)


# ============ 固件升级计划 ============

class FirmwareUpgradePlanSerializer(serializers.ModelSerializer):
    device_name = serializers.SerializerMethodField()
    executed_by_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = FirmwareUpgradePlan
        fields = ["id", "device_id", "device_name", "package_id",
                  "package_name_snapshot", "package_version_snapshot", "current_version",
                  "status", "status_label", "scheduled_at", "executed_at",
                  "executed_by_id", "executed_by_name", "result_log", "error",
                  "created_at", "updated_at"]
        read_only_fields = ["package_name_snapshot", "package_version_snapshot",
                            "status", "result_log", "error", "executed_at",
                            "executed_by_id"]

    def get_device_name(self, obj):
        return (self.context.get("devices") or {}).get(obj.device_id, {}).get("name", "-")

    def get_executed_by_name(self, obj):
        return (self.context.get("users") or {}).get(obj.executed_by_id, "") if obj.executed_by_id else ""


class FirmwareUpgradePlanViewSet(viewsets.ModelViewSet):
    queryset = FirmwareUpgradePlan.objects.all()
    serializer_class = FirmwareUpgradePlanSerializer
    permission_classes = [RbacPermission]
    required_perm = "automate.run.view"
    http_method_names = ["get", "post", "delete", "head", "options"]
    filterset_fields = ["device_id", "package_id", "status"]

    # ---------- 数据装配 ----------

    def _context(self, plans):
        plans = list(plans)
        dev_ids = [p.device_id for p in plans]
        uids = [p.executed_by_id for p in plans if p.executed_by_id]
        return {"devices": services.fetch_devices_brief(dev_ids),
                "users": services.fetch_users(uids)}

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        items = page if page is not None else self.filter_queryset(self.get_queryset())
        ser = self.get_serializer(items, many=True, context=self._context(items))
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        ser = self.get_serializer(obj, context=self._context([obj]))
        return Response(ser.data)

    # ---------- 创建/删除 ----------

    def create(self, request, *args, **kwargs):
        if not (request.user.is_superuser or has_perm(request.user, "automate.run.execute")):
            raise PermissionDenied("无实施权限（automate.run.execute），不能建升级计划")
        plan = _run_view_call(services.create_firmware_plan, request.user,
                              request.data, source_ip=_request_ip(request))
        ser = self.get_serializer(plan, context=self._context([plan]))
        return Response(ser.data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        if not (self.request.user.is_superuser
                or has_perm(self.request.user, "automate.run.execute")):
            raise PermissionDenied("无实施权限（automate.run.execute）")
        if instance.status in (FirmwareUpgradePlan.Status.PENDING,
                               FirmwareUpgradePlan.Status.READY,
                               FirmwareUpgradePlan.Status.RUNNING):
            raise ValidationError("进行中计划不能删除，请先取消（cancel）")
        super().perform_destroy(instance)

    # ---------- 状态动作 ----------

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        """执行升级作业。body: {mock?:0|1, confirm?:true}。mock 演练默认 0（真实=只读预检+编排）。"""
        from apps.automate.tasks import firmware_upgrade
        plan = self.get_object()
        if not (request.user.is_superuser or has_perm(request.user, "automate.run.execute")):
            raise PermissionDenied("无实施权限（automate.run.execute）")
        if not request.data.get("confirm"):
            raise ValidationError("confirm=true 必填（升级为高危操作，需二次确认）")
        if plan.status not in (FirmwareUpgradePlan.Status.PENDING,
                               FirmwareUpgradePlan.Status.READY,
                               FirmwareUpgradePlan.Status.FAILED,
                               FirmwareUpgradePlan.Status.SUCCESS):
            raise ValidationError(f"当前状态 {plan.status} 不可执行")
        mock = bool(request.data.get("mock") or 0)
        plan.status = FirmwareUpgradePlan.Status.RUNNING
        plan.executed_by_id = request.user.id
        plan.save(update_fields=["status", "executed_by_id", "updated_at"])
        write_audit(request.user, "execute", "FirmwareUpgradePlan", plan.pk,
                    after={"status": plan.status, "mock": mock},
                    source_ip=_request_ip(request))
        res = firmware_upgrade.delay(plan.pk, mock)  # EAGER 环境内联完成
        plan.refresh_from_db()
        return Response({"task": getattr(res, "id", None), "plan_id": plan.id,
                         "status": plan.status,
                         "detail": (plan.error or plan.result_log or "")[:200]})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """取消计划（pending/ready/failed 可取消）。"""
        if not (request.user.is_superuser or has_perm(request.user, "automate.run.execute")):
            raise PermissionDenied("无实施权限（automate.run.execute）")
        plan = self.get_object()
        res = _run_view_call(services.cancel_firmware_plan, request.user, plan,
                             reason=request.data.get("reason", ""),
                             source_ip=_request_ip(request))
        return Response(res)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        """固件升级总览：按状态计数 + 最近进行中 + 设备最近一次目标/当前版本对照。"""
        from django.db.models import Count
        counts = dict(FirmwareUpgradePlan.objects.order_by()
                      .values_list("status").annotate(c=Count("id")))
        rows = list(FirmwareUpgradePlan.objects.order_by("device_id", "-id")
                    .values("id", "device_id", "status",
                            "package_name_snapshot", "package_version_snapshot"))
        latest, latest_by_dev = [], {}
        for r in rows:
            latest_by_dev.setdefault(r["device_id"], r)
        return Response({
            "counts": counts,
            "devices": len(latest_by_dev),
            "latest": list(latest_by_dev.values())[:50],
        })
