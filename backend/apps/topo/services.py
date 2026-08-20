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
