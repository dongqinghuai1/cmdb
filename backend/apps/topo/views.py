from rest_framework import serializers, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.topo.models import LldpNeighbor, Topology, TopologyEdge
from apps.topo.services import build_graph
from apps.system.views import BaseModelViewSet
from common.permissions import RbacPermission


class GraphView(APIView):
    """GET /api/v1/topo/graph/?region=&site= -- live topology for rendering."""
    permission_classes = [RbacPermission]

    def get(self, request):
        region = request.query_params.get("region")
        site = request.query_params.get("site")
        return Response(build_graph(region_id=region, site_id=site))


class LldpDiscoverView(APIView):
    """POST /api/v1/topo/lldp-discover/  body {mock: 0|1}（默认 1 防误触真网络；
    mock=0 对绑定 snmp_v2c 凭据的设备做真实 LLDP-MIB 走查）。execute 权限 + audit。"""
    permission_classes = [RbacPermission]
    required_perm = "cmdb.device.execute"

    def post(self, request):
        from apps.topo.services import discover_lldp
        from common.audit import write_audit
        mock = str(request.data.get("mock", 1)) not in ("0", "false", "False")
        r = discover_lldp(mock=mock)
        write_audit(request.user, "execute", "Topo", "lldp-discover",
                    after={**r, "action": "lldp-discover", "mock": mock},
                    source_ip=request.META.get("REMOTE_ADDR", ""))
        return Response(r)


class LldpNeighborSerializer(serializers.ModelSerializer):
    class Meta:
        model = LldpNeighbor
        fields = "__all__"


class LldpNeighborViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = LldpNeighbor.objects.order_by("-last_seen_at")
    serializer_class = LldpNeighborSerializer
    permission_classes = [RbacPermission]
    required_perm = "cmdb.device.view"
    filterset_fields = ["source", "remote_device_id"]


class TopologySerializer(serializers.ModelSerializer):
    class Meta:
        model = Topology
        fields = "__all__"


class TopologyEdgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TopologyEdge
        fields = "__all__"


class TopologyViewSet(BaseModelViewSet):
    queryset = Topology.objects.all()
    serializer_class = TopologySerializer
    required_perm = "cmdb.device.view"


class TopologyEdgeViewSet(BaseModelViewSet):
    queryset = TopologyEdge.objects.all()
    serializer_class = TopologyEdgeSerializer
    required_perm = "cmdb.device.view"
    filterset_fields = ["topology"]
