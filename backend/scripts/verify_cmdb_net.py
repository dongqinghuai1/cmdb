"""网络总览汇总端点回归：分区结构/类型/区域过滤/只读可读/扩展位（空数据也须返回完整分区）。
用法: python scripts/verify_cmdb_net.py [BASE]   （只读账号可用 NOPS_RO_USER 覆盖）
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010/api/v1")
PASS = 0
FAIL = 0


def check(name, ok, extra=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"PASS {name}")
    else:
        FAIL += 1
        print(f"FAIL {name} | {extra}")


def call(method, path, tok=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=25) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def login(u, p):
    for _ in range(8):
        s, r = call("POST", "/auth/login/", body={"username": u, "password": p})
        if s == 200:
            return r["access"]
        if s == 429:
            time.sleep(6)
            continue
        break
    raise SystemExit(f"login fail {u}: {s} {r}")


admin = login("admin", "nops@2025")
ro_user = os.environ.get("NOPS_RO_USER", "op_low")
op = login(ro_user, "NopsTest@2025")

s, d = call("GET", "/cmdb/devices/network-overview/", admin)
check("N1 汇总端点 200", s == 200, str(s))
sections = ("generated_at", "meta", "neighbors", "routes", "links", "ap", "vlans", "extensions")
check("N2 分区齐全", all(k in d for k in sections), str(list(d.keys())))
m = d.get("meta", {})
check("N3 meta 含覆盖设备数(≥0)", isinstance(m.get("devices_covered"), int) and m.get("devices_covered") >= 0,
      str(m))
n = d.get("neighbors", {})
check("N4 邻居 rows 列表+by_state dict", isinstance(n.get("rows"), list) and isinstance(n.get("by_state"), dict)
      and (not n["rows"] or set(n["rows"][0]) >= {"device_id", "name", "protocol", "neighbor_addr", "state"}),
      str(list(n.keys())))
r = d.get("routes", {})
check("N5 路由 total_prefixes≥0 且 rows 每行含 count", isinstance(r.get("total_prefixes"), int)
      and r.get("total_prefixes") >= 0 and (not r.get("rows")
      or set(r["rows"][0]) >= {"device_id", "name", "count", "snapshot_at"}), str(r)[:150])
l = d.get("links", {})
check("N6 链路 summary{checked,down,high_error}", isinstance(l.get("summary"), dict)
      and "down" in l.get("summary", {}) and "high_error" in l.get("summary", {}), str(l.get("summary")))
ap = d.get("ap", {})
check("N7 AP rows 列表", isinstance(ap.get("rows"), list)
      and (not ap["rows"] or set(ap["rows"][0]) >= {"device_id", "name", "ap_name", "status"}), "")
ex = d.get("extensions", [])
check("N8 扩展位4项含 nat/acl/quality_history/wireless_deep",
      isinstance(ex, list) and {e.get("key") for e in ex} >=
      {"nat", "acl", "quality_history", "wireless_deep"}, str(ex)[:200])
vl = d.get("vlans", {})
check("N9 VLAN rows 每行 vlan/count", isinstance(vl.get("rows"), list)
      and (not vl["rows"] or set(vl["rows"][0]) >= {"vlan", "count"}), "")
s2, _ = call("GET", "/cmdb/devices/network-overview/", op)
check("N10 只读可读", s2 == 200, str(s2))
_, devs = call("GET", "/cmdb/devices/?page_size=1", admin)
bid = devs["results"][0]["id"]
s3, d3 = call("GET", f"/cmdb/devices/network-overview/?region_id=-1&site_id=-1", admin)
check("N11 空过滤(不存在区域)仍 200 且覆盖=0", s3 == 200
      and d3.get("meta", {}).get("devices_covered") == 0, str(d3.get("meta")))

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
