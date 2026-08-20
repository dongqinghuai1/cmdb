"""IPAM services: usage stats + ARP discover & conflict detection."""
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


def import_arp(text: str) -> dict:
    """粘贴 ARP 表（'ip mac' 每行）：
    - 网段内的 IP：已登记(reserved/free) -> 置 used(arp)；已 used 且 mac 不同 -> conflict
    - 未登记 -> 新增 used(arp_discover)
    返回 {created, updated, conflict, out_of_scope}"""
    from apps.ipam.models import IpAddress, Subnet
    subnets = list(Subnet.objects.all())
    now = timezone.now()
    created = updated = conflict = out = 0
    report = []
    for line in text.splitlines():
        m = ARP_LINE.search(line)
        if not m:
            continue
        ip_str, mac = m.group(1), m.group(2).lower().replace("-", ":").replace(".", ":")
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        sn = next((s for s in subnets if ip in s.network), None)
        if not sn:
            out += 1
            continue
        obj = IpAddress.objects.filter(subnet=sn, address=str(ip)).first()
        if not obj:
            IpAddress.objects.create(subnet=sn, address=str(ip), status="used",
                                     mac=mac, source="arp_discover", last_seen_at=now)
            created += 1
        elif obj.status in ("reserved", "free"):
            obj.status, obj.mac, obj.source, obj.last_seen_at = "used", mac, "arp_discover", now
            obj.save(update_fields=["status", "mac", "source", "last_seen_at", "updated_at"])
            updated += 1
        elif obj.mac and obj.mac.lower() != mac:
            obj.status, obj.last_seen_at = "conflict", now
            obj.save(update_fields=["status", "last_seen_at", "updated_at"])
            conflict += 1
            report.append({"ip": str(ip), "registered_mac": obj.mac, "arp_mac": mac})
        else:
            obj.last_seen_at = now
            obj.save(update_fields=["last_seen_at", "updated_at"])
    return {"created": created, "updated": updated, "conflict": conflict,
            "out_of_scope": out, "conflict_detail": report,
            "ts": now + timedelta(0)}
