from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.permissions import RbacPermission
from apps.alert.models import AlertEvent, AlertRule, AlertSilence


class AlertRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertRule
        fields = "__all__"


class AlertEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertEvent
        fields = "__all__"


class AlertSilenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertSilence
        fields = "__all__"
        read_only_fields = ["created_by_id"]

    def create(self, validated_data):
        validated_data["created_by_id"] = self.context["request"].user.id
        return super().create(validated_data)


class AlertRuleViewSet(viewsets.ModelViewSet):
    queryset = AlertRule.objects.all()
    serializer_class = AlertRuleSerializer
    permission_classes = [RbacPermission]
    required_perm = "alert.rule.view"
    filterset_fields = ["rule_type", "enabled", "severity"]

    @action(detail=False, methods=["post"], url_path="evaluate")
    def evaluate(self, request):
        """手动触发一轮规则评估（告警引擎入口，供运维/测试用，同步执行）。"""
        from common.audit import write_audit
        from common.permissions import has_perm
        from rest_framework.exceptions import PermissionDenied
        from apps.alert.engine import evaluate_alert_rules
        if not (request.user.is_superuser or has_perm(request.user, "alert.rule.edit")):
            raise PermissionDenied("无告警规则管理权限，无法触发评估")
        r = evaluate_alert_rules()
        write_audit(request.user, "execute", "AlertRule", "evaluate",
                    after={**r, "action": "evaluate"},
                    source_ip=request.META.get("REMOTE_ADDR", ""))
        return Response(r)


class AlertSilenceViewSet(viewsets.ModelViewSet):
    """静默/维护窗口：scope={"device_ids":[..]} 或 {"all":true}；ended_at 空则到期自动失效。"""
    queryset = AlertSilence.objects.order_by("-id")
    serializer_class = AlertSilenceSerializer
    permission_classes = [RbacPermission]
    required_perm = "alert.rule.edit"
    filterset_fields = ["silence_type"]

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        """提前结束静默。"""
        from django.utils import timezone
        s = self.get_object()
        s.ended_at = timezone.now()
        s.save(update_fields=["ended_at", "updated_at"])
        return Response(AlertSilenceSerializer(s).data)


class AlertEventViewSet(viewsets.ModelViewSet):
    http_method_names = ["get", "patch", "post"]
    queryset = AlertEvent.objects.order_by("-id")
    serializer_class = AlertEventSerializer
    permission_classes = [RbacPermission]
    required_perm = "alert.event.view"
    filterset_fields = ["status", "severity", "device_id"]

    def create(self, request, *args, **kwargs):
        # 告警事件只由采集/规则引擎生成，禁止通过 API 伪造；保留 POST 仅用于动作路由
        from rest_framework.exceptions import MethodNotAllowed
        raise MethodNotAllowed("POST")

    @action(detail=True, methods=["post"])
    def ack(self, request, pk=None):
        ev = self.get_object()
        ev.status = "acknowledged"
        ev.acked_by_id = request.user.id
        ev.save(update_fields=["status", "acked_by_id", "acked_at"])
        return Response(AlertEventSerializer(ev).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        from django.utils import timezone
        ev = self.get_object()
        ev.status = "resolved"
        ev.resolved_at = timezone.now()
        ev.save(update_fields=["status", "resolved_at", "updated_at"])
        return Response(AlertEventSerializer(ev).data)

    @action(detail=True, methods=["post"], url_path="create-incident")
    def create_incident(self, request, pk=None):
        """告警联动 -> 轻量事件单（apps/change）。body: {note?}"""
        from apps.change import services as change_services
        from apps.change.models import IncidentTicket
        from common.permissions import has_perm
        from rest_framework.exceptions import PermissionDenied, ValidationError

        ev = self.get_object()
        if not (request.user.is_superuser or has_perm(request.user, "alert.event.execute")
                or has_perm(request.user, "change.incident.edit")):
            raise PermissionDenied("无告警处理权限，无法联动建单")
        try:
            res = change_services.create_from_alert(
                request.user, ev.id, note=request.data.get("note", ""))
        except ValueError as e:
            raise ValidationError(str(e))
        return Response({"incident_id": res["id"], "ticket_no": res["ticket_no"],
                         "status": res["status"]}, status=201)


from rest_framework.decorators import (api_view, authentication_classes,  # noqa: E402
                                       permission_classes)
from rest_framework.permissions import AllowAny  # noqa: E402


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def prometheus_webhook(request):
    """Alertmanager webhook → AlertEvent（监控贯通）。

    鉴权：若服务端配置 NOPS_PROM_WEBHOOK_TOKEN，则请求头 X-Webhook-Token 必须一致；
    设备关联：labels.instance 的 IP 匹配 CMDB manage_ip，未命中 device_id=0(未关联)；
    firing 去重(alertname+instance)递增 fired_count；resolved 关闭对应 active 事件。
    """
    import os

    from django.utils import timezone

    from apps.cmdb.models import Device
    token = (os.getenv("NOPS_PROM_WEBHOOK_TOKEN") or "").strip()
    if token and request.headers.get("X-Webhook-Token") != token:
        return Response({"detail": "bad token"}, status=403)
    payload = request.data or {}
    created = updated = resolved = 0
    for alert in payload.get("alerts") or []:
        labels = alert.get("labels") or {}
        ann = alert.get("annotations") or {}
        name = labels.get("alertname") or "prometheus"
        inst = str(labels.get("instance") or "").split(":")[0]
        dev = Device.objects.filter(manage_ip=inst, deleted_at__isnull=True).first()
        device_id = dev.pk if dev else 0
        dedup = f"{device_id}:prom:{name}:{inst}"
        severity = (labels.get("severity") or "warning")[:8]
        ev = (AlertEvent.objects.filter(dedup_key=dedup, status="firing")
              .order_by("-id").first())
        if (alert.get("status") or "firing") == "resolved":
            if ev:
                ev.status = "resolved"
                ev.resolved_at = timezone.now()
                ev.save(update_fields=["status", "resolved_at", "updated_at"])
                resolved += 1
            continue
        title = ann.get("summary") or f"[{name}] {inst}"
        if ev:
            ev.fired_count += 1
            ev.title = title[:255]
            ev.detail = {"labels": labels, "annotations": ann}
            ev.save(update_fields=["fired_count", "title", "detail", "updated_at"])
            updated += 1
        else:
            AlertEvent.objects.create(
                dedup_key=dedup, device_id=device_id, severity=severity,
                title=title[:255], detail={"labels": labels, "annotations": ann},
                status="firing")
            created += 1
    return Response({"ok": True, "created": created, "updated": updated,
                     "resolved": resolved})
