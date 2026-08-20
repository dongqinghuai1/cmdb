"""AP ledger sync: paste Cisco WLC `show ap summary` output -> Device + WirelessApInfo.

支持 3504(AIRESPACE) 与 9800 同格式输出；行格式（容忍空格数）：
AP Name            Slots  AP Model  MAC Address       ...  Status  IP Address
"""
import re

AP_LINE = re.compile(
    r"^([\w.-]+)\s+(\d+)\s+([\w-]+)\s+([0-9a-fA-F:.-]{12,17})\s+.*?(\d+\.\d+\.\d+\.\d+)?\s*$")


def parse_ap_summary(text: str) -> list:
    """返回 [{name, model, mac, ip}]；跳过表头与汇总行。"""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or re.match(r"^(AP Name|Total Number|Number of)", line, re.I):
            continue
        m = re.match(r"^([\w.-]+)\s+(\d+)\s+([\w.-]+)\s+([0-9a-fA-F:.-]{12,17})(.*)$", line)
        if not m:
            continue
        tail = m.group(5)
        ipm = re.search(r"(\d+\.\d+\.\d+\.\d+)", tail)
        mac = m.group(4).lower().replace("-", ":").replace(".", ":")
        if len(mac) == 14:  # aabb.ccdd.eeff -> aa:bb:cc:dd:ee:ff
            mac = ":".join(mac[i:i + 2] for i in range(0, 14, 2))
        out.append({"name": m.group(1), "model": m.group(3), "mac": mac,
                    "ip": ipm.group(1) if ipm else None})
    return out


def sync_aps(wlc_device_id: int, text: str) -> dict:
    """解析 show ap summary 并同步：AP 设备 get_or_create + WirelessApInfo upsert。"""
    from apps.cmdb.models import CiModel, Device, WirelessApInfo
    from django.utils import timezone
    wlc = Device.objects.filter(pk=wlc_device_id).first()
    if not wlc:
        raise ValueError("WLC 设备不存在")
    ap_model = CiModel.objects.filter(code="ap").first()
    if not ap_model:
        raise ValueError("缺少 ap 设备类型（运行 init_nops_data）")
    now = timezone.now()
    created = updated = 0
    aps = parse_ap_summary(text)
    for ap in aps:
        dev, is_new = Device.objects.get_or_create(
            name=ap["name"], deleted_at__isnull=True,
            defaults={"model": ap_model, "vendor": "Cisco", "hw_model": ap["model"],
                      "sn": ap["mac"], "manage_ip": ap["ip"],
                      "region": wlc.region, "site": wlc.site})
        if is_new:
            created += 1
        else:
            updated += 1
        info, _ = WirelessApInfo.objects.get_or_create(device=dev)
        WirelessApInfo.objects.filter(pk=info.pk).update(
            wlc_device_id=wlc.id, ap_name=ap["name"], ap_model=ap["model"],
            ap_ip=ap["ip"], status="online", synced_at=now)
    return {"parsed": len(aps), "created": created, "updated": updated}
