from urllib.parse import quote

from django.db import connection
from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.cmdb import storage
from apps.cmdb.models import (CiModel, CiModelAttr, Device, DeviceAttachment,
                              DeviceGroup, License)
from apps.cmdb.serializers import (CiModelAttrSerializer, CiModelSerializer,
                                   DeviceGroupSerializer, DeviceSerializer,
                                   DeviceInterfaceSerializer, BusinessSerializer)
from apps.cmdb.services import DeviceService
from apps.system.views import BaseModelViewSet
from common.permissions import has_perm


def _need(user, code: str):
    """写操作门禁：admin 或具备对应操作码（粗粒度 required_perm 只管读）。"""
    if not (user.is_superuser or has_perm(user, code)):
        raise PermissionDenied("no permission")


def _need_edit(user):
    _need(user, "cmdb.device.edit")


def _need_execute(user):
    _need(user, "cmdb.device.execute")


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
        if self.request.query_params.get("deleted") == "1":
            qs = Device.all_objects.select_related(
                "model", "site", "region", "rack", "owner").filter(deleted_at__isnull=False)
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
        from common.audit import write_audit
        write_audit(request.user, "create", "Device", dev.pk,
                    after={"name": dev.name, "sn": dev.sn,
                           "manage_ip": str(dev.manage_ip or "")},
                    source_ip=request.META.get("REMOTE_ADDR", ""))
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
        before = {f.name: getattr(instance, f.name, None) for f in instance._meta.fields
                  if f.name not in ("created_at", "updated_at", "deleted_at")}
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
        from common.audit import write_audit
        write_audit(request.user, "update", "Device", dev.pk,
                    before=before, after=dict(ser.validated_data),
                    source_ip=request.META.get("REMOTE_ADDR", ""))
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

    @action(detail=False, methods=["post"], url_path="ap-sync")
    def ap_sync(self, request):
        """粘贴 WLC `show ap summary` 输出同步 AP 台账。body: {wlc, text}"""
        from apps.cmdb.ap_sync import sync_aps
        try:
            r = sync_aps(int(request.data["wlc"]), request.data.get("text", ""))
        except (KeyError, ValueError) as e:
            return Response({"detail": str(e) or "wlc/text required"}, status=400)
        return Response(r)

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

    # ---------- 回收站（5.5.2 P1：误删可恢复） ----------
    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        _need_execute(request.user)
        dev = Device.all_objects.filter(pk=pk).first()
        if not dev:
            return Response({"detail": "device not found"}, status=404)
        if dev.deleted_at is None:
            return Response({"detail": "device is not deleted"}, status=400)
        dev.deleted_at = None
        dev.save(update_fields=["deleted_at", "updated_at"])
        from common.audit import write_audit
        write_audit(request.user, "restore", "Device", dev.pk, after={"name": dev.name},
                    source_ip=request.META.get("REMOTE_ADDR", ""))
        return Response(DeviceSerializer(dev).data)

    @action(detail=True, methods=["post"], url_path="purge")
    def purge(self, request, pk=None):
        _need_execute(request.user)
        if not (request.user.is_superuser or request.query_params.get("confirm") == "1"):
            return Response({"detail": "confirm=1 required"}, status=400)
        dev = Device.all_objects.filter(pk=pk).first()
        if not dev:
            return Response({"detail": "device not found"}, status=404)
        name = dev.name
        Device.all_objects.filter(pk=pk).delete()  # 全量 SQL 删除（含附件/授权等级联）
        from common.audit import write_audit
        write_audit(request.user, "purge", "Device", pk, after={"name": name},
                    source_ip=request.META.get("REMOTE_ADDR", ""))
        return Response({"detail": "purged", "name": name})

    # ---------- 数据质量看板（5.5.6 P1：关键字段缺失清单） ----------
    @action(detail=False, methods=["get"], url_path="data-quality")
    def data_quality(self, request):
        qs = Device.objects.filter(deleted_at__isnull=True)
        count = lambda q: q.count()
        empty = {"", None}
        checks = {
            "no_sn": qs.filter(sn__isnull=True) | qs.filter(sn=""),
            "no_owner": qs.filter(owner__isnull=True),
            "no_warranty": qs.filter(warranty_until__isnull=True),
            "no_vendor": qs.filter(vendor=""),
            "no_sw_version": qs.filter(sw_version=""),
            "no_rack": qs.filter(is_virtual=False, rack__isnull=True),
            "no_manage_ip": qs.filter(is_virtual=False, manage_ip__isnull=True),
        }
        summary = {k: v.count() for k, v in checks.items()}
        kind = request.query_params.get("kind")
        rows = []
        if kind in checks:
            q = checks[kind].select_related("model", "site", "region", "rack", "owner")
            rows = list(q.order_by("-updated_at")[:100].values(
                "id", "name", "sn", "manage_ip", "vendor", "hw_model",
                "sw_version", "warranty_until", "owner__username",
                "region__name", "site__name", "rack__name", "is_virtual"))
        return Response({"summary": summary, "rows": rows, "total": sum(summary.values())})

    # ---------- 变更历史（360° Tab；读 system_auditlog 跨应用） ----------
    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        self.get_object()  # 确保存在 & 权限
        with connection.cursor() as cur:
            cur.execute(
                "SELECT id, action, created_at, source_ip, user_id, "
                "COALESCE((SELECT username FROM auth_user WHERE id=a.user_id),'') AS username "
                "FROM system_auditlog a "
                "WHERE resource_type='Device' AND resource_id=%s "
                "ORDER BY id DESC LIMIT 100", [pk])
            cols = [c[0] for c in cur.description]
            return Response([dict(zip(cols, r)) for r in cur.fetchall()])

    # ---------- 软件版本一致性（5.5.4 P1 首步：型号维度版本分布） ----------
    @action(detail=False, methods=["get"], url_path="software-summary")
    def software_summary(self, request):
        qs = Device.objects.filter(deleted_at__isnull=True).exclude(sw_version="")
        data = qs.values("vendor", "hw_model", "model__code", "sw_version").annotate(
            c=Count("id"))
        return Response(list(data.order_by("vendor", "hw_model", "-c")))


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

    @action(detail=True, methods=["post"], url_path="evaluate")
    def evaluate(self, request, pk=None):
        """动态分组规则重算。body: {filter?: {...}, apply?: bool}
        支持规则字段：model(模型code)、region_id、vendor（与 member_ids 同语义）。"""
        _need_edit(request.user)
        g = self.get_object()
        if g.group_type != "dynamic":
            return Response({"detail": "only dynamic group can evaluate"}, status=400)
        f = request.data.get("filter") or g.filter or {}
        if not isinstance(f, dict):
            return Response({"detail": "filter must be object"}, status=400)
        qs = Device.objects.filter(deleted_at__isnull=True)
        if f.get("model"):
            qs = qs.filter(model__code=f["model"])
        if f.get("region_id"):
            qs = qs.filter(region_id=f["region_id"])
        if f.get("vendor"):
            qs = qs.filter(vendor=f["vendor"])
        ids = list(qs.values_list("id", flat=True))
        out = {"matched": len(ids), "ids": ids[:200]}
        if request.data.get("apply"):
            g.filter = f
            g.save(update_fields=["filter", "updated_at"])
            g.devices.set(ids)
            out["applied"] = len(ids)
        return Response(out)


class LicenseSerializer(serializers.ModelSerializer):
    device_id = serializers.PrimaryKeyRelatedField(source="device", queryset=Device.objects.all())

    class Meta:
        model = License
        fields = ["id", "device_id", "license_type", "seats", "expire_at",
                  "supplier", "contract_no", "remark", "created_at"]
        read_only_fields = ["created_at"]


class LicenseViewSet(BaseModelViewSet):
    queryset = License.objects.select_related("device").order_by("-id")
    serializer_class = LicenseSerializer
    required_perm = "cmdb.device.view"
    filterset_fields = {"device_id": ["exact"]}

    def create(self, request, *args, **kwargs):
        _need_edit(request.user)
        if not Device.objects.filter(pk=request.data.get("device_id"),
                                     deleted_at__isnull=True).exists():
            return Response({"detail": "device not found"}, status=400)
        return super().create(request, *args, **kwargs)

    def perform_update(self, serializer):
        _need_edit(self.request.user)
        return super().perform_update(serializer)

    def destroy(self, request, *args, **kwargs):
        _need_execute(request.user)
        return super().destroy(request, *args, **kwargs)


class DeviceAttachmentViewSet(BaseModelViewSet):
    """设备附件：上传(multipart file)/列表/下载/删除（PRD 5.5.3 附件 Tab）。"""
    queryset = DeviceAttachment.objects.none()
    required_perm = "cmdb.device.view"
    http_method_names = ["get", "post", "delete", "head", "options"]
    MAX_SIZE = 25 * 1024 * 1024

    def list(self, request, *args, **kwargs):
        qs = DeviceAttachment.objects.filter(
            device_id=request.query_params.get("device_id") or 0)
        from django.contrib.auth import get_user_model
        uids = {a.uploaded_by_id for a in qs if a.uploaded_by_id}
        names = dict(get_user_model().objects.filter(id__in=uids).values_list("id", "username"))
        rows = [{"id": a.id, "device_id": a.device_id, "file_name": a.file_name,
                 "file_type": a.file_type, "size": a.size,
                 "uploaded_by": names.get(a.uploaded_by_id),
                 "created_at": a.created_at}
                for a in qs.order_by("-id")[:200]]
        return Response(rows)

    def create(self, request, *args, **kwargs):
        _need_edit(request.user)
        f = request.FILES.get("file")
        if not f:
            return Response({"detail": "file field missing"}, status=400)
        if f.size > self.MAX_SIZE:
            return Response({"detail": "file too large (max 25MB)"}, status=400)
        device_id = request.data.get("device_id")
        if not Device.objects.filter(pk=device_id, deleted_at__isnull=True).exists():
            return Response({"detail": "device not found"}, status=400)
        ftype = request.data.get("file_type", "other")
        allowed = {c[0] for c in DeviceAttachment._meta.get_field("file_type").choices}
        if ftype not in allowed:
            ftype = "other"
        name = storage.save_blob(f.read(), f.name)
        a = DeviceAttachment.objects.create(
            device_id=device_id, file_name=f.name[:255], file_url=name,
            file_type=ftype, size=f.size, uploaded_by_id=request.user.id)
        return Response({"id": a.id, "device_id": a.device_id, "file_name": a.file_name,
                         "file_type": a.file_type, "size": a.size,
                         "uploaded_by": request.user.username,
                         "created_at": a.created_at}, status=201)

    def destroy(self, request, *args, **kwargs):
        _need_execute(request.user)
        a = DeviceAttachment.objects.filter(pk=kwargs["pk"]).first()
        if not a:
            return Response({"detail": "attachment not found"}, status=404)
        DeviceAttachment.objects.filter(pk=a.pk).delete()
        storage.remove_blob(a.file_url)
        return Response(status=204)

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        a = DeviceAttachment.objects.filter(pk=pk).first()
        if not a:
            return Response({"detail": "attachment not found"}, status=404)
        resp = HttpResponse(storage.read_blob(a.file_url),
                            content_type=storage.content_type_for(a.file_name))
        resp["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(a.file_name)}"
        return resp


class BusinessViewSet(BaseModelViewSet):
    from apps.cmdb.models import Business
    queryset = Business.objects.all()
    serializer_class = BusinessSerializer
    required_perm = "cmdb.device.view"
