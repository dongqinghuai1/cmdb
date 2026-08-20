from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.ipam.models import IpAddress, Subnet, Vlan
from apps.ipam.services import import_arp, subnet_usage
from apps.system.views import BaseModelViewSet
from common.permissions import RbacPermission


class VlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vlan
        fields = "__all__"

    def validate_vid(self, v):
        if not (1 <= v <= 4094):
            raise serializers.ValidationError("VLAN ID 须在 1-4094")
        return v


class SubnetSerializer(serializers.ModelSerializer):
    usage = serializers.SerializerMethodField()
    vlan_name = serializers.SerializerMethodField()

    class Meta:
        model = Subnet
        fields = "__all__"

    def get_usage(self, obj):
        return subnet_usage(obj)

    def get_vlan_name(self, obj):
        return None  # 由前端按 vlan_id 映射（避免跨表 N+1）

    def validate_cidr(self, v):
        import ipaddress
        try:
            ipaddress.ip_network(v, strict=False)
        except ValueError as e:
            raise serializers.ValidationError(str(e))
        return v


class IpSerializer(serializers.ModelSerializer):
    class Meta:
        model = IpAddress
        fields = "__all__"

    def validate(self, attrs):
        sn = attrs.get("subnet") or getattr(self.instance, "subnet", None)
        addr = attrs.get("address") or getattr(self.instance, "address", None)
        if sn and addr:
            import ipaddress
            if ipaddress.ip_address(addr) not in sn.network:
                raise serializers.ValidationError(f"{addr} 不在网段 {sn.cidr} 内")
        return attrs


class VlanViewSet(BaseModelViewSet):
    queryset = Vlan.objects.all()
    serializer_class = VlanSerializer
    required_perm = "cmdb.device.view"
    filterset_fields = ["site_id"]


class SubnetViewSet(BaseModelViewSet):
    queryset = Subnet.objects.all()
    serializer_class = SubnetSerializer
    required_perm = "cmdb.device.view"
    filterset_fields = ["vlan_id", "site_id"]
    search_fields = ["cidr", "purpose"]

    @action(detail=True, methods=["get"])
    def usage(self, request, pk=None):
        return Response(subnet_usage(self.get_object()))


class IpViewSet(BaseModelViewSet):
    queryset = IpAddress.objects.select_related("subnet").all()
    serializer_class = IpSerializer
    required_perm = "cmdb.device.view"
    filterset_fields = ["subnet", "status", "device_id", "source"]

    @action(detail=False, methods=["post"], url_path="import-arp")
    def import_arp(self, request):
        text = request.data.get("text", "")
        if not text.strip():
            return Response({"detail": "text required（每行: IP MAC）"}, status=400)
        return Response(import_arp(text))
