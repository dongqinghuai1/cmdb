"""dcim 服务层：机柜 U 位视图 + 跨表冲突校验（ER D2：DB 不支持跨表 EXCLUDE，服务层统一校验）。"""
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.dcim.models import Rack, RackReservation


class RackService:
    @staticmethod
    def _occupied_ranges(rack_id, exclude_device_id=None):
        """返回 [(start, end_exclusive)]：设备占用 + 有效预留。"""
        from apps.cmdb.models import Device  # cmdb 视图内调用；仅服务层允许
        ranges = []
        dev_qs = Device.objects.filter(rack_id=rack_id, deleted_at__isnull=True,
                                       rack_start_u__isnull=False)
        if exclude_device_id:
            dev_qs = dev_qs.exclude(pk=exclude_device_id)
        for d in dev_qs.values_list("rack_start_u", "rack_units"):
            ranges.append((d[0], d[0] + d[1]))
        now = timezone.now()
        for r in RackReservation.objects.filter(rack_id=rack_id).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=now)).values_list("start_u", "units"):
            ranges.append((r[0], r[0] + r[1]))
        return ranges

    @classmethod
    def check_placement(cls, rack_id, start_u, units, exclude_device_id=None):
        """上架/预留/换位统一冲突校验：同柜 U 区间不得相交，且不越界。"""
        rack = Rack.objects.get(pk=rack_id)
        if not start_u or start_u < 1 or start_u + units - 1 > rack.u_total:
            raise ValueError(f"U 位越界：有效范围 1~{rack.u_total}")
        new = (start_u, start_u + units)
        for s, e in cls._occupied_ranges(rack_id, exclude_device_id):
            if new[0] < e and s < new[1]:
                raise ValueError(f"U 位冲突：与已占用/预留区间 U{s}~U{e - 1} 重叠")
        return True

    @classmethod
    def elevation(cls, rack_id):
        """机柜可视化数据（附录 C 交互）：units 从顶(U_total)到底(1)。"""
        from apps.cmdb.models import Device
        rack = Rack.objects.select_related("site", "site__region").get(pk=rack_id)
        now = timezone.now()
        resv = {r["start_u"]: r for r in RackReservation.objects.filter(rack_id=rack_id).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)).values("start_u", "units", "reason")}
        units = []
        for u in range(rack.u_total, 0, -1):
            entry = {"u": u, "status": "free", "device": None, "reservation": None}
            for s, meta in resv.items():
                if s <= u < s + meta["units"]:
                    entry.update(status="reserved", reservation={"reason": meta["reason"]})
                    break
            units.append(entry)
        for d in Device.objects.filter(rack_id=rack_id, deleted_at__isnull=True).values(
                "id", "name", "vendor", "hw_model", "rack_start_u", "rack_units",
                "online_status", "usage_tag"):
            u0, n = d["rack_start_u"], d["rack_units"]
            for entry in units:
                if u0 <= entry["u"] < u0 + n:
                    entry.update(status="occupied", device=d)
        used = sum(1 for e in units if e["status"] == "occupied")
        return {
            "rack": {"id": rack.id, "name": rack.name, "u_total": rack.u_total,
                     "site": rack.site.name, "region": rack.site.region.name},
            "units": units,
            "summary": {"used_u": used, "free_u": rack.u_total - used,
                        "reserved_u": sum(1 for e in units if e["status"] == "reserved")},
        }

    @staticmethod
    def capacity(site_id=None):
        """机房容量汇总（ER v_rack_capacity）。"""
        from apps.cmdb.models import Device
        racks = Rack.objects.all()
        if site_id:
            racks = racks.filter(site_id=site_id)
        out = []
        for r in racks:
            dev = Device.objects.filter(rack=r, deleted_at__isnull=True)
            out.append({"id": r.id, "name": r.name, "site_id": r.site_id, "u_total": r.u_total,
                        "used_u": dev.aggregate(models.Sum("rack_units"))["rack_units__sum"] or 0,
                        "power_w": sum(d.get("rated_power_w") or 0 for d in dev.values("rated_power_w")),
                        "rated_power_w": r.rated_power_w})
        return out
