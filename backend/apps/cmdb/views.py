from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.cmdb.models import CiModel, CiModelAttr, Device, DeviceGroup
from apps.cmdb.serializers import (CiModelAttrSerializer, CiModelSerializer,
                                   DeviceGroupSerializer, DeviceSerializer,
                                   DeviceInterfaceSerializer, BusinessSerializer)
from apps.cmdb.services import DeviceService
from apps.system.views import BaseModelViewSet


class CiModelViewSet(BaseModelViewSet):
    queryset = CiModel.objects.prefetch_related("attrs_def").all()
    serializer_class = CiModelSerializer
    required_perm = "cmdb.model.view"
    filterset_fields = ["category"]
    search_fields = ["name", "code"]

    @action(detail=True, methods=["get", "post"])
    def attrs(self, request, pk=None):
        if request.method == "POST":
            data = {**request.data, "model": int(pk)}
            ser = CiModelAttrSerializer(data=data)
            ser.is_valid(raise_exception=True)
            ser.save()
            return Response(ser.data, status=201)
        return Response(CiModelAttrSerializer(self.get_object().attrs_def.all(), many=True).data)


class DeviceViewSet(BaseModelViewSet):
    queryset = Device.objects.none()  # 供 router 推断 basename

    def get_queryset(self):
        qs = Device.objects.select_related(
            "model", "site", "region", "rack", "owner").filter(deleted_at__isnull=True)
        if self.request.query_params.get("all") == "1" and self.request.user.is_superuser:
            qs = Device.all_objects.select_related(
                "model", "site", "region", "rack", "owner")
        return qs
    serializer_class = DeviceSerializer
    required_perm = "cmdb.device.view"
    filterset_fields = {"region": ["exact"], "site": ["exact"], "model": ["exact"],
                        "usage_tag": ["exact"], "online_status": ["exact"],
                        "lifecycle_status": ["exact"], "vendor": ["exact"],
                        "driver_type": ["exact"], "rack": ["exact", "isnull"]}
    search_fields = ["name", "sn", "hostname", "asset_no", "manage_ip"]

    def create(self, request, *args, **kwargs):
        from django.db import IntegrityError
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        dev = None
        try:
            dev = ser.save()
            if dev.rack:
                DeviceService.place(dev, dev.rack, dev.rack_start_u)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except IntegrityError:
            if dev is not None and dev.pk:
                dev.delete()
            return Response({"detail": "U-slot conflict (db constraint)"},
                            status=status.HTTP_409_CONFLICT)
        return Response(DeviceSerializer(dev).data, status=201)

    def perform_destroy(self, instance):
        """支持 ?hard=1 超管硬删除（软删除行仍占 site/rack 外键与唯一索引）。"""
        if self.request.query_params.get("hard") == "1" and self.request.user.is_superuser:
            pk = instance.pk
            type(instance).all_objects.filter(pk=pk).delete()
            from common.audit import write_audit
            write_audit(self.request.user, "delete", "Device", pk,
                        source_ip=self.request.META.get("REMOTE_ADDR", ""))
            return
        super().perform_destroy(instance)

    def update(self, request, *args, **kwargs):
        """编辑含位置变更：换柜/换 U/下架（rack=null）。U 位冲突由 DB EXCLUDE 兜底转 409。"""
        from django.db import IntegrityError
        partial = kwargs.pop("partial", True)
        instance = self.get_object()
        ser = self.get_serializer(instance, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        try:
            dev = ser.save()
        except IntegrityError:
            return Response({"detail": "U-slot conflict (db constraint)"},
                            status=status.HTTP_409_CONFLICT)
        from apps.dcim.services import RackService
        if dev.rack_id:
            try:  # 越界校验（跨 start_u+units > u_total 不会触发 DB 约束）
                RackService.check_placement(dev.rack_id, dev.rack_start_u, dev.rack_units,
                                            exclude_device_id=dev.id)
            except ValueError as e:
                return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(DeviceSerializer(dev).data)

    @action(detail=True, methods=["post"], url_path="place")
    def place_device(self, request, pk=None):
        """drag-place / move device in rack (PRD 5.4.3). body: {rack, rack_start_u}"""
        dev = self.get_object()
        from apps.dcim.models import Rack
        try:
            DeviceService.place(dev, Rack.objects.get(pk=request.data["rack"]),
                                int(request.data["rack_start_u"]))
        except ValueError as e:
            return Response({"detail": str(e)}, status=409)
        return Response(DeviceSerializer(dev).data)

    @action(detail=True, methods=["get"], url_path="360")
    def view360(self, request, pk=None):
        """device 360 view (PRD 5.5.3)."""
        d = self.get_object()
        data = DeviceSerializer(d).data
        ifaces = []
        for i in d.interfaces.select_related("stat").all()[:200]:
            item = DeviceInterfaceSerializer(i).data
            st = getattr(i, "stat", None)
            item["stat"] = {"in_bps": st.in_bps, "out_bps": st.out_bps,
                            "in_errors_rate": str(st.in_errors_rate),
                            "out_errors_rate": str(st.out_errors_rate),
                            "optical_tx_dbm": str(st.optical_tx_dbm) if st.optical_tx_dbm else None,
                            "optical_rx_dbm": str(st.optical_rx_dbm) if st.optical_rx_dbm else None,
                            "updated_at": st.updated_at} if st else None
            ifaces.append(item)
        data["interfaces"] = ifaces
        data["asset_events"] = list(d.asset_events.values("event_type", "occurred_at", "detail")[:50])
        data["business"] = list(d.business_links.values("business_id", "role"))
        return Response(data)

    @action(detail=False, methods=["post"], url_path="import-excel")
    def import_excel(self, request):
        if "file" not in request.FILES:
            return Response({"detail": "file field missing"}, status=400)
        return Response(DeviceService.import_excel(request.FILES["file"], request.user))

    @action(detail=False, methods=["get"], url_path="export-excel")
    def export_excel(self, request):
        buf = DeviceService.export_excel(self.filter_queryset(self.get_queryset()))
        resp = HttpResponse(
            buf.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="devices_{timezone.now():%Y%m%d}.xlsx"'
        return resp


class DeviceGroupViewSet(BaseModelViewSet):
    queryset = DeviceGroup.objects.all()
    serializer_class = DeviceGroupSerializer
    required_perm = "cmdb.device.view"

    @action(detail=True, methods=["get"])
    def members(self, request, pk=None):
        ids = self.get_object().member_ids()
        return Response({"ids": ids, "count": len(ids),
                         "devices": DeviceSerializer(
                             Device.objects.filter(id__in=ids)[:500], many=True).data})


class BusinessViewSet(BaseModelViewSet):
    from apps.cmdb.models import Business
    queryset = Business.objects.all()
    serializer_class = BusinessSerializer
    required_perm = "cmdb.device.view"
