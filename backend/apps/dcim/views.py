from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.dcim.models import (Cable, DcimTicket, Rack, RackReservation,
                              Region, Site, SiteObject)
from apps.dcim.serializers import (CableSerializer, DcimTicketSerializer,
                                   RackReservationSerializer, RackSerializer,
                                   RegionSerializer, SiteSerializer)
from apps.dcim.services import RackService
from apps.system.views import BaseModelViewSet
from common.permissions import has_perm
from rest_framework.exceptions import PermissionDenied


def _need_perm(user, code):
    """dcim 视图读写门禁：admin 或持码（required_perm 只控读，写需显式）。"""
    if not (user.is_superuser or has_perm(user, code)):
        raise PermissionDenied("no permission")


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


class DcimTicketViewSet(BaseModelViewSet):
    """机房作业工单：上下架/迁移/维修/布线；读=dcim.rack.view，写=dcim.rack.edit。"""

    queryset = DcimTicket.objects.select_related("rack")
    serializer_class = DcimTicketSerializer
    required_perm = "dcim.rack.view"
    filterset_fields = {"status": ["exact"], "kind": ["exact"],
                        "device_id": ["exact"], "rack": ["exact"]}

    def perform_create(self, serializer):
        _need_perm(self.request.user, "dcim.rack.edit")
        super().perform_create(serializer)
        DcimTicket.objects.filter(pk=serializer.instance.pk)\
            .update(operator_id=self.request.user.id)

    def perform_update(self, serializer):
        _need_perm(self.request.user, "dcim.rack.edit")
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        _need_perm(self.request.user, "dcim.rack.edit")
        super().perform_destroy(instance)

    def _edit(self):
        _need_perm(self.request.user, "dcim.rack.edit")

    @action(detail=True, methods=["post"], url_path="start")
    def start(self, request, pk=None):
        self._edit()
        t = self.get_object()
        if t.status != DcimTicket.Status.PLANNED:
            return Response({"detail": "仅待处理可开工"}, status=400)
        t.status = DcimTicket.Status.DOING
        t.save(update_fields=["status", "updated_at"])
        return Response({"id": t.pk, "status": t.status})

    @action(detail=True, methods=["post"], url_path="finish")
    def finish(self, request, pk=None):
        self._edit()
        t = self.get_object()
        if t.status in (DcimTicket.Status.DONE, DcimTicket.Status.CANCELLED):
            return Response({"detail": "已结束工单不可再完成"}, status=400)
        # ---- U 位落位联动（冲突校验通过才完成；冲突则工单保持原状态）----
        from apps.cmdb.models import Device
        from common.audit import write_audit
        placement = None
        dev = None
        if t.device_id:
            try:
                dev = Device.objects.get(pk=t.device_id, deleted_at__isnull=True)
            except Device.DoesNotExist:
                return Response({"detail": "关联设备不存在（可能已删除）"}, status=400)
        if t.kind in (DcimTicket.Kind.RACK_IN, DcimTicket.Kind.MOVE) and t.rack_id and dev:
            if t.u_from:
                start, units = t.u_from, max(1, (t.u_to or t.u_from) - t.u_from + 1)
            elif dev.rack_id == t.rack_id and dev.rack_start_u:
                start, units = dev.rack_start_u, dev.rack_units or 1  # 同柜仅迁移登记
            else:
                return Response({"detail": "目标机柜需提供目标 U 位起点（u_from）"}, status=400)
            try:
                RackService.check_placement(t.rack_id, start, units, exclude_device_id=dev.pk)
            except ValueError as e:
                return Response({"detail": str(e)}, status=400)
            before = {"rack_id": dev.rack_id, "rack_start_u": dev.rack_start_u}
            dev.rack_id, dev.rack_start_u, dev.rack_units = t.rack_id, start, units
            dev.save(update_fields=["rack_id", "rack_start_u", "rack_units", "updated_at"])
            write_audit(request.user, "update", "Device", dev.pk, before=before,
                        after={"rack_id": t.rack_id, "rack_start_u": start, "units": units},
                        source_ip=self._ip())
            placement = {"device_id": dev.pk, "rack_id": t.rack_id,
                         "rack_start_u": start, "units": units}
        elif t.kind == DcimTicket.Kind.RACK_OUT and dev:
            before = {"rack_id": dev.rack_id, "rack_start_u": dev.rack_start_u}
            dev.rack_id, dev.rack_start_u = None, None
            dev.save(update_fields=["rack_id", "rack_start_u", "updated_at"])
            write_audit(request.user, "update", "Device", dev.pk, before=before,
                        after={"rack_id": None, "rack_start_u": None},
                        source_ip=self._ip())
            placement = {"device_id": dev.pk, "rack_id": None, "rack_start_u": None}
        from django.utils import timezone
        t.status = DcimTicket.Status.DONE
        t.finished_at = timezone.now()
        t.result = (request.data.get("result") or "").strip()
        t.save(update_fields=["status", "finished_at", "result", "updated_at"])
        return Response({"id": t.pk, "status": t.status, "finished_at": t.finished_at,
                         "placement": placement})

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        self._edit()
        t = self.get_object()
        if t.status in (DcimTicket.Status.DONE, DcimTicket.Status.CANCELLED):
            return Response({"detail": "已结束工单不可取消"}, status=400)
        t.status = DcimTicket.Status.CANCELLED
        t.result = (request.data.get("reason") or "").strip() or t.result
        t.save(update_fields=["status", "result", "updated_at"])
        return Response({"id": t.pk, "status": t.status})
