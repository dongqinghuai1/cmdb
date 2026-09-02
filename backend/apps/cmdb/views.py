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
from apps.cmdb.models import (CiModel, CiModelAttr, Device, DeviceAssetEvent,
                              DeviceAttachment, DeviceGroup, License, TechSnapshot)
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
        for kind, note in (("acl", "ACL 策略采集驱动未接入"), ("ipsec", "IPSec/IKE 隧道采集驱动未接入")):
            ts = TechSnapshot.objects.filter(device_id=d.pk, kind=kind).first()
            if ts:
                extensions[kind] = {"supported": True, "updated_at": ts.created_at,
                                    "payload": ts.payload}
            else:
                extensions[kind] = {"supported": False,
                                    "note": f"{note}（R3 已建模 cmdb_techsnapshot：采集驱动解析后 POST tech-snapshot 落库即在此展示）"}
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
            "extensions": [
                {"key": "nat", "label": "公网 S/D NAT 状态", "collected": False,
                 "note": "待 fortigate/asa 采集驱动写入 TechSnapshot(kind=nat)"},
                {"key": "acl", "label": "ACL 策略", "collected": False,
                 "note": "已建模 cmdb_techsnapshot(kind=acl)，待采集驱动"},
                {"key": "quality_history", "label": "链路质量时序(错包/时延/丢包趋势)", "collected": False,
                 "note": "依赖 DeviceInterfaceStat 周期采样落历史表"},
                {"key": "wireless_deep", "label": "无线深度(漫游/RSSI/信道利用率)", "collected": False,
                 "note": "依赖 WLC 详细采集"},
            ],
        })


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
