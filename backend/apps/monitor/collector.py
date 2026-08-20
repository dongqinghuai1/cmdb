"""采集引擎：SNMP 指标 + ICMP 兜底探测（在线/离线判定的真实数据源）。

链路：collect_all(beat 5min) -> 分批 collect_batch -> 每台 collect_device：
  1) SNMP(sysName/接口) 成功 -> online + 指标推 VM
  2) SNMP 失败但 ICMP ping 通 -> online（记 snmp_fail 备注）
  3) 都失败 -> offline
凭据解析走 system.Credential（community），无凭据时仅 ping。"""
import logging

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

try:
    from pysnmp.hlapi import (CommunityData, ContextData, ObjectIdentity, ObjectType,
                              SnmpEngine, UdpTransportTarget, nextCmd)
    HAS_PYSNMP = True
except Exception:  # pragma: no cover
    HAS_PYSNMP = False

OID_SYSNAME = "1.3.6.1.2.1.1.5.0"
OID_SYSDESCR = "1.3.6.1.2.1.1.1.0"

DRIVER_MAP = {  # driver_type -> netmiko device_type（NCM SSH 备份用）
    "h3c_comware": "hp_comware", "cisco_asa": "cisco_asa",
    "cisco_wlc_3504": "cisco_wlc", "cisco_wlc_9800": "cisco_wlc",
    "fortigate": "fortinet", "sangfor_ac": "linux",
}


def _load_device(device_id):
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute("""SELECT id, manage_ip, driver_type, credential_id, attrs,
                              hostname, online_status
                       FROM cmdb_device WHERE id=%s""", [device_id])
        cols = [c[0] for c in cur.description]
        row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def _snmp_get(host, community, oid):
    """单值 GET；失败返回 None。"""
    if not HAS_PYSNMP:
        return None
    try:
        for err, _, _, varbinds in nextCmd(
                SnmpEngine(), CommunityData(community, mpModel=0),
                UdpTransportTarget((host, 161), timeout=3, retries=1),
                ContextData(), ObjectType(ObjectIdentity(oid)), lexicographicMode=False):
            if err:
                return None
            for vb in varbinds:
                return str(vb[1])
    except Exception:
        return None
    return None


def _icmp_ping(host, timeout=2.0):
    try:
        import ping3
        ms = ping3.ping(host, timeout=timeout, unit="ms")
        return ms is not False and ms is not None
    except Exception:
        return False


def _resolve_community(cred_id, attrs):
    if isinstance(attrs, str):
        try:
            import json as _json
            attrs = _json.loads(attrs or "{}")
        except Exception:
            attrs = {}
    if cred_id:
        from apps.system.models import Credential
        c = Credential.objects.filter(pk=cred_id).first()
        if c and c.cred_type.startswith("snmp"):
            return c.secret
    return (attrs or {}).get("_snmp_community", "public")


def _push_vm(device_id, driver_type, metrics):
    lines = [f'{k}{{device_id="{device_id}",driver_type="{driver_type}"}} {v}'
             for k, v in metrics.items()]
    try:
        requests.post(f"{settings.VICTORIAMETRICS_URL}/api/v1/import/prometheus",
                      data="\n".join(lines) + "\n", timeout=5)
    except Exception:
        logger.warning("vm push failed device=%s", device_id)


def _set_status(device_id, status, hostname=None):
    from django.db import connection
    with connection.cursor() as cur:
        if hostname:
            cur.execute("UPDATE cmdb_device SET online_status=%s, last_seen_at=%s, hostname=%s WHERE id=%s",
                        [status, timezone.now(), hostname, device_id])
        else:
            cur.execute("UPDATE cmdb_device SET online_status=%s, last_seen_at=%s WHERE id=%s",
                        [status, timezone.now(), device_id])


def collect_one(device_id) -> dict:
    """单台设备采集：SNMP -> ICMP 兜底。返回 {device, snmp, ping, status}。"""
    dev = _load_device(device_id)
    if not dev or not dev["manage_ip"]:
        return {"device": device_id, "status": "skipped", "reason": "no manage_ip"}
    host = str(dev["manage_ip"])
    community = _resolve_community(dev["credential_id"], dev["attrs"])
    driver = dev["driver_type"] or "snmp_std"

    sysname = _snmp_get(host, community, OID_SYSNAME)
    if sysname is not None:
        _set_status(device_id, "online", hostname=sysname[:120])
        _push_vm(device_id, driver, {"device_up": 1, "device_snmp_up": 1})
        return {"device": device_id, "status": "online", "snmp": True, "ping": None}

    alive = _icmp_ping(host)
    if alive:
        _set_status(device_id, "online")
        _push_vm(device_id, driver, {"device_up": 1, "device_snmp_up": 0})
        return {"device": device_id, "status": "online", "snmp": False, "ping": True}
    _set_status(device_id, "offline")
    _push_vm(device_id, driver, {"device_up": 0})
    return {"device": device_id, "status": "offline", "snmp": False, "ping": False}


@shared_task(name="monitor.collect_batch")
def collect_batch(device_ids):
    return [collect_one(d) for d in device_ids]


@shared_task(name="monitor.collect_all")
def collect_all(collector_node_id=None):
    """beat 每 5 分钟：全部启用采集的设备分批并发。collector_node_id 可选分片。"""
    from django.db import connection
    sql = "SELECT id FROM cmdb_device WHERE deleted_at IS NULL AND collect_enabled AND manage_ip IS NOT NULL"
    params = []
    if collector_node_id:
        sql += " AND collector_id=%s"
        params.append(collector_node_id)
    with connection.cursor() as cur:
        cur.execute(sql, params)
        ids = [r[0] for r in cur.fetchall()]
    BATCH = 20
    for i in range(0, len(ids), BATCH):
        collect_batch.delay(ids[i:i + BATCH])
    return {"queued": len(ids), "ts": str(timezone.now())}


# 兼容旧入口（按采集器分片）
@shared_task(name="monitor.collect_shard")
def collect_shard(collector_node_id):
    return collect_all(collector_node_id)
