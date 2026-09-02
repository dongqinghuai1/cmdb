"""IPAM services: usage stats / ARP 采集导入(含 interface 回填) / 大网段格子图切片。"""
import ipaddress
import re
from datetime import timedelta

from django.utils import timezone


def subnet_usage(subnet) -> dict:
    from apps.ipam.models import IpAddress
    q = IpAddress.objects.filter(subnet=subnet)
    return {
        "total": subnet.usable_size,
        "used": q.filter(status="used").count(),
        "reserved": q.filter(status="reserved").count(),
        "conflict": q.filter(status="conflict").count(),
    }


ARP_LINE = re.compile(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F:.-]{12,17})")


def _normalize_mac(mac):
    return (mac or "").lower().replace("-", ":").replace(".", ":").strip()


def _apply_entry(sn, ip_str, mac, if_index=None, device_id=None, report=None):
    """登记/刷新一条 ARP 记录；if_index+device_id 命中该设备接口则回填 interface_id。
    返回 (kind, obj|None)。kind ∈ created/updated/conflict/touched/out。"""
    from apps.ipam.models import IpAddress
    now = timezone.now()
    mac = _normalize_mac(mac)
    obj = IpAddress.objects.filter(subnet=sn, address=ip_str).first()
    if not obj:
        obj = IpAddress.objects.create(subnet=sn, address=str(ip_str), status="used",
                                       mac=mac, source="arp_discover", last_seen_at=now)
        kind = "created"
    elif obj.status in ("reserved", "free"):
        obj.status, obj.mac, obj.source, obj.last_seen_at = "used", mac, "arp_discover", now
        kind = "updated"
    elif obj.mac and obj.mac.lower() != mac:
        obj.status, obj.last_seen_at = "conflict", now
        kind = "conflict"
        if report is not None:
            report.append({"ip": str(ip_str), "registered_mac": obj.mac, "arp_mac": mac})
    else:
        obj.last_seen_at = now
        kind = "touched"
    if if_index and kind != "conflict":
        from apps.cmdb.models import DeviceInterface
        iface = DeviceInterface.objects.filter(device_id=device_id,
                                               if_index=int(if_index)).first() \
            if device_id else None
        if iface and obj.interface_id != iface.pk:
            obj.interface_id = iface.pk
            obj.save(update_fields=["interface_id", "status", "mac", "source",
                                    "last_seen_at", "updated_at"])
            return kind + ":linked", obj
    obj.save(update_fields=["status", "mac", "source", "last_seen_at", "updated_at"])
    return kind, obj


def import_arp(text: str) -> dict:
    """粘贴 ARP 表（'ip mac' 每行）→ 登记/更新/冲突/范围外。返回计数汇总。"""
    from apps.ipam.models import Subnet
    subnets = list(Subnet.objects.all())
    counts = {"created": 0, "updated": 0, "conflict": 0, "touched": 0,
              "out_of_scope": 0, "linked": 0}
    report = []
    for line in text.splitlines():
        m = ARP_LINE.search(line)
        if not m:
            continue
        ip_str, mac = m.group(1), m.group(2)
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        sn = next((s for s in subnets if ip in s.network), None)
        if not sn:
            counts["out_of_scope"] += 1
            continue
        kind, obj = _apply_entry(sn, ip_str, mac)
        if kind == "conflict":
            report.append({"ip": ip_str, "registered_mac": obj.mac, "arp_mac": mac})
        if kind.startswith("created"):
            counts["created"] += 1
        elif kind.startswith("updated"):
            counts["updated"] += 1
        elif kind.startswith("conflict"):
            counts["conflict"] += 1
        elif kind == "touched":
            counts["touched"] += 1
        if ":linked" in kind:
            counts["linked"] += 1
    return {**counts, "conflict_detail": report, "ts": str(timezone.now())}


def ingest_arp_rows(rows, device_id=None):
    """采集器行流（snmp ARP 表）→ 登记 + interface 回填。rows: [{ip, mac, if_index}]。"""
    from apps.ipam.models import Subnet
    subnets = list(Subnet.objects.all())
    counts = {"created": 0, "updated": 0, "conflict": 0, "touched": 0,
              "out_of_scope": 0, "linked": 0}
    detail = []
    for row in rows:
        ip_str, mac = (row.get("ip") or "").strip(), (row.get("mac") or "").strip()
        if not ip_str or not mac:
            continue
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        sn = next((s for s in subnets if ip in s.network), None)
        if not sn:
            counts["out_of_scope"] += 1
            continue
        kind, obj = _apply_entry(sn, ip_str, mac, if_index=row.get("if_index"),
                                 device_id=device_id)
        if kind == "conflict":
            detail.append({"ip": ip_str, "registered_mac": obj.mac, "arp_mac": mac})
        if kind.startswith("created"):
            counts["created"] += 1
        elif kind.startswith("updated"):
            counts["updated"] += 1
        elif kind.startswith("conflict"):
            counts["conflict"] += 1
        elif kind == "touched":
            counts["touched"] += 1
        if ":linked" in kind:
            counts["linked"] += 1
    return {**counts, "detail": detail, "device_id": device_id}


def arp_poll(device_ids=None, mock=True):
    """周期/手动 ARP 采集：复用 apps.cmdb.snmp（单采集栈）走查 ipNetToMediaTable →
    ingest（登记/冲突/interface 回填）。mock=True 演练样例（不触网，无 manage_ip 以 127 兜底）。"""
    from apps.cmdb.models import Device
    from apps.system.models import Credential
    from apps.cmdb import snmp as snmp_mod
    qs = Device.objects.filter(deleted_at__isnull=True).order_by("id")
    if device_ids:
        qs = qs.filter(id__in=[int(i) for i in device_ids])
    total = {"checked": 0, "skipped": 0, "calibration": 0, "errors": 0}
    merged = None
    devices_report = []
    for d in qs:
        cred = (Credential.objects.filter(pk=d.credential_id)
                .filter(cred_type="snmp_v2c").first() if d.credential_id else None)
        host = d.manage_ip or ("127.0.0.1" if mock else None)
        if mock:
            cred = cred or type("C", (), {"secret": "public", "params": {}})()
            port = (cred.params or {}).get("port") or 161
            community = cred.secret
        else:
            if not cred or not host:
                total["skipped"] += 1
                continue
            port = (cred.params or {}).get("port") or 161
            community = cred.secret
        try:
            r = snmp_mod.collect_arp(host, community, port=port, mock=mock)
            total["checked"] += 1
            res = ingest_arp_rows(r.get("rows", []), device_id=d.pk)
            if merged is None:
                merged = {k: v for k, v in res.items() if k not in ("detail", "device_id")}
            else:
                for k in ("created", "updated", "conflict", "touched",
                          "out_of_scope", "linked"):
                    merged[k] = merged.get(k, 0) + res.get(k, 0)
            devices_report.append({"device_id": d.pk, "name": d.name,
                                   "rows": len(r.get("rows", [])),
                                   **{k: res.get(k) for k in
                                      ("created", "conflict", "linked")}})
        except Exception as e:  # noqa: BLE001 —— 单设备失败不拖垮
            name = type(e).__name__
            if name == "RequiresCalibration":
                total["calibration"] += 1
            else:
                total["errors"] += 1
            devices_report.append({"device_id": d.pk, "error": str(e)[:160]})
    return {"mock": mock, "devices": len(devices_report), **total,
            "summary": merged or {"created": 0, "updated": 0, "conflict": 0,
                                  "touched": 0, "out_of_scope": 0, "linked": 0},
            "detail": devices_report[:30]}


def subnet_map(subnet, offset=0, limit=512):
    """大网段格子图切片：usable 地址按整数偏移推进（offset 起最多 limit 格，不物化全段），
    每格附当前登记状态。返回 {cidr, usable_total, start_offset, count, rows}。"""
    from apps.ipam.models import IpAddress
    net = subnet.network
    total = subnet.usable_size
    offset = max(int(offset), 0)
    limit = max(min(int(limit), 2048), 1)
    base = int(net.network_address)
    size = net.num_addresses
    addrs = []
    for i in range(offset, min(offset + limit, total)):
        a = base + i
        if net.version == 4:
            if a == base or a == base + size - 1:  # 网络号/广播不在 usable 内
                continue
        addrs.append(str(ipaddress.ip_address(a)))
    statuses = dict(IpAddress.objects.filter(subnet=subnet, address__in=addrs)
                    .values_list("address", "status"))
    rows = [{"address": a, "status": statuses.get(a, "free")} for a in addrs]
    return {"cidr": subnet.cidr, "usable_total": total,
            "start_offset": offset, "count": len(rows), "rows": rows,
            "usage": subnet_usage(subnet)}
