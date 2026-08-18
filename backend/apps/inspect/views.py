from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.inspect.models import InspectRun, InspectTask, InspectTemplate
from apps.inspect.tasks import run_inspect
from common.permissions import RbacPermission


class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = InspectTemplate
        fields = "__all__"


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = InspectTask
        fields = "__all__"


class RunSerializer(serializers.ModelSerializer):
    class Meta:
        model = InspectRun
        fields = "__all__"


class InspectTemplateViewSet(viewsets.ModelViewSet):
    queryset = InspectTemplate.objects.prefetch_related("items").all()
    serializer_class = TemplateSerializer
    permission_classes = [RbacPermission]
    required_perm = "inspect.template.view"


class InspectTaskViewSet(viewsets.ModelViewSet):
    queryset = InspectTask.objects.select_related("template").all()
    serializer_class = TaskSerializer
    permission_classes = [RbacPermission]
    required_perm = "inspect.template.view"

    @action(detail=True, methods=["post"])
    def run(self, request, pk=None):
        res = run_inspect.delay(task_id=self.get_object().id)
        return Response({"task_id": res.id})


class InspectRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = InspectRun.objects.order_by("-id")
    serializer_class = RunSerializer
    permission_classes = [RbacPermission]
    required_perm = "inspect.run.view"
