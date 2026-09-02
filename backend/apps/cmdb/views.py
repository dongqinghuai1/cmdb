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
from apps.cmdb.models import (Business, CiModel, CiModelAttr, Device, DeviceAssetEvent,
                              DeviceAttachment, DeviceBusiness, DeviceGroup, License,
                              LinkQualitySample, TechSnapshot)
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
        # 扩展过滤（系统域清单/业务归属用）
        qp = self.request.query_params
        if qp.get("business_id"):
            qs = qs.filter(id__in=DeviceBusiness.objects.filter(
                business_id=int(qp["business_id"])).values_list("device_id", flat=True))
        if qp.get("is_virtual") in ("1", "0"):
            qs = qs.filter(is_virtual=bool(int(qp["is_virtual"])))
        if qp.get("model_category"):
            qs = qs.filter(model__category=qp["model_category"])
        return qs
    serializer_class = DeviceSerializer
    required_perm = "cmdb.device.view"
    filterset_fields = {"region": ["exact"], "site": ["exact"], "model": ["exact"],
                        "usage_tag": ["exact"], "online_status": ["exact"],
                        "lifecycle_status": ["exact"], "vendor": ["exact"],
                        "hw_model": ["exact"], "driver_type": ["exact"],
                        "rack": ["exact", "isnull"]}
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
        # 跨域裸外键残留先清：LLDP 邻居行（topo 域）以接口 id 关联，不随设备级联删除
        from apps.cmdb.models import DeviceInterface
        iface_ids = list(DeviceInterface.objects.filter(device_id=pk).values_list("id", flat=True))
        if iface_ids:
            from apps.topo.models import LldpNeighbor
            LldpNeighbor.objects.filter(local_interface_id__in=iface_ids).delete()
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

    # ---------- 360° 技术概览（R2：已采集数据可视化 + 扩展入口） ----------
    @action(detail=True, methods=["get"], url_path="tech")
    def tech(self, request, pk=None):
        d = self.get_object()
        from apps.cmdb.models import RouteTableSnapshot, RoutingNeighbor
        neighbors = list(RoutingNeighbor.objects.filter(device_id=d.pk).values(
            "protocol", "vrf", "neighbor_addr", "state", "last_seen_at")[:200])
        rt = RouteTableSnapshot.objects.filter(device_id=d.pk).order_by("-snapshot_at").first()
        routes = (rt.routes[:500] if rt and rt.routes else [])
        route_meta = ({"snapshot_at": rt.snapshot_at, "count": len(routes)} if rt else None)
        ap = None
        ai = getattr(d, "ap_info", None)
        if ai:
            ap = {"ap_name": ai.ap_name, "ap_ip": str(ai.ap_ip or ""), "ap_model": ai.ap_model,
                  "channel_2g": ai.channel_2g, "channel_5g": ai.channel_5g,
                  "tx_power": ai.tx_power, "client_count": ai.client_count,
                  "uplink_switch_id": ai.uplink_switch_id, "status": ai.status}
        vlan_set = set()
        for i in d.interfaces.all()[:500]:
            if i.native_vlan:
                vlan_set.add(i.native_vlan)
            for v in (i.vlan_ids or []):
                if isinstance(v, int):
                    vlan_set.add(v)
        sessions = []
        with connection.cursor() as cur:
            cur.execute(
                "SELECT username, source_ip, login_at, logout_at, session_type, result "
                "FROM usage_loginevent WHERE device_id=%s "
                "ORDER BY login_at DESC LIMIT 20", [d.pk])
            cols = [c[0] for c in cur.description]
            sessions = [dict(zip(cols, r)) for r in cur.fetchall()]
        extensions = {}
        for kind, note in (("acl", "ACL 策略采集驱动未接入"),
                           ("nat", "NAT/VIP 采集驱动未接入"),
                           ("ipsec", "IPSec/IKE 隧道采集驱动未接入")):
            ts = TechSnapshot.objects.filter(device_id=d.pk, kind=kind).first()
            if ts:
                extensions[kind] = {"supported": True, "updated_at": ts.created_at,
                                    "payload": ts.payload}
            else:
                extensions[kind] = {"supported": False,
                                    "note": f"{note}（设备 360 支持粘贴输出解析：POST tech-parse 落库即在此展示）"}
        return Response({
            "neighbors": neighbors, "routes": routes, "route_meta": route_meta,
            "ap": ap, "vlans": sorted(vlan_set), "sessions": sessions,
            "extensions": extensions,
        })

    @action(detail=True, methods=["post"], url_path="tech-snapshot")
    def tech_snapshot(self, request, pk=None):
        """扩展技术概览快照写入（ACL/IPSec 等）：body {kind: acl|ipsec, payload:{...}}。

        供采集驱动(fortigate/asa)解析设备输出后调用；每次写一条新记录，读取取最新。
        """
        _need_execute(request.user)
        d = self.get_object()
        kind = request.data.get("kind")
        if kind not in TechSnapshot.Kind.values:
            return Response({"detail": f"kind must be in {list(TechSnapshot.Kind.values)}"}, status=400)
        payload = request.data.get("payload")
        if not isinstance(payload, dict):
            return Response({"detail": "payload must be object"}, status=400)
        import json as _json
        if len(_json.dumps(payload, ensure_ascii=False)) > 200_000:
            return Response({"detail": "payload too large (max ~200KB)"}, status=400)
        ts = TechSnapshot.objects.create(device_id=d.pk, kind=kind, payload=payload)
        return Response({"id": ts.id, "kind": kind, "created_at": ts.created_at}, status=201)

    @action(detail=True, methods=["post"], url_path="tech-parse")
    def tech_parse(self, request, pk=None):
        """采集驱动解析入口（粘贴式）：把设备 CLI 输出文本解析为结构化数据并可选落库。

        body {kind: acl|nat|ipsec, text, save?: true}；
        预览仅需视图权限；save=true 需 execute 权限并写 audit（执行留痕）。
        """
        dev = self.get_object()
        kind = request.data.get("kind")
        text = (request.data.get("text") or "").strip()
        if kind not in ("acl", "nat", "ipsec"):
            return Response({"detail": "kind must be acl/nat/ipsec"}, status=400)
        if not text:
            return Response({"detail": "text required"}, status=400)
        from apps.cmdb.collectors import KIND_HINTS, PARSERS
        try:
            parsed = PARSERS[kind](text)
        except ValueError as e:
            return Response({"detail": str(e), "hint": KIND_HINTS[kind]}, status=400)
        out = {"ok": True, "kind": kind, "count": parsed["count"],
               "rows": parsed["rows"], "summary": parsed["summary"], "saved": False}
        if request.data.get("save"):
            _need_execute(request.user)
            ts = TechSnapshot.objects.create(device_id=dev.pk, kind=kind, payload=parsed)
            from common.audit import write_audit
            write_audit(request.user, "execute", "Device", dev.pk,
                        before={"action": f"tech-parse:{kind}"},
                        after={"snapshot_id": ts.id, "count": parsed["count"]},
                        source_ip=request.META.get("REMOTE_ADDR", ""))
            out.update(saved=True, snapshot_id=ts.id, created_at=ts.created_at)
        return Response(out)

    @action(detail=False, methods=["post"], url_path="tech-retention")
    def tech_retention(self, request):
        """按需执行快照保留：body {keep?: n}；execute 权限 + 超管或 confirm=1。
        周期执行走 celery beat（cmdb.cleanup_techsnapshots，每日 04:30）。"""
        _need_execute(request.user)
        if not (request.user.is_superuser or request.query_params.get("confirm") == "1"):
            return Response({"detail": "confirm=1 required"}, status=400)
        from apps.cmdb.retention import cleanup_techsnapshots
        try:
            r = cleanup_techsnapshots(request.data.get("keep") or 5)
        except (TypeError, ValueError):
            return Response({"detail": "keep must be int >= 1"}, status=400)
        from common.audit import write_audit
        write_audit(request.user, "execute", "TechSnapshot", None,
                    after={**r, "action": "tech-retention"},
                    source_ip=request.META.get("REMOTE_ADDR", ""))
        return Response(r)

    # ---------- 软件版本一致性（5.5.4 P1 首步：型号维度版本分布） ----------
    @action(detail=False, methods=["get"], url_path="software-summary")
    def software_summary(self, request):
        qs = Device.objects.filter(deleted_at__isnull=True).exclude(sw_version="")
        data = qs.values("vendor", "hw_model", "model__code", "sw_version").annotate(
            c=Count("id"))
        return Response(list(data.order_by("vendor", "hw_model", "-c")))

    # ---------- 资产生命周期（5.5.7 P1：状态机流转 + 资产事件流水） ----------
    _EVENT_BY_LIFECYCLE = {"purchasing": "purchase", "in_stock": "in_stock",
                           "deployed": "deploy", "repairing": "repair",
                           "spare": "spare", "retired": "retire"}

    @action(detail=True, methods=["post"], url_path="lifecycle")
    def set_lifecycle(self, request, pk=None):
        _need_edit(request.user)
        dev = self.get_object()
        ns = request.data.get("lifecycle_status")
        if ns not in Device.Lifecycle.values:
            return Response({"detail": "lifecycle_status 非法"}, status=400)
        if ns == dev.lifecycle_status:
            return Response({"detail": "状态未变化"}, status=400)
        old = dev.lifecycle_status
        dev.lifecycle_status = ns
        dev.save(update_fields=["lifecycle_status", "updated_at"])
        et = (request.data.get("event_type") or self._EVENT_BY_LIFECYCLE.get(ns))
        if et and et in DeviceAssetEvent.EventType.values:
            DeviceAssetEvent.objects.create(
                device_id=dev.pk, event_type=et, occurred_at=timezone.now(),
                operator_id=request.user.id,
                counterparty=request.data.get("counterparty") or "",
                detail={"from": old, "to": ns})
        from common.audit import write_audit
        write_audit(request.user, "update", "Device", dev.pk,
                    before={"lifecycle_status": old}, after={"lifecycle_status": ns},
                    source_ip=request.META.get("REMOTE_ADDR", ""))
        return Response({"id": dev.pk, "lifecycle_status": dev.lifecycle_status,
                         "lifecycle_label": dev.get_lifecycle_status_display()})

    @action(detail=True, methods=["get", "post"], url_path="asset-events")
    def asset_events(self, request, pk=None):
        dev = self.get_object()
        if request.method == "POST":
            _need_edit(request.user)
            et = request.data.get("event_type")
            if et not in DeviceAssetEvent.EventType.values:
                return Response({"detail": "event_type 非法"}, status=400)
            occurred = request.data.get("occurred_at")
            ev = DeviceAssetEvent.objects.create(
                device_id=dev.pk, event_type=et,
                occurred_at=occurred or timezone.now(),
                operator_id=request.user.id,
                counterparty=request.data.get("counterparty") or "",
                detail=request.data.get("detail") or {})
            return Response({"id": ev.id, "event_type": et,
                             "occurred_at": ev.occurred_at}, status=201)
        rows = list(dev.asset_events.values(
            "id", "event_type", "occurred_at", "counterparty", "operator_id", "detail")[:200])
        from django.contrib.auth import get_user_model
        uids = {r["operator_id"] for r in rows if r["operator_id"]}
        names = dict(get_user_model().objects.filter(id__in=uids).values_list("id", "username"))
        for r in rows:
            r["operator"] = names.get(r["operator_id"])
        return Response(rows)

    # ---------- 借还台账（5.17 使用与共享：borrow/return ↔ usage_status 联动） ----------
    LOAN_OVERDUE_DAYS = 30

    @action(detail=False, methods=["get"], url_path="loan-summary")
    def loan_summary(self, request):
        """全局在借设备台账 + 最近借还动态；设备仅统计未删除。"""
        from django.contrib.auth import get_user_model
        events = list(DeviceAssetEvent.objects.filter(event_type__in=("borrow", "return"))
                      .order_by("-occurred_at", "-id").values(
                          "id", "device_id", "event_type", "occurred_at",
                          "counterparty", "operator_id", "detail")[:800])
        alive = set(Device.objects.filter(deleted_at__isnull=True).values_list("id", flat=True))
        devmap = {d.id: {"name": d.name, "manage_ip": str(d.manage_ip or ""),
                         "region": d.region.name if d.region else "",
                         "site": d.site.name if d.site else ""}
                  for d in Device.objects.filter(id__in=alive).select_related("region", "site")}
        uids = {e["operator_id"] for e in events if e.get("operator_id")}
        names = dict(get_user_model().objects.filter(id__in=uids).values_list("id", "username"))
        borrowed, activity, seen = [], [], set()
        for e in events:
            did = e["device_id"]
            info = devmap.get(did)
            if info and len(activity) < 40:
                activity.append({**info, "device_id": did, "event_type": e["event_type"],
                                 "occurred_at": e["occurred_at"], "counterparty": e["counterparty"],
                                 "operator": names.get(e["operator_id"]),
                                 "note": (e.get("detail") or {}).get("note", "")})
            if did in seen or not info:
                continue
            seen.add(did)
            if e["event_type"] == "borrow":
                days = (timezone.now() - e["occurred_at"]).days
                borrowed.append({**info, "device_id": did, "holder": e["counterparty"],
                                 "borrowed_at": e["occurred_at"], "days": days,
                                 "operator": names.get(e["operator_id"]),
                                 "note": (e.get("detail") or {}).get("note", "")})
        return Response({
            "borrowed": borrowed,
            "activity": activity,
            "threshold_days": self.LOAN_OVERDUE_DAYS,
            "stats": {"borrowed": len(borrowed),
                      "overdue": sum(1 for b in borrowed
                                     if b["days"] >= self.LOAN_OVERDUE_DAYS)},
        })

    @action(detail=True, methods=["post"], url_path="usage-claim")
    def usage_claim(self, request, pk=None):
        """借出/归还：body {claim: borrow|return, counterparty?, occurred_at?, note?}。

        borrow → usage_status=occupied + 资产事件(borrow)；return → idle + 事件(return)。
        重复借出/未借先归返回 400（edit 权限 + audit）。
        """
        _need_edit(request.user)
        dev = self.get_object()
        claim = request.data.get("claim")
        occurred = request.data.get("occurred_at") or timezone.now()
        note = request.data.get("note") or ""
        old = dev.usage_status
        ev = None
        if claim == "borrow":
            if old == Device.UsageStatus.OCCUPIED:
                return Response({"detail": "设备已在借（先归还再借出）"}, status=400)
            counterparty = (request.data.get("counterparty") or "").strip()
            if not counterparty:
                return Response({"detail": "counterparty 必填（借给谁/部门/单号）"}, status=400)
            dev.usage_status = Device.UsageStatus.OCCUPIED
            dev.save(update_fields=["usage_status", "updated_at"])
            ev = DeviceAssetEvent.objects.create(
                device_id=dev.pk, event_type="borrow", occurred_at=occurred,
                operator_id=request.user.id, counterparty=counterparty,
                detail={"note": note} if note else {})
        elif claim == "return":
            if old != Device.UsageStatus.OCCUPIED:
                return Response({"detail": "设备当前非在借状态，无法归还"}, status=400)
            dev.usage_status = Device.UsageStatus.IDLE
            dev.save(update_fields=["usage_status", "updated_at"])
            ev = DeviceAssetEvent.objects.create(
                device_id=dev.pk, event_type="return", occurred_at=occurred,
                operator_id=request.user.id, counterparty=request.data.get("counterparty", ""),
                detail={"note": note} if note else {})
        else:
            return Response({"detail": "claim must be borrow/return"}, status=400)
        from common.audit import write_audit
        write_audit(request.user, "update", "Device", dev.pk,
                    before={"usage_status": old}, after={"usage_status": dev.usage_status,
                                                         "claim": claim, "event_id": ev.id},
                    source_ip=request.META.get("REMOTE_ADDR", ""))
        return Response({"device_id": dev.pk, "usage_status": dev.usage_status,
                         "claim": claim, "event_id": ev.id})

    # ---------- 保修到期提醒（5.5.7 P1：30/60/90/180 + 已过期） ----------
    @action(detail=False, methods=["get"], url_path="warranty-expiring")
    def warranty_expiring(self, request):
        from datetime import date, timedelta
        today = date.today()
        days = min(int(request.query_params.get("within_days") or 90), 730)
        qs = Device.objects.filter(deleted_at__isnull=True, warranty_until__isnull=False)
        expired_qs = qs.filter(warranty_until__lt=today)
        expiring = qs.filter(warranty_until__gte=today, warranty_until__lte=today + timedelta(days=days))
        summary = {"expired": expired_qs.count(),
                   **{str(d): qs.filter(warranty_until__gt=today,
                                        warranty_until__lte=today + timedelta(days=d)).count()
                      for d in (30, 60, 90, 180)}}
        rows = []
        for dev in list(expiring.order_by("warranty_until")[:200]) + list(expired_qs.order_by("-warranty_until")[:100]):
            rows.append({
                "id": dev.id, "name": dev.name, "manage_ip": str(dev.manage_ip or ""),
                "vendor": dev.vendor, "hw_model": dev.hw_model,
                "warranty_until": dev.warranty_until, "days_left": (dev.warranty_until - today).days,
                "owner": dev.owner.username if dev.owner else None,
                "region_name": dev.region.name if dev.region else None,
                "site_name": dev.site.name if dev.site else None,
            })
        return Response({"summary": summary, "within_days": days, "rows": rows})

    # ---------- 网络总览（跨设备汇总：路由/邻居/链路/无线/VLAN + 扩展位） ----------
    @action(detail=False, methods=["get"], url_path="network-overview")
    def network_overview(self, request):
        """按 区域/站点 过滤（可选 region_id/site_id），汇总现有采集：

        neighbors=OSPF/BGP 邻居 / routes=最新路由快照 / links=链路状态(下行/高错包,含光功率)
        ap=无线AP / vlans=VLAN 使用分布 / extensions=待采集能力说明位(NAT/ACL/质量时序/无线深度)。
        新增采集品类时在此追加分区字段即可，前端按分区渲染——满足"随时拓展、后续迁移"。
        """
        from collections import Counter
        from apps.cmdb.models import (DeviceInterface, DeviceInterfaceStat, RoutingNeighbor,
                                      RouteTableSnapshot, WirelessApInfo)
        flt = {"deleted_at__isnull": True}
        rid = request.query_params.get("region_id")
        sid = request.query_params.get("site_id")
        if rid:
            flt["region_id"] = int(rid)
        if sid:
            flt["site_id"] = int(sid)
        devs = Device.objects.filter(**flt).only("id", "name", "manage_ip", "region", "site")
        ids = [d.id for d in devs]
        devmap = {d.id: {"name": d.name,
                         "manage_ip": str(d.manage_ip or ""),
                         "region": d.region.name if d.region else "",
                         "site": d.site.name if d.site else ""} for d in devs}

        # 邻居
        nrows = list(RoutingNeighbor.objects.filter(device_id__in=ids)
                     .order_by("protocol", "neighbor_addr")[:400])
        neigh_rows, state_c = [], Counter()
        for n in nrows:
            dm = devmap.get(n.device_id) or {}
            state_c[n.state] += 1
            neigh_rows.append({"device_id": n.device_id, **dm, "protocol": n.protocol,
                               "vrf": n.vrf or "", "neighbor_addr": n.neighbor_addr,
                               "state": n.state, "last_seen_at": n.last_seen_at})

        # 路由快照（每设备最新一条）
        rt_rows, prefix_total = [], 0
        latest = {}
        for rt in RouteTableSnapshot.objects.filter(device_id__in=ids).order_by("-snapshot_at"):
            if rt.device_id not in latest:
                latest[rt.device_id] = rt
        for did, rt in list(latest.items())[:200]:
            dm = devmap.get(did) or {}
            cnt = len(rt.routes or [])
            prefix_total += cnt
            rt_rows.append({"device_id": did, **dm, "snapshot_at": rt.snapshot_at,
                            "count": cnt, "route_hash": rt.route_hash[:12],
                            "age_days": (timezone.now() - rt.snapshot_at).days})

        # 链路：下行(admin up/oper down) + 高错包；全部统计 checked/down/high_error
        ifs = list(DeviceInterface.objects.select_related("device", "stat")
                   .filter(device_id__in=ids, admin_status="up")[:400])
        link_rows, link_sum = [], {"checked": 0, "down": 0, "high_error": 0}
        for i in ifs:
            st = getattr(i, "stat", None)
            down = i.oper_status == "down"
            herr = bool(st) and (float(st.in_errors_rate or 0) > 0.5
                                 or float(st.out_errors_rate or 0) > 0.5)
            link_sum["checked"] += 1
            if down:
                link_sum["down"] += 1
            if herr:
                link_sum["high_error"] += 1
            if down or herr:
                dm = devmap.get(i.device_id) or {}
                link_rows.append({
                    "device_id": i.device_id, **dm, "if_name": i.name,
                    "if_alias": i.if_alias, "media_type": i.media_type,
                    "admin_status": i.admin_status, "oper_status": i.oper_status,
                    "is_uplink": i.is_uplink, "speed_bps": i.speed_bps,
                    "stat": {"in_bps": st.in_bps, "out_bps": st.out_bps,
                             "in_errors_rate": str(st.in_errors_rate),
                             "out_errors_rate": str(st.out_errors_rate),
                             "optical_tx_dbm": str(st.optical_tx_dbm) if st.optical_tx_dbm else None,
                             "optical_rx_dbm": str(st.optical_rx_dbm) if st.optical_rx_dbm else None,
                             "updated_at": st.updated_at} if st else None,
                })
        link_rows.sort(key=lambda x: (x["oper_status"] != "down", -float(x["stat"]["in_errors_rate"])
                                      if x["stat"] and x["stat"]["in_errors_rate"] else 0))

        # 无线 AP
        ap_qs = WirelessApInfo.objects.select_related("device").filter(device_id__in=ids)
        ap_rows = [{"device_id": a.device_id,
                    "name": a.device.name, "ap_name": a.ap_name, "ap_model": a.ap_model,
                    "ap_ip": str(a.ap_ip or ""), "status": a.status,
                    "client_count": a.client_count, "channel_2g": a.channel_2g,
                    "channel_5g": a.channel_5g, "tx_power": a.tx_power,
                    "site": a.device.site.name if a.device.site else "",
                    "synced_at": a.synced_at}
                   for a in ap_qs[:200]]

        # VLAN 使用分布（native + tagged）
        vlan_cnt = Counter()
        for i in ifs:
            if i.native_vlan:
                vlan_cnt[i.native_vlan] += 1
            for v in (i.vlan_ids or []):
                vlan_cnt[v] += 1
        vlan_rows = [{"vlan": v, "count": c} for v, c in vlan_cnt.most_common(50)]

        # 扩展采集品类聚合（TechSnapshot：acl/nat/ipsec 按设备取最新，汇总台数与条目数）
        agg, seen = {}, set()
        for ts in TechSnapshot.objects.filter(
                device_id__in=ids, kind__in=("acl", "nat", "ipsec")).order_by("kind", "device_id", "-id"):
            key = (ts.device_id, ts.kind)
            if key in seen:
                continue
            seen.add(key)
            b = agg.setdefault(ts.kind, {"devices": 0, "total": 0, "latest": ts.created_at})
            b["devices"] += 1
            b["total"] += len((ts.payload or {}).get("rows") or [])
            if ts.created_at > b["latest"]:
                b["latest"] = ts.created_at
        ext_items = [
            {"key": "nat", "label": "公网 NAT/VIP", "collected": False,
             "note": "设备 360 粘贴 FortiOS show firewall vip 解析落库（tech-parse）"},
            {"key": "acl", "label": "ACL 策略", "collected": False,
             "note": "设备 360 粘贴 ASA show access-list 解析落库（tech-parse）"},
            {"key": "ipsec", "label": "IPSec 隧道", "collected": False,
             "note": "设备 360 粘贴 FortiOS get vpn ipsec tunnel status 解析落库（tech-parse）"},
            {"key": "quality_history", "label": "链路质量时序(错包/时延/丢包趋势)", "collected": False,
             "note": "依赖 DeviceInterfaceStat 周期采样落历史表"},
            {"key": "wireless_deep", "label": "无线深度(漫游/RSSI/信道利用率)", "collected": False,
             "note": "依赖 WLC 详细采集"},
        ]
        for e in ext_items:
            a = agg.get(e["key"])
            if a:
                e.update(collected=True, devices=a["devices"], total=a["total"], latest_at=a["latest"])

        return Response({
            "generated_at": timezone.now().isoformat(),
            "meta": {"region_id": rid, "site_id": sid, "devices_covered": len(ids),
                     "extensible": True},
            "neighbors": {"rows": neigh_rows[:200], "by_state": dict(state_c)},
            "routes": {"devices_with_snapshot": len(rt_rows), "total_prefixes": prefix_total,
                       "rows": rt_rows},
            "links": {"summary": link_sum, "rows": link_rows[:200]},
            "ap": {"rows": ap_rows},
            "vlans": {"rows": vlan_rows},
            "extensions": ext_items,
        })

    # ---------- 业务-设备归属（系统域：业务矩阵） ----------
    @action(detail=False, methods=["get"], url_path="business-summary")
    def business_summary(self, request):
        rows = []
        alive = Device.objects.filter(deleted_at__isnull=True)
        alive_ids = set(alive.values_list("id", flat=True))
        for b in Business.objects.order_by("code")[:200]:
            links = DeviceBusiness.objects.filter(business=b, device_id__in=alive_ids)
            regions, sites = set(), set()
            for l in links.values("device__region__name", "device__site__name"):
                if l.get("device__region__name"):
                    regions.add(l["device__region__name"])
                if l.get("device__site__name"):
                    sites.add(l["device__site__name"])
            rows.append({
                "id": b.id, "name": b.name, "code": b.code, "importance": b.importance,
                "remark": b.remark, "device_count": links.count(),
                "regions": sorted(regions)[:8], "sites": sorted(sites)[:8],
            })
        linked = alive.filter(id__in=DeviceBusiness.objects.values("device_id")).count()
        return Response({
            "businesses": rows, "total_devices": alive.count(),
            "linked_devices": linked, "unassigned_devices": alive.count() - linked,
        })

    @action(detail=False, methods=["post"], url_path="business-assign")
    def business_assign(self, request):
        """业务设备归属维护：body {business_id, device_ids:[...], action: add|remove}。"""
        _need_edit(request.user)
        b = Business.objects.filter(pk=request.data.get("business_id")).first()
        if not b:
            return Response({"detail": "business not found"}, status=404)
        action = request.data.get("action")
        if action not in ("add", "remove"):
            return Response({"detail": "action must be add/remove"}, status=400)
        ids = request.data.get("device_ids") or []
        if not isinstance(ids, list):
            return Response({"detail": "device_ids must be list"}, status=400)
        ids = list(dict.fromkeys(int(i) for i in ids if str(i).isdigit()))
        existing = set(DeviceBusiness.objects.filter(business=b, device_id__in=ids)
                       .values_list("device_id", flat=True))
        role = request.data.get("role") or "member"
        if action == "add":
            to_create = [DeviceBusiness(business=b, device_id=i, role=role)
                         for i in ids if i not in existing]
            DeviceBusiness.objects.bulk_create(to_create)
            changed = len(to_create)
        else:
            changed, _ = DeviceBusiness.objects.filter(business=b, device_id__in=ids).delete()
        from common.audit import write_audit
        write_audit(request.user, "update", "Business", b.pk,
                    before={"action": action}, after={"device_ids": ids, "changed": changed},
                    source_ip=request.META.get("REMOTE_ADDR", ""))
        return Response({"business_id": b.pk, "action": action, "changed": changed})

    # ---------- 系统域清单（形态/厂商/OS/用途 分布 + 明细） ----------
    @action(detail=False, methods=["get"], url_path="system-summary")
    def system_summary(self, request):
        from django.db.models import Count as _C
        qs = Device.objects.filter(deleted_at__isnull=True)
        q = lambda base: list(base.annotate(c=_C("id")).order_by("-c"))
        morph = [{"label": "物理机" if not m["is_virtual"] else "虚拟机/云主机",
                  "is_virtual": m["is_virtual"], "count": m["c"]}
                 for m in q(qs.values("is_virtual"))]
        model_cat = q(qs.exclude(model__isnull=True)
                      .values("model__code", "model__name", "model__category"))
        return Response({
            "morph": morph, "model_cat": model_cat,
            "vendor": q(qs.exclude(vendor="").values("vendor")),
            "os": q(qs.exclude(sw_version="").values("sw_version")),
            "usage": q(qs.exclude(usage_tag="").values("usage_tag")),
        })

    # ---------- 链路质量时间序列（LinkQualitySample） ----------
    @action(detail=False, methods=["get"], url_path="link-quality-overview")
    def link_quality_overview(self, request):
        """近 N 小时链路质量：按接口聚合并降采样 36 桶（网络级，无需前端设备 id）。"""
        from datetime import timedelta as _td
        hours = int(request.query_params.get("hours", 24))
        since = timezone.now() - _td(hours=hours)
        rows = list(LinkQualitySample.objects.filter(sampled_at__gte=since)
                    .order_by("sampled_at")[:6000])
        if not rows:
            return Response({"hours": hours, "generated": timezone.now(), "interfaces": []})
        devn = {d.id: d.name for d in Device.objects.filter(
            id__in={r.device_id for r in rows})}
        grouped = {}
        for r in rows:
            g = grouped.setdefault(r.interface_id, {"device_id": r.device_id,
                                                    "iface": r.iface_name, "pts": []})
            g["pts"].append((r.sampled_at.timestamp(), float(r.in_bps or 0),
                             float(r.out_bps or 0), float(r.in_errors_rate or 0)))
        out = []
        for iid, g in grouped.items():
            pts = g["pts"]
            t0, t1, NB = pts[0][0], pts[-1][0], 36
            span = max(t1 - t0, 1)
            buckets = []
            for bi in range(NB):
                lo = t0 + span * bi / NB
                hi = t0 + span * (bi + 1) / NB
                sel = [p for p in pts if lo <= p[0] < hi or (bi == NB - 1 and p[0] <= hi)]
                if not sel:
                    continue
                buckets.append({"ts": int((lo + hi) / 2),
                                "in": round(sum(p[1] for p in sel) / len(sel)),
                                "out": round(sum(p[2] for p in sel) / len(sel)),
                                "err": round(max(p[3] for p in sel), 2)})
            ins, outs = [p[1] for p in pts], [p[2] for p in pts]
            out.append({
                "interface_id": iid, "device_id": g["device_id"],
                "device": devn.get(g["device_id"], ""), "iface": g["iface"],
                "samples": len(pts),
                "avg_in": int(sum(ins) / len(ins)), "peak_in": int(max(ins)),
                "avg_out": int(sum(outs) / len(outs)), "peak_out": int(max(outs)),
                "peak_err": max(p[3] for p in pts), "buckets": buckets})
        out.sort(key=lambda x: (x["device"], x["iface"]))
        return Response({"hours": hours, "generated": timezone.now(), "interfaces": out})

    @action(detail=False, methods=["post"], url_path="link-quality-sample")
    def link_quality_sample(self, request):
        """按需取样（execute 权限）：等价 beat 任务 cmdb.sample_link_quality 单次执行。"""
        _need_execute(request.user)
        from apps.cmdb.linkquality import sample_link_quality
        try:
            r = sample_link_quality(request.data.get("keep_days") or 7)
        except (TypeError, ValueError):
            return Response({"detail": "keep_days must be int"}, status=400)
        from common.audit import write_audit
        write_audit(request.user, "execute", "LinkQualitySample", None,
                    after={**r, "action": "link-quality-sample"},
                    source_ip=request.META.get("REMOTE_ADDR", ""))
        return Response(r)

    @action(detail=True, methods=["post"], url_path="snmp-test")
    def snmp_test(self, request, pk=None):
        """SNMP 采集单测/手动触发：body {mock: 0|1}（默认 1 防误触真网络；
        mock=0 需设备已绑定 snmp_v2c 凭据）。execute 权限 + audit。"""
        _need_execute(request.user)
        dev = self.get_object()
        mock = str(request.data.get("mock", 1)) not in ("0", "false", "False")
        from apps.cmdb import snmp as snmp_mod
        if mock:
            r = snmp_mod.collect(dev, profile="if-mib", mock=True,
                                 octets_step=request.data.get("octets_step") or 0)
        else:
            from apps.system.models import Credential
            cred = (Credential.objects.filter(pk=dev.credential_id)
                    .filter(cred_type__startswith="snmp").first() if dev.credential_id else None)
            if not cred:
                return Response({"detail": "设备未绑定 SNMP 凭据（需 Credential 类型 snmp_* 且设备 credential_id 指向它）"},
                                status=400)
            if cred.cred_type != "snmp_v2c":
                return Response({"detail": "当前仅支持 SNMPv2c（v1/v3 待接入）"}, status=400)
            try:
                r = snmp_mod.collect(dev, mock=False, community=cred.secret,
                                     port=(cred.params or {}).get("port") or 161)
            except ValueError as e:
                return Response({"detail": str(e)}, status=400)
        from common.audit import write_audit
        write_audit(request.user, "execute", "SnmpCollect", dev.pk,
                    after={**r, "action": "snmp-test", "mock": mock},
                    source_ip=request.META.get("REMOTE_ADDR", ""))
        return Response(r)

    @action(detail=True, methods=["post"], url_path="prom-test")
    def prom_test(self, request, pk=None):
        """Prometheus 接入单测/手动触发：body {mock:0|1}（默认 1 走内置样例；
        mock=0 需服务端已配 NOPS_PROM_URL/TOKEN，按模板查询拉真实指标）。
        execute 权限 + audit。"""
        _need_execute(request.user)
        dev = self.get_object()
        mock = str(request.data.get("mock", 1)) not in ("0", "false", "False")
        from apps.cmdb import prometheus as prom_mod
        if mock:
            r = prom_mod.collect_mock(dev)
        else:
            import os
            base = (os.getenv("NOPS_PROM_URL") or "").strip()
            if not base:
                return Response({"detail": "服务端未配置 NOPS_PROM_URL（演示请用 mock=1）"},
                                status=400)
            try:
                r = prom_mod.poll_once(base, os.getenv("NOPS_PROM_TOKEN") or "")
            except ValueError as e:
                return Response({"detail": str(e)}, status=400)
            r = {**r, "target": base}
        from common.audit import write_audit
        write_audit(request.user, "execute", "PromPoll", dev.pk,
                    after={**r, "action": "prom-test", "mock": mock},
                    source_ip=request.META.get("REMOTE_ADDR", ""))
        return Response(r)


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
