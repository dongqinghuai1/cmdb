"""SNMP collector skeleton (PRD 5.6 / ER D6/D7/D10).
Driver registry + standard IF-MIB set; writes snapshots to PG and metrics to VM."""
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
except Exception:  # pysnmp missing -> engine degrades gracefully
    HAS_PYSNMP = False

# ---- standard IF-MIB OIDs (V1.1 ER D7: driver registry) ----
BASE_OID = {
    "sysDescr": "1.3.6.1.2.1.1.1.0",
    "sysName": "1.3.6.1.2.1.1.5.0",
    "ifDescr": "1.3.6.1.2.1.31.1.1.1.1",
    "ifOperStatus": "1.3.6.1.2.1.2.2.1.8",
    "ifHCInOctets": "1.3.6.1.2.1.31.1.1.1.6",
    "ifHCOutOctets": "1.3.6.1.2.1.31.1.1.1.10",
    "ifInErrors": "1.3.6.1.2.1.2.2.1.14",
    "ifOutErrors": "1.3.6.1.2.1.2.2.1.20",
}
DRIVERS = {"snmp_std": []}  # h3c_comware/fortigate/cisco_wlc_* 等私有 OID 集合后续注册


def register_driver(name, extra_oids=None):
    def deco(fn):
        DRIVERS[name] = fn
        return fn
    return deco


def snmp_walk(host, community, oid):
    """Generator: yields (suffix, value)."""
    if not HAS_PYSNMP:
        return
    for err, _, _, varbinds in nextCmd(
            SnmpEngine(), CommunityData(community, mpModel=0),
            UdpTransportTarget((host, 161), timeout=3, retries=1),
            ContextData(), ObjectType(ObjectIdentity(oid)), lexicographicMode=False):
        if err:
            return
        for vb in varbinds:
            yield str(vb[0]).rsplit(".", 1)[-1], vb[1]


def collect_device(device_row):
    """device_row: dict with id/manage_ip/attrs(_snmp_community)/driver_type."""
    host = device_row["manage_ip"]
    community = (device_row.get("attrs") or {}).get("_snmp_community", "public")
    metrics = []
    for oid_name in ("ifHCInOctets", "ifHCOutOctets", "ifInErrors", "ifOutErrors"):
        for suffix, val in snmp_walk(host, community, BASE_OID[oid_name]):
            metrics.append((f"if_{oid_name[2:].lower()}", suffix, int(val)))
    return metrics


def push_to_vm(device_id, driver_type, metrics):
    """ER D10 unified labels: device_id / if_name / driver_type."""
    lines = []
    for name, if_suffix, val in metrics:
        lines.append(f'{name}{{device_id="{device_id}",if_index="{if_suffix}",'
                     f'driver_type="{driver_type}"}} {val}')
    if lines:
        try:
            requests.post(f"{settings.VICTORIAMETRICS_URL}/api/v1/import/prometheus",
                          data="\n".join(lines) + "\n", timeout=10)
        except Exception:
            logger.exception("VM push failed device=%s", device_id)


@shared_task(name="monitor.collect_shard")
def collect_shard(collector_node_id):
    """Shard collection: upsert device.online_status + interface snapshots (ER D6)."""
    from django.db import connection
    from apps.monitor.models import CollectorNode
    node = CollectorNode.objects.filter(pk=collector_node_id).first()
    if not node:
        return
    with connection.cursor() as cur:
        cur.execute("""SELECT id, manage_ip, driver_type, attrs FROM cmdb_device
                       WHERE collector_id=%s AND collect_enabled AND deleted_at IS NULL""",
                    [collector_node_id])
        rows = [dict(zip(("id", "manage_ip", "driver_type", "attrs"), r)) for r in cur.fetchall()]
    ok = 0
    for row in rows:
        try:
            metrics = collect_device(row)
            push_to_vm(row["id"], row["driver_type"] or "snmp_std", metrics)
            with connection.cursor() as cur:
                cur.execute("UPDATE cmdb_device SET online_status='online', last_seen_at=%s WHERE id=%s",
                            [timezone.now(), row["id"]])
            ok += 1
        except Exception:
            logger.exception("collect failed device=%s", row["id"])
    node.current_load = len(rows)
    node.last_heartbeat_at = timezone.now()
    node.save(update_fields=["current_load", "last_heartbeat_at", "updated_at"])
    return {"collected": ok, "total": len(rows)}
