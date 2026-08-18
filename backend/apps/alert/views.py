from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.permissions import RbacPermission
from apps.alert.models import AlertEvent, AlertRule


class AlertRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertRule
        fields = "__all__"


class AlertEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertEvent
        fields = "__all__"


class AlertRuleViewSet(viewsets.ModelViewSet):
    queryset = AlertRule.objects.all()
    serializer_class = AlertRuleSerializer
    permission_classes = [RbacPermission]
    required_perm = "alert.rule.view"
    filterset_fields = ["rule_type", "enabled", "severity"]


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
