"""apps.change views -- 轻量事件单（ER 4.13）：报障/分派/处理/反馈/关闭 + 时间线。

权限点：change.incident.view / change.incident.edit（init_nops_data 同步）。
细粒度参与人校验在 services._can（报障人/处理人/具备 edit 权限者）。
"""
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.change import services
from apps.change.models import ChangeTicket, IncidentEvent, IncidentTicket
from common.audit import write_audit
from common.permissions import RbacPermission, has_perm


def _request_ip(request) -> str:
    meta = getattr(request, "META", {}) or {}
    return (meta.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            or meta.get("REMOTE_ADDR", ""))


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except PermissionError as e:
        raise PermissionDenied(str(e))
    except ValueError as e:
        raise ValidationError(str(e))


class IncidentEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    event_type_label = serializers.CharField(source="get_event_type_display", read_only=True)

    class Meta:
        model = IncidentEvent
        fields = ["id", "event_type", "event_type_label", "actor_id", "actor_name",
                  "content", "created_at"]

    def get_actor_name(self, obj):
        return (self.context.get("users") or {}).get(obj.actor_id, "-")


class IncidentTicketSerializer(serializers.ModelSerializer):
    reporter_name = serializers.SerializerMethodField()
    handler_name = serializers.SerializerMethodField()
    device_name = serializers.SerializerMethodField()
    alert_title = serializers.SerializerMethodField()
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    overdue = serializers.SerializerMethodField()
    events = serializers.SerializerMethodField()

    class Meta:
        model = IncidentTicket
        fields = ["id", "ticket_no", "title", "source", "source_label", "reporter_id",
                  "reporter_name", "handler_id", "handler_name", "priority", "priority_label",
                  "status", "status_label", "related_alert_event_id", "alert_title",
                  "device_id", "device_name", "sla_deadline", "overdue", "closed_at",
                  "description", "resolution", "created_at", "updated_at", "events"]

    def get_reporter_name(self, obj):
        return (self.context.get("users") or {}).get(obj.reporter_id, "")

    def get_handler_name(self, obj):
        return (self.context.get("users") or {}).get(obj.handler_id or -1, "") if obj.handler_id else ""

    def get_device_name(self, obj):
        return (self.context.get("devices") or {}).get(obj.device_id or -1, "") if obj.device_id else ""

    def get_alert_title(self, obj):
        alert = (self.context.get("alerts") or {}).get(obj.related_alert_event_id or -1)
        return (alert or {}).get("title", "") if obj.related_alert_event_id else ""

    def get_overdue(self, obj):
        return (obj.status != IncidentTicket.Status.CLOSED
                and bool(obj.sla_deadline) and obj.sla_deadline < timezone.now())

    def get_events(self, obj):
        # 仅详情/创建回显时带时间线；列表接口 events=[] 不查库
        if not self.context.get("with_events"):
            return []
        evs = list(obj.events.all())
        self.context.setdefault("users", {})
        return IncidentEventSerializer(evs, many=True,
                                       context={"users": self.context["users"]}).data


class IncidentTicketViewSet(viewsets.ModelViewSet):
    http_method_names = ["get", "post", "head", "options"]
    queryset = IncidentTicket.objects.all()
    serializer_class = IncidentTicketSerializer
    permission_classes = [RbacPermission]
    required_perm = "change.incident.view"
    search_fields = ["ticket_no", "title", "description"]
    filterset_fields = ["status", "priority", "source", "handler_id", "device_id"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("overdue"):
            qs = qs.exclude(status=IncidentTicket.Status.CLOSED).filter(sla_deadline__lt=timezone.now())
        if self.request.query_params.get("mine") == "reported":
            qs = qs.filter(reporter_id=self.request.user.id)
        if self.request.query_params.get("mine") == "handled":
            qs = qs.filter(handler_id=self.request.user.id)
        return qs

    # ---------- 装配 ----------

    @staticmethod
    def _ctx(tickets, with_events=False):
        tickets = list(tickets)
        uids = set()
        for t in tickets:
            uids.add(t.reporter_id)
            if t.handler_id:
                uids.add(t.handler_id)
            if with_events:
                uids.update(e for e in IncidentEvent.objects
                            .filter(ticket_id__in=[t.id for t in tickets])
                            .values_list("actor_id", flat=True) if e)
        alerts = services.fetch_alert_events(
            [t.related_alert_event_id for t in tickets if t.related_alert_event_id])
        return {"users": services.fetch_users(uids),
                "devices": services.fetch_device_names(
                    [t.device_id for t in tickets if t.device_id]),
                "alerts": alerts,
                "with_events": with_events}

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        items = page if page is not None else self.filter_queryset(self.get_queryset())
        ser = self.get_serializer(items, many=True, context=self._ctx(items))
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        ser = self.get_serializer(obj, context=self._ctx([obj], with_events=True))
        return Response(ser.data)

    def create(self, request, *args, **kwargs):
        if not (request.user.is_superuser or has_perm(request.user, "change.incident.edit")):
            raise PermissionDenied("无事件单报障权限（change.incident.edit）")
        res = _run(services.create_ticket, request.user, request.data,
                   source_ip=_request_ip(request))
        ticket = IncidentTicket.objects.get(pk=res["id"])
        ser = self.get_serializer(ticket, context=self._ctx([ticket], with_events=True))
        return Response(ser.data, status=status.HTTP_201_CREATED)

    # ---------- 状态动作 ----------

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        return Response(_run(services.assign_ticket, request.user, self.get_object(),
                             request.data, source_ip=_request_ip(request)))

    @action(detail=True, methods=["post"], url_path="start")
    def start_handle(self, request, pk=None):
        return Response(_run(services.start_ticket, request.user, self.get_object(),
                             request.data, source_ip=_request_ip(request)))

    @action(detail=True, methods=["post"])
    def feedback(self, request, pk=None):
        return Response(_run(services.feedback_ticket, request.user, self.get_object(),
                             request.data, source_ip=_request_ip(request)))

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        return Response(_run(services.close_ticket, request.user, self.get_object(),
                             request.data, source_ip=_request_ip(request)))

    @action(detail=True, methods=["post"])
    def comment(self, request, pk=None):
        return Response(_run(services.comment_ticket, request.user, self.get_object(),
                             request.data, source_ip=_request_ip(request)))

    @action(detail=False, methods=["get"], url_path="my-stats")
    def my_stats(self, request):
        """工作台用：我的报障/待我处理计数。"""
        base = IncidentTicket.objects
        return Response({
            "reported": base.filter(reporter_id=request.user.id)
                            .exclude(status=IncidentTicket.Status.CLOSED).count(),
            "handled": base.filter(handler_id=request.user.id)
                           .exclude(status=IncidentTicket.Status.CLOSED).count(),
            "overdue": base.exclude(status=IncidentTicket.Status.CLOSED)
                           .filter(sla_deadline__lt=timezone.now()).count(),
        })


# ================= 轻量变更单（ER 4.13 / 12.2-5） =================

class ChangeTicketSerializer(serializers.ModelSerializer):
    applicant_name = serializers.SerializerMethodField()
    implementer_name = serializers.SerializerMethodField()
    verifier_name = serializers.SerializerMethodField()
    approver_name = serializers.SerializerMethodField()
    approval_status = serializers.SerializerMethodField()
    approval_comment = serializers.SerializerMethodField()
    script_run_name = serializers.SerializerMethodField()
    change_type_label = serializers.CharField(source="get_change_type_display", read_only=True)
    risk_label = serializers.CharField(source="get_risk_level_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ChangeTicket
        fields = ["id", "ticket_no", "title", "change_type", "change_type_label",
                  "risk_level", "risk_label", "plan_start", "plan_end",
                  "actual_start", "actual_end", "status", "status_label",
                  "applicant_id", "applicant_name", "implementer_id", "implementer_name",
                  "verifier_id", "verifier_name", "approver_id", "approver_name",
                  "approval_id", "approval_status", "approval_comment",
                  "content", "related_script_run_id", "script_run_name",
                  "related_config_event_id", "rollback_plan", "result_desc",
                  "created_at", "updated_at"]

    def get_applicant_name(self, obj):
        return (self.context.get("users") or {}).get(obj.applicant_id, "")

    def get_implementer_name(self, obj):
        return (self.context.get("users") or {}).get(obj.implementer_id or -1, "") if obj.implementer_id else ""

    def get_verifier_name(self, obj):
        return (self.context.get("users") or {}).get(obj.verifier_id or -1, "") if obj.verifier_id else ""

    def get_approver_name(self, obj):
        return (self.context.get("users") or {}).get(obj.approver_id or -1, "") if obj.approver_id else ""

    def get_approval_status(self, obj):
        ap = (self.context.get("approvals") or {}).get(obj.approval_id or -1)
        return (ap or {}).get("status", "") if obj.approval_id else ""

    def get_approval_comment(self, obj):
        ap = (self.context.get("approvals") or {}).get(obj.approval_id or -1)
        return (ap or {}).get("comment", "") if obj.approval_id else ""

    def get_script_run_name(self, obj):
        ap = (self.context.get("script_runs") or {}).get(obj.related_script_run_id or -1)
        return (ap or {}).get("name", "") if obj.related_script_run_id else ""


def _fetch_approvals(ids) -> dict:
    """automate_approval 审批行（仅 status/comment，供变更单回显）。"""
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    from django.db import connection
    ph = ",".join(["%s"] * len(ids))
    with connection.cursor() as cur:
        cur.execute(f"SELECT id, status, comment FROM automate_approval WHERE id IN ({ph})", ids)
        return {r[0]: {"status": r[1], "comment": r[2]} for r in cur.fetchall()}


def _fetch_script_runs(ids) -> dict:
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    from django.db import connection
    ph = ",".join(["%s"] * len(ids))
    with connection.cursor() as cur:
        cur.execute(f"SELECT id, script_name_snapshot, status FROM automate_scriptrun WHERE id IN ({ph})", ids)
        return {r[0]: {"name": r[1], "status": r[2]} for r in cur.fetchall()}


class ChangeTicketViewSet(viewsets.ModelViewSet):
    http_method_names = ["get", "post", "head", "options"]
    queryset = ChangeTicket.objects.all()
    serializer_class = ChangeTicketSerializer
    permission_classes = [RbacPermission]
    required_perm = "change.ticket.view"
    search_fields = ["ticket_no", "title", "result_desc"]
    filterset_fields = ["status", "risk_level", "change_type"]

    def get_queryset(self):
        qs = super().get_queryset()
        mine = self.request.query_params.get("mine")
        if mine == "applicant":
            qs = qs.filter(applicant_id=self.request.user.id)
        if mine == "implement":
            qs = qs.filter(implementer_id=self.request.user.id)
        if mine == "verify":
            qs = qs.filter(verifier_id=self.request.user.id)
        if self.request.query_params.get("approving") == "1":
            qs = qs.filter(status=ChangeTicket.Status.APPROVING)
        return qs

    @staticmethod
    def _ctx(items):
        items = list(items)
        users = services.fetch_users(
            {v for t in items for v in
             (t.applicant_id, t.implementer_id, t.verifier_id, t.approver_id) if v})
        return {"users": users,
                "approvals": _fetch_approvals(
                    [t.approval_id for t in items if t.approval_id]),
                "script_runs": _fetch_script_runs(
                    [t.related_script_run_id for t in items if t.related_script_run_id])}

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        items = page if page is not None else self.filter_queryset(self.get_queryset())
        ser = self.get_serializer(items, many=True, context=self._ctx(items))
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        ser = self.get_serializer(obj, context=self._ctx([obj]))
        return Response(ser.data)

    def create(self, request, *args, **kwargs):
        if not (request.user.is_superuser or has_perm(request.user, "change.ticket.edit")):
            raise PermissionDenied("无变更单申请权限（change.ticket.edit）")
        res = _run(services.create_change_ticket, request.user, request.data,
                   source_ip=_request_ip(request))
        t = ChangeTicket.objects.get(pk=res["id"])
        ser = self.get_serializer(t, context=self._ctx([t]))
        return Response(ser.data, status=status.HTTP_201_CREATED)

    # ---------- 生命周期动作 ----------

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return Response(_run(services.submit_change_ticket, request.user, self.get_object(),
                             request.data, source_ip=_request_ip(request)))

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return Response(_run(services.decide_change_ticket, request.user, self.get_object(),
                             "approve", request.data, source_ip=_request_ip(request)))

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return Response(_run(services.decide_change_ticket, request.user, self.get_object(),
                             "reject", request.data, source_ip=_request_ip(request)))

    @action(detail=True, methods=["post"], url_path="start")
    def start_impl(self, request, pk=None):
        return Response(_run(services.start_change_impl, request.user, self.get_object(),
                             request.data, source_ip=_request_ip(request)))

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        return Response(_run(services.verify_change, request.user, self.get_object(),
                             request.data, source_ip=_request_ip(request)))

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        return Response(_run(services.close_change, request.user, self.get_object(),
                             request.data, source_ip=_request_ip(request)))

    @action(detail=True, methods=["post"])
    def rollback(self, request, pk=None):
        return Response(_run(services.rollback_change, request.user, self.get_object(),
                             request.data, source_ip=_request_ip(request)))
