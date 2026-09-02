"""dcim 电源服务：PDU/UPS 实测样本的采集适配与汇总。

采集路径严格复用既有架构（不另起采集器）：
- Prometheus 主通道：apps.cmdb.prometheus.query_once 只读 PromQL（NOPS_PROM_URL / NOPS_PROM_POWER_QUERIES）；
- SNMP 通道：apps.cmdb.snmp.collect_pdu（厂商模板未校准前 mock 演练 + 待校准计数）；
- 手工/演示：dcim 视图 mock 轮询写样例。
额定功率读 cmdb.Device.rated_power_w（样本落库时快照）。
"""
import logging
import os

from django.db.models import Count, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)

POWER_MODEL_CODES = ("pdu", "ups")  # cmdb.CiModel.code，init_nops_data 预置


def target_devices(device_ids=None):
    """facility 供电设备：model.code in (pdu, ups)。可选按 id 收窄。"""
    from apps.cmdb.models import Device
    qs = Device.objects.filter(deleted_at__isnull=True, model__code__in=POWER_MODEL_CODES)
    if device_ids:
        qs = qs.filter(id__in=[int(i) for i in device_ids])
    return list(qs)


def apply_sample(device_id, outlet="", watts=None, current_a=None, voltage_v=None,
                 source="prom", sampled_at=None, rated_watts=None):
    """写一条实测样本；utilization = watts / rated（rated 缺省读设备额定快照）。"""
    from apps.dcim.models import PowerSample
    device_id = int(device_id)
    if rated_watts is None:
        from apps.cmdb.models import Device
        dev = Device.objects.filter(pk=device_id, deleted_at__isnull=True).first()
        if not dev:
            return None
        rated_watts = dev.rated_power_w
    pct = None
    if watts is not None and rated_watts:
        pct = round(100.0 * watts / rated_watts, 1)
    s = PowerSample.objects.create(
        device_id=device_id, outlet=(outlet or ""),
        watts=watts, current_a=current_a, voltage_v=voltage_v,
        utilization_pct=pct, rated_watts=rated_watts,
        source=source, sampled_at=sampled_at or timezone.now())
    return {"sample_id": s.pk, "device_id": device_id, "outlet": s.outlet,
            "watts": s.watts, "utilization_pct": pct}


def _purge_old(device_id, keep_days=30):
    """按设备清理过旧样本（防止长跑膨胀）。"""
    from apps.dcim.models import PowerSample
    cutoff = timezone.now() - timezone.timedelta(days=keep_days)
    return PowerSample.objects.filter(device_id=device_id,
                                      sampled_at__lt=cutoff).delete()[0]


def poll_prom():
    """Prometheus 只读消费（主通道）。NOPS_PROM_URL 未配置 → skipped。"""
    base = (os.getenv("NOPS_PROM_URL") or "").strip()
    if not base:
        return {"skipped": True, "reason": "NOPS_PROM_URL 未配置（SNMP mock/手工为回退）"}
    from apps.cmdb import prometheus as prom_mod
    raw = (os.getenv("NOPS_PROM_POWER_QUERIES") or "").strip()
    queries = []
    if raw:
        try:
            queries = __import__("json").loads(raw)
        except Exception:  # noqa: BLE001
            queries = []
    if not queries:
        return {"skipped": True, "reason": "NOPS_PROM_POWER_QUERIES 未配置（格式见 HANDOVER）"}
    devices = target_devices()
    ip_map = {d.manage_ip.strip(): d.id for d in devices if d.manage_ip}
    name_map = {d.name.strip(): d.id for d in devices}
    applied, unmatched = [], 0
    for cfg in queries:
        labels_out = cfg.get("outlet_label") or ""
        for labels, val in prom_mod.query_once(base, os.getenv("NOPS_PROM_TOKEN") or "",
                                               cfg.get("promql")):
            src = labels.get(cfg.get("device_label", "device"))
            pid = None
            if src:
                if cfg.get("device_field") == "manage_ip":
                    pid = ip_map.get(str(src).split(":")[0])
                else:
                    pid = name_map.get(str(src))
            if not pid:
                unmatched += 1
                continue
            r = apply_sample(pid, outlet=(labels.get(labels_out, "") if labels_out else ""),
                             watts=float(val),
                             source="prom",
                             current_a=cfg.get("current_from_promql") and _query_aux(
                                 base, os.getenv("NOPS_PROM_TOKEN") or "", labels, cfg) or None)
            applied.append(r)
            _purge_old(pid)
    return {"skipped": False, "queries": len(queries), "applied": len(applied),
            "unmatched": unmatched}


def _query_aux(base, token, labels, cfg):
    """读取同 series 的电流（volt 模板缺省 None；保留扩展位）。"""
    return None


def poll_snmp(device_ids=None, mock=False):
    """SNMP 通道：遍历 pdu/ups 设备（绑定 snmp_v2c 凭据）。mock=1 演练写样例；
    真实模式模板未校准 → 计待校准跳过。"""
    from apps.system.models import Credential
    applied, skipped, calibration = [], 0, 0
    for d in target_devices(device_ids):
        cred = (Credential.objects.filter(pk=d.credential_id)
                .filter(cred_type="snmp_v2c").first() if d.credential_id else None)
        host = d.manage_ip or "127.0.0.1"
        if (not mock) and (not cred or not d.manage_ip):
            skipped += 1
            continue
        try:
            from apps.cmdb import snmp as snmp_mod
            r = snmp_mod.collect_pdu(host, (cred.secret if cred else "public"),
                                     mock=mock,
                                     port=((cred.params or {}).get("port") or 161) if cred else 161)
            for o in r.get("outlets", []):
                applied.append(apply_sample(
                    d.pk, outlet=o.get("outlet", ""),
                    watts=o.get("watts"), current_a=o.get("current_a"),
                    voltage_v=o.get("voltage_v"), source="snmp"))
            _purge_old(d.pk)
        except Exception as e:  # noqa: BLE001
            calibration += 1  # RequiresCalibration（模板待校准）或网络失败均跳过单台
            logger.warning("pdu snmp skip dev=%s err=%s", d.pk, str(e)[:160])
    return {"applied": len(applied), "skipped": skipped, "calibration": calibration,
            "detail": applied[:20]}


def latest_summary():
    """每台供电设备最近样本汇总 + 总用电 + 超阈值(≥80%)提醒。"""
    from apps.dcim.models import PowerSample
    ids = [d.id for d in target_devices()]
    rows = {}
    for s in PowerSample.objects.filter(device_id__in=ids).order_by(
            "device_id", "-sampled_at", "-id"):
        rows.setdefault(s.device_id, s)
    devices = target_devices()
    dev_map = {d.id: d for d in devices}
    items, total_watts, over = [], 0.0, 0
    for did in sorted(rows):
        s = rows[did]
        dev = dev_map.get(did)
        total_watts += s.watts or 0
        over_flag = (s.utilization_pct or 0) >= 80
        over += int(over_flag)
        items.append({"device_id": did, "device": dev.name if dev else "-",
                      "vendor": dev.vendor if dev else "", "rated_watts": dev.rated_power_w if dev else None,
                      "watts": s.watts, "current_a": s.current_a, "voltage_v": s.voltage_v,
                      "utilization_pct": s.utilization_pct, "outlet": s.outlet,
                      "sampled_at": s.sampled_at.isoformat(), "source": s.source,
                      "over_threshold": over_flag})
    samples_total = PowerSample.objects.filter(device_id__in=ids).count()
    return {"devices": len(items), "sampled_rows": samples_total,
            "total_watts": round(total_watts, 1), "over_threshold": over,
            "items": items}
