"""cmdb 周期任务：TechSnapshot 保留 + 链路质量取样。"""
from celery import shared_task

from apps.cmdb.retention import cleanup_techsnapshots


@shared_task(name="cmdb.cleanup_techsnapshots")
def cleanup_techsnapshots_task(keep=5):
    """清理过旧技术快照；每天 04:30 由 beat 触发（keep 可调）。"""
    return cleanup_techsnapshots(keep)


@shared_task(name="cmdb.sample_link_quality")
def sample_link_quality_task(keep_days=7):
    """链路质量取样（每 5 分钟）：DeviceInterfaceStat → LinkQualitySample + 老样本清理。"""
    from apps.cmdb.linkquality import sample_link_quality
    return sample_link_quality(keep_days)


@shared_task(name="cmdb.snmp_collect")
def snmp_collect_task():
    """SNMP 采集（beat 每 10 分钟）：遍历绑定 snmp 凭据的设备 → IF-MIB 接口状态/错误。"""
    from apps.cmdb.models import Device
    from apps.cmdb import snmp as snmp_mod
    from apps.system.models import Credential
    res = []
    ok = skipped = errors = 0
    for d in Device.objects.filter(deleted_at__isnull=True).exclude(manage_ip="") \
            .exclude(manage_ip__isnull=True).order_by("id"):
        cred = (Credential.objects.filter(pk=d.credential_id)
                .filter(cred_type__startswith="snmp").first() if d.credential_id else None)
        if not cred:
            skipped += 1
            continue
        if cred.cred_type != "snmp_v2c":
            skipped += 1
            continue  # v1/v3 后续
        try:
            r = snmp_mod.collect(d, mock=False, community=cred.secret,
                                 port=(cred.params or {}).get("port") or 161)
            ok += 1
            res.append({"device_id": d.pk, "name": d.name, **r})
        except Exception as e:  # noqa: BLE001 —— 单设备失败不拖垮全量
            errors += 1
            res.append({"device_id": d.pk, "name": d.name, "error": str(e)[:200]})
    return {"targets": ok + skipped, "ok": ok, "skipped": skipped, "errors": errors,
            "detail": res[:20]}


@shared_task(name="cmdb.prom_poll")
def prom_poll_task():
    """Prometheus 只读消费（beat 每 5 分钟）：NOPS_PROM_URL 未配置则跳过。
    拉取 PromQL → 关联 CMDB 设备 → 写 DeviceInterfaceStat（复用现有展示/取样）。"""
    import os
    base = (os.getenv("NOPS_PROM_URL") or "").strip()
    if not base:
        return {"skipped": True, "reason": "NOPS_PROM_URL 未配置（SNMP 直采为回退）"}
    from apps.cmdb import prometheus as prom_mod
    try:
        stats = prom_mod.poll_once(base, os.getenv("NOPS_PROM_TOKEN") or "")
        return {"skipped": False, **stats}
    except Exception as e:  # noqa: BLE001 —— 接入失败不拖垮 beat
        return {"skipped": False, "error": str(e)[:300]}
