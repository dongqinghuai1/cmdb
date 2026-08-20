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


class AlertSilenceViewSet(viewsets.ModelViewSet):
    """静默/维护窗口：scope={"device_ids":[..]} 或 {"all":true}；ended_at 空则到期自动失效。"""
    queryset = AlertSilence.objects.order_by("-id")
    serializer_class = AlertSilenceSerializer
    permission_classes = [RbacPermission]
    required_perm = "alert.rule.edit"

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        """提前结束静默。"""
        from django.utils import timezone
        s = self.get_object()
        s.ended_at = timezone.now()
        s.save(update_fields=["ended_at", "updated_at"])
        return Response(AlertSilenceSerializer(s).data)


class AlertEventViewSet(viewsets.ModelViewSet):
    http_method_names = ["get", "patch"]
    queryset = AlertEvent.objects.order_by("-id")
    serializer_class = AlertEventSerializer
    permission_classes = [RbacPermission]
    required_perm = "alert.event.view"
    filterset_fields = ["status", "severity", "device_id"]

    @action(detail=True, methods=["post"])
    def ack(self, request, pk=None):
        ev = self.get_object()
        ev.status = "acknowledged"
        ev.acked_by_id = request.user.id
        ev.save(update_fields=["status", "acked_by_id", "acked_at"])
        return Response(AlertEventSerializer(ev).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        ev = self.get_object()
        ev.status = "resolved"
        ev.save(update_fields=["status"])
        return Response(AlertEventSerializer(ev).data)
