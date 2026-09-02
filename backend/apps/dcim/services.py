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


def compare_lldp_cables(site_id=None):
    """线缆台账 vs LLDP 邻居比对（ER D7：lldp_neighbor 实测 与 cable 台账分离比对）。

    口径（幂等，可反复执行）：
      1. manual 台账线缆，两端在 LLDP 邻居中出现且对端设备+接口名匹配 → 确认（恢复
         active + 刷新 last_seen）；
      2. manual 台账线缆无对应邻居（LLDP 未发现/物理链路异常）→ status=mismatch +
         remark 标注（不删除台账，待人工处置）；
      3. LLDP 可见而台账缺失（对端为已纳管设备且接口可解析）→ 补录 source=lldp 线缆
         （active），path_desc 标注"LLDP 自动发现"。

    跨域只读用 raw SQL（不 import topo/cmdb 模型）；写回仅动 dcim.Cable。"""
    from django.db import connection
    from apps.dcim.models import Cable

    with connection.cursor() as cur:
        cond = ["c.deleted_at IS NULL", "c.source = 'manual'", "ib.id IS NOT NULL"]
        params = []
        if site_id:
            cond.append("da.site_id = %s")
            params.append(site_id)
        cur.execute(f"""
            SELECT c.id, c.a_interface_id, c.b_interface_id,
                   da.id, db2.id, ia.name, ib.name
            FROM dcim_cable c
            JOIN cmdb_deviceinterface ia ON ia.id = c.a_interface_id
            JOIN cmdb_device da ON da.id = ia.device_id
            JOIN cmdb_deviceinterface ib ON ib.id = c.b_interface_id
            JOIN cmdb_device db2 ON db2.id = ib.device_id
            WHERE {" AND ".join(cond)}""", params)
        cables = cur.fetchall()
        cur.execute("""
            SELECT ln.local_interface_id, ifc.device_id, ifc.name,
                   ln.remote_device_id, ln.remote_port_desc, ln.remote_port_id
            FROM topo_lldpneighbor ln
            JOIN cmdb_deviceinterface ifc ON ifc.id = ln.local_interface_id
            WHERE ln.remote_device_id IS NOT NULL""")
        nbrs = cur.fetchall()
        cur.execute("""
            SELECT c.id, c.a_interface_id, c.b_interface_id, ia.device_id, ib.device_id
            FROM dcim_cable c
            JOIN cmdb_deviceinterface ia ON ia.id = c.a_interface_id
            JOIN cmdb_deviceinterface ib ON ib.id = c.b_interface_id
            WHERE c.deleted_at IS NULL""")
        _rows = cur.fetchall()
        exist_pairs = {(r[1], r[2]) for r in _rows} | {(r[2], r[1]) for r in _rows}
        cur.execute("""
            SELECT i.device_id, i.id, i.name FROM cmdb_deviceinterface i
            WHERE i.name <> ''""")
        iface_by_dev_name = {}
        for dev_id, iid, name in cur.fetchall():
            iface_by_dev_name.setdefault((dev_id, name), iid)

    def _port_matches(port_desc, port_id, name):
        return (name and port_desc == name) or (name and port_id == name)

    matched_ids, mismatch_ids = set(), set()
    for cid, a_if, b_if, a_dev, b_dev, a_name, b_name in cables:
        hit = any(
            (n[1] == a_dev and n[2] == a_name and n[3] == b_dev
             and _port_matches(n[4], n[5], b_name))
            or (n[1] == b_dev and n[2] == b_name and n[3] == a_dev
                and _port_matches(n[4], n[5], a_name))
            for n in nbrs)
        if hit:
            matched_ids.add(cid)
        else:
            mismatch_ids.add(cid)
    now = timezone.now()
    if matched_ids:
        Cable.objects.filter(pk__in=matched_ids, status=Cable.Status.MISMATCH) \
            .update(status=Cable.Status.ACTIVE, remark="", last_seen_at=now)
        Cable.objects.filter(pk__in=matched_ids).exclude(
            status=Cable.Status.MISMATCH).update(last_seen_at=now)
    if mismatch_ids:
        Cable.objects.filter(pk__in=mismatch_ids).exclude(
            status=Cable.Status.MISMATCH).update(
                status=Cable.Status.MISMATCH, remark="LLDP 未发现该链路（比对时间 "
                + timezone.now().strftime("%Y-%m-%d %H:%M") + "）")

    # LLDP 可见而未录入台账 → 补录（仅对端已纳管 + 接口名可解析；双向去重）
    discovered, skipped_remote = [], 0
    for _lid, a_dev, a_name, b_dev, b_port_desc, b_port_id in nbrs:
        b_if = iface_by_dev_name.get((b_dev, b_port_desc)) or \
               iface_by_dev_name.get((b_dev, b_port_id))
        if not b_if:
            skipped_remote += 1
            continue
        pair = tuple(sorted((_lid, b_if)))
        if pair in exist_pairs:
            continue
        Cable.objects.create(a_interface_id=pair[0], b_interface_id=pair[1],
                             source=Cable.Source.LLDP, status=Cable.Status.ACTIVE,
                             path_desc=f"LLDP 自动发现 {b_port_desc or b_port_id or ''}",
                             last_seen_at=now)
        exist_pairs.add(pair)
        discovered.append({"a_interface_id": pair[0], "b_interface_id": pair[1]})

    return {"cables": len(cables), "confirmed": len(matched_ids),
            "mismatch": len(mismatch_ids), "discovered": len(discovered),
            "discovered_links": discovered[:20],
            "skipped_remote_unmanaged": skipped_remote,
            "compared_at": timezone.now().isoformat()}
