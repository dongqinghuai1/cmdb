"""Topology graph builder: nodes/edges merged from devices + LLDP + cable (ER D7).

Cross-app reads use raw SQL (bare-FK discipline; models not imported here)."""
from django.db import connection


def build_graph(region_id=None, site_id=None):
    where, params = ["d.deleted_at IS NULL", "d.is_virtual = FALSE"], []
    if site_id:
        where.append("d.site_id = %s")
        params.append(site_id)
    elif region_id:
        where.append("d.region_id = %s")
        params.append(region_id)
    cond = " AND ".join(where)

    nodes, node_ids = {}, set()
    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT d.id, d.name, d.online_status, d.vendor, m.code, d.site_id
            FROM cmdb_device d JOIN cmdb_cimodel m ON m.id = d.model_id
            WHERE {cond} ORDER BY d.id""", params)
        for did, name, online, vendor, model_code, site in cur.fetchall():
            nodes[did] = {"id": did, "label": name, "online": online, "vendor": vendor,
                          "model": model_code, "site_id": site, "managed": True}
            node_ids.add(did)

        # active alert severity per device (coloring)
        cur.execute("""
            SELECT device_id, MAX(CASE severity WHEN 'critical' THEN 3 WHEN 'major' THEN 2
                                                  WHEN 'warning' THEN 1 ELSE 0 END)
            FROM alert_alertevent
            WHERE status IN ('firing','acknowledged','processing')
            GROUP BY device_id""")
        sev = dict(cur.fetchall())
        for n in nodes.values():
            n["alert_severity"] = sev.get(n["id"], 0)

        edges, pseudo = [], {}
        # auto edges from LLDP neighbors
        cur.execute(f"""
            SELECT i.device_id, COALESCE(ln.remote_device_id, NULL),
                   ln.remote_hostname, ln.remote_port_desc, ln.source
            FROM topo_lldpneighbor ln
            JOIN cmdb_deviceinterface i ON i.id = ln.local_interface_id
            JOIN cmdb_device d ON d.id = i.device_id
            WHERE {cond}""", params)
        for a, b, hostname, port, src in cur.fetchall():
            if b is None:
                key = "host:" + (hostname or "unknown")
                if key not in pseudo:
                    pseudo[key] = {"id": key, "label": hostname or "未纳管设备", "online": "unknown",
                                   "vendor": "", "model": "unknown", "site_id": None,
                                   "managed": False, "alert_severity": 0}
                b = key
            if a == b:
                continue
            edges.append({"source": a, "target": b, "kind": "lldp",
                          "label": (port or "")[:12], "source_type": src})

        # manual cable edges (cable table ledger, no LLDP counterpart)
        cond_a = ["da.deleted_at IS NULL", "da.is_virtual = FALSE"]
        if site_id:
            cond_a.append("da.site_id = %s")
        elif region_id:
            cond_a.append("da.region_id = %s")
        cur.execute(f"""
            SELECT da.id, db2.id
            FROM dcim_cable c
            JOIN cmdb_deviceinterface ia ON ia.id = c.a_interface_id
            JOIN cmdb_device da ON da.id = ia.device_id
            LEFT JOIN cmdb_deviceinterface ib ON ib.id = c.b_interface_id
            LEFT JOIN cmdb_device db2 ON db2.id = ib.device_id
            WHERE c.deleted_at IS NULL AND db2.id IS NOT NULL
              AND {" AND ".join(cond_a)}
              AND NOT EXISTS (SELECT 1 FROM topo_lldpneighbor ln2
                              WHERE ln2.local_interface_id IN (c.a_interface_id, c.b_interface_id))
        """, params)
        for a, b in cur.fetchall():
            if a != b:
                edges.append({"source": a, "target": b, "kind": "cable", "label": "", "source_type": "manual"})

    all_nodes = list(nodes.values()) + list(pseudo.values())
    # dedup edges (a,b) vs (b,a)
    seen, dedup = set(), []
    for e in edges:
        key = tuple(sorted([str(e["source"]), str(e["target"])]))
        if key not in seen:
            seen.add(key)
            dedup.append(e)
    return {"nodes": all_nodes, "edges": dedup,
            "stats": {"devices": len(nodes), "unmanaged": len(pseudo), "links": len(dedup)}}


# ================= LLDP 拓扑自动发现（SNMP 只读探针） =================
# 走查驱动在 apps/cmdb/snmp.py::collect_lldp（LLDP-MIB, IEEE 802.1AB-2005）；
# 本层负责：候选设备范围（绑 snmp_v2c 凭据）→ 邻居行落 topo_lldpneighbor（含远端
# 设备回填）→ 失效清理。mock=True 走确定性织体（回归，不触网）。


def _snmp_candidates():
    """绑定了 snmp_v2c 凭据、有管理 IP 的启用设备（真实走查目标；与 cmdb.snmp_collect 同口径）。"""
    from apps.cmdb.models import Device
    from apps.system.models import Credential
    devs = list(Device.objects.filter(deleted_at__isnull=True)
                .exclude(manage_ip=None).exclude(credential_id=None)
                .exclude(collect_enabled=False)
                .order_by("id").values("id", "name", "manage_ip", "credential_id"))
    cred_ids = {d["credential_id"] for d in devs}
    creds = {c.id: c for c in Credential.objects.filter(id__in=cred_ids, cred_type="snmp_v2c")}
    out = []
    for d in devs:
        c = creds.get(d["credential_id"])
        if c:
            out.append({**d, "community": c.secret,
                        "port": int((c.params or {}).get("port") or 161)})
    return out


def _norm_mac(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _build_maps():
    """CMDB 索引：名称(hostname)/接口 MAC/管理 IP → device id（LLDP 远端匹配用）。"""
    from apps.cmdb.models import Device, DeviceInterface
    devs = list(Device.objects.filter(deleted_at__isnull=True)
                .values("id", "name", "hostname", "manage_ip"))
    name_map, ip_map = {}, {}
    for d in devs:
        for key in (d.get("name"), d.get("hostname")):
            if key:
                name_map[key.strip().lower()] = d["id"]
        if d.get("manage_ip"):
            ip_map[d["manage_ip"].strip()] = d["id"]
    mac_map = {}
    for iface in DeviceInterface.objects.exclude(mac="").values("device_id", "mac"):
        m = _norm_mac(iface["mac"])
        if m:
            mac_map.setdefault(m, iface["device_id"])
    return {"name": name_map, "mac": mac_map, "ip": ip_map}


def _resolve_remote(row, maps):
    """LLDP 远端 → CMDB 设备：优先 sysName 精确匹配 name/hostname；chassisId
    subtype=4(macAddress) 匹配任一接口 MAC；subtype=5(networkAddress/IPv4) 匹配管理 IP。"""
    sysn = (row.get("sys_name") or "").strip().lower()
    if sysn:
        pid = maps["name"].get(sysn)
        if pid:
            return pid
    if str(row.get("chassis_id_subtype")) == "4":           # macAddress
        m = _norm_mac(row.get("chassis_id"))
        if m:
            pid = maps["mac"].get(m)
            if pid:
                return pid
    if str(row.get("chassis_id_subtype")) == "5":           # networkAddress
        raw = row.get("chassis_id") or ""
        # 编码 = 1 字节 AF(1=IPv4) + 4 字节地址；本驱动以字节裸流保存时按 '\\x01' 前缀识别
        if raw.startswith("\x01") and len(raw) == 5:
            pid = maps["ip"].get(".".join(str(b) for b in raw[1:].encode("latin1")))
            if pid:
                return pid
    return None


def _sync_device_neighbors(device_id, parsed, maps):
    """parsed: {'local': {port: {...}}, 'remote': {(local_port, rem_idx): {...}}}
    → upsert topo_lldpneighbor + 90 分钟未再见的邻居行清理。"""
    from datetime import timedelta
    from django.utils import timezone
    from apps.cmdb.models import DeviceInterface
    from apps.topo.models import LldpNeighbor
    ifaces = list(DeviceInterface.objects.filter(device_id=device_id)
                  .order_by("if_index").values("id", "if_index", "name"))
    by_index = {i["if_index"]: i for i in ifaces if i["if_index"] is not None}
    by_name = {i["name"].lower(): i for i in ifaces}
    local_desc = parsed.get("local") or {}
    touched, skipped_local = set(), 0
    for (port, _ridx), row in (parsed.get("remote") or {}).items():
        li = by_index.get(port)
        if li is None:                       # 交换机 lldpPortNum ≠ ifIndex：用本地表描述兜底
            cand = (local_desc.get(port) or {}).get("port_id", "") or \
                   (local_desc.get(port) or {}).get("port_desc", "")
            li = by_name.get(cand.strip().lower())
        if li is None:
            skipped_local += 1
            continue
        LldpNeighbor.objects.update_or_create(
            local_interface_id=li["id"],
            remote_chassis_id=(row.get("chassis_id") or "")[:128],
            remote_port_id=(row.get("port_id") or "")[:128],
            defaults={"source": "lldp",
                      "remote_hostname": (row.get("sys_name") or "")[:128],
                      "remote_port_desc": (row.get("port_desc") or "")[:128],
                      "remote_device_id": _resolve_remote(row, maps)})
        touched.add(li["id"])
    cutoff = timezone.now() - timedelta(minutes=90)      # LLDP TTL ~120s，3 周期未现视为失效
    stale = LldpNeighbor.objects.filter(local_interface_id__in=[i["id"] for i in ifaces]) \
        .exclude(local_interface_id__in=touched).filter(last_seen_at__lt=cutoff)
    dead = stale.delete()[0]
    return {"rows": len(parsed.get("remote") or {}), "applied": len(touched),
            "skipped_local": skipped_local, "stale_deleted": dead}


def _mock_parsed_for(device_id, candidates, maps):
    """回归用确定性 LLDP 织体：与同环境另一台 snmp 设备按接口序两两互联（前 2 对）。
    不触网；与 _snmp_candidates 同序保证幂等。"""
    from apps.cmdb.models import DeviceInterface
    peers = [c for c in candidates if c["id"] != device_id]
    if not peers:
        return {"local": {}, "remote": {}}
    peer = peers[0]
    mine = list(DeviceInterface.objects.filter(device_id=device_id).order_by("if_index"))
    theirs = list(DeviceInterface.objects.filter(device_id=peer["id"]).order_by("if_index"))
    local, remote = {}, {}
    for i in range(min(len(mine), len(theirs), 2)):
        mi, ti = mine[i], theirs[i]
        port = mi.if_index or (i + 1)
        local[port] = {"port_id": mi.name, "port_desc": mi.name}
        remote[(port, i + 1)] = {
            "chassis_id_subtype": 4,
            "chassis_id": f"02:00:00:00:{peer['id']:02x}:{(i + 1):02x}",
            "port_id_subtype": 5, "port_id": ti.name, "port_desc": ti.name,
            "sys_name": peer["name"],
        }
    return {"local": local, "remote": remote}


def discover_lldp(mock=False):
    """LLDP 拓扑自动发现（beat 周期 / 手动触发）：
    SNMPv2c 只读走查 LLDP-MIB → topo_lldpneighbor；单设备失败不拖垮全量。
    mock=True 仅对 TEST-NET 段(198.51.100.0/24) 设备建确定性织体（回归专用，不触网、
    不受环境残留设备干扰）。"""
    candidates = _snmp_candidates()
    if mock:
        candidates = [c for c in candidates
                      if (c.get("manage_ip") or "").startswith("198.51.100.")]
    if not candidates:
        note = ("无绑定 snmp_v2c 凭据的设备（拓扑自动发现无目标，跳过）"
                if not mock else "mock 织体无 TEST-NET(198.51.100.x) 目标设备")
        return {"targets": 0, "ok": 0, "errors": 0, "detail": [], "note": note,
                "mock": bool(mock)}
    maps = _build_maps()
    res, ok, errors = [], 0, 0
    for c in candidates:
        try:
            if mock:
                parsed = _mock_parsed_for(c["id"], candidates, maps)
            else:
                from apps.cmdb import snmp as snmp_mod
                parsed = snmp_mod.collect_lldp(c["manage_ip"], c["community"],
                                               port=c["port"])
            s = _sync_device_neighbors(c["id"], parsed, maps)
            ok += 1
            res.append({"device_id": c["id"], "name": c["name"], **s})
        except Exception as e:  # noqa: BLE001 —— 单设备失败不拖垮
            errors += 1
            res.append({"device_id": c["id"], "name": c["name"], "error": str(e)[:200]})
    return {"targets": len(candidates), "ok": ok, "errors": errors, "detail": res[:20],
            "mock": bool(mock)}
