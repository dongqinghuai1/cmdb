from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.dcim.models import Cable, Rack, RackReservation, Region, Site
from apps.dcim.serializers import (CableSerializer, RackReservationSerializer,
                                   RackSerializer, RegionSerializer, SiteSerializer)
from apps.dcim.services import RackService
from apps.system.views import BaseModelViewSet


class RegionViewSet(BaseModelViewSet):
    queryset = Region.objects.all()
    serializer_class = RegionSerializer
    required_perm = "dcim.region.view"
    search_fields = ["name", "code"]

    def perform_destroy(self, instance):
        _purge_soft_devices(site_ids=[s.id for s in instance.sites.all()])
        super().perform_destroy(instance)


class SiteViewSet(BaseModelViewSet):
    queryset = Site.objects.select_related("region").all()
    serializer_class = SiteSerializer
    required_perm = "dcim.region.view"
    filterset_fields = ["region"]
    search_fields = ["name", "code", "address"]

    def perform_destroy(self, instance):
        _purge_soft_devices(site_ids=[instance.id])
        super().perform_destroy(instance)


def _purge_soft_devices(site_ids):
    """软删除设备在 UI 不可见但仍占 site/rack 外键，删除位置节点前物理清除。"""
    from apps.cmdb.models import Device
    if site_ids:
        Device.all_objects.filter(site_id__in=site_ids, deleted_at__isnull=False).delete()


class RackViewSet(BaseModelViewSet):
    queryset = Rack.objects.select_related("site", "site__region").all()
    serializer_class = RackSerializer
    required_perm = "dcim.rack.view"
    filterset_fields = ["site"]

    def perform_destroy(self, instance):
        from apps.cmdb.models import Device
        Device.all_objects.filter(rack_id=instance.id, deleted_at__isnull=False).delete()
        super().perform_destroy(instance)

    @action(detail=True, methods=["get"])
    def elevation(self, request, pk=None):
        """机柜可视化（PRD 5.4.3 核心亮点）。"""
        return Response(RackService.elevation(int(pk)))

    @action(detail=False, methods=["get"], url_path="capacity")
    def capacity(self, request):
        site = request.query_params.get("site")
        return Response(RackService.capacity(site_id=int(site) if site else None))


class RackReservationViewSet(BaseModelViewSet):
    queryset = RackReservation.objects.all()
    serializer_class = RackReservationSerializer
    required_perm = "dcim.rack.edit"
    filterset_fields = ["rack"]


class SiteObjectViewSet(BaseModelViewSet):
    """机房平面图元素 CRUD + 整图保存（DIY 布局编辑器）。"""
    from apps.dcim.models import SiteObject
    from apps.dcim.serializers import SiteObjectSerializer
    queryset = SiteObject.objects.select_related("site").all()
    serializer_class = SiteObjectSerializer
    required_perm = "dcim.rack.view"
    filterset_fields = ["site", "obj_type"]

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk(self, request):
        """整体保存布局：body {site, floor_len_m?, floor_w_m?, objects:[{obj_type,name,rack_id,x,y,w,h,meta}]}
        策略=全删重建（编辑器是整图保存语义）。"""
        from apps.dcim.models import Site, SiteObject
        site = Site.objects.filter(pk=request.data.get("site")).first()
        if not site:
            return Response({"detail": "site 不存在"}, status=400)
        fl = request.data.get("floor_len_m")
        fw = request.data.get("floor_w_m")
        if fl:
            site.floor_len_m = fl
        if fw:
            site.floor_w_m = fw
        if fl or fw:
            site.save(update_fields=["floor_len_m", "floor_w_m", "updated_at"])
        SiteObject.objects.filter(site=site).delete()
        objs = []
        for o in request.data.get("objects", []):
            objs.append(SiteObject(site=site, obj_type=o.get("obj_type", "other"),
                                   name=o.get("name", ""), rack_id=o.get("rack_id"),
                                   x=o.get("x", 0), y=o.get("y", 0),
                                   w=o.get("w", 0.6), h=o.get("h", 1.2),
                                   meta=o.get("meta", {})))
        SiteObject.objects.bulk_create(objs)
        return Response({"saved": len(objs)})


class CableViewSet(BaseModelViewSet):
    queryset = Cable.objects.filter(deleted_at__isnull=True)
    serializer_class = CableSerializer
    required_perm = "dcim.rack.view"
    filterset_fields = ["a_interface_id", "b_interface_id", "status", "source"]
