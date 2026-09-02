"""业务-设备归属 & 系统域清单回归：矩阵汇总/归属维护(增删)/过滤联动/越权/系统汇总结构。
用法: python scripts/verify_bizsys.py [BASE]   （只读账号可用 NOPS_RO_USER 覆盖）
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010/api/v1")
TS = time.strftime("%m%d%H%M%S")
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


def call(method, path, tok=None, body=None, q=""):
    req = urllib.request.Request(BASE + path + (("?" + q) if q else ""), method=method)
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


def pk(x):
    return x if isinstance(x, int) else x.get("id")


s, sm = call("GET", "/cmdb/devices/business-summary/", admin)
check("B1 业务汇总结构", s == 200 and "businesses" in sm and "unassigned_devices" in sm
      and isinstance(sm.get("total_devices"), int), str(sm)[:150])
s, ss = call("GET", "/cmdb/devices/system-summary/", admin)
check("B2 系统汇总分区", s == 200 and {"morph", "model_cat", "vendor", "os", "usage"} <= set(ss),
      str(list(ss.keys())))
check("B3 morph 含物理/虚拟计数", any(m.get("label") == "物理机" for m in ss.get("morph", []))
      and sum(m.get("count", 0) for m in ss.get("morph", [])) == sm.get("total_devices"),
      str(ss.get("morph"))[:160])

# 建临时业务 + 选 2 台设备归属
s, b = call("POST", "/cmdb/businesses/", admin,
            {"name": f"回归业务-{TS[:6]}", "code": f"biztest{TS[:6]}", "importance": "normal"})
check("B4 建临时业务", s == 201 and b.get("id"), str(b)[:150])
bid = pk(b)
_, lst = call("GET", "/cmdb/devices/?page_size=2", admin)
dids = [d["id"] for d in lst["results"]]
s, r = call("POST", "/cmdb/devices/business-assign/", admin,
            {"business_id": bid, "device_ids": dids, "action": "add"})
check("B5 归属 add", s == 200 and r.get("changed") == len(dids), str(r)[:150])
s, r2 = call("GET", "/cmdb/devices/?business_id=" + str(bid), admin)
check("B6 business_id 过滤返回成员", s == 200 and len(r2.get("results", [])) == len(dids), str(s))
s, r3 = call("GET", "/cmdb/devices/business-summary/", admin)
hit = next((x for x in r3.get("businesses", []) if x["id"] == bid), None)
check("B7 汇总含新业务计数", hit is not None and hit["device_count"] == len(dids), str(r3)[:200])
s, r4 = call("POST", "/cmdb/devices/business-assign/", op,
             {"business_id": bid, "device_ids": dids[:1], "action": "remove"})
check("B8 只读归属维护 -> 403", s == 403, str(s))
s, r5 = call("POST", "/cmdb/devices/business-assign/", admin,
             {"business_id": bid, "device_ids": dids[:1], "action": "remove"})
check("B9 归属 remove", s == 200 and r5.get("changed") == 1, str(r5)[:120])
s, r6 = call("GET", "/cmdb/devices/?business_id=" + str(bid), admin)
check("B10 移除后余 1", len(r6.get("results", [])) == 1, str(len(r6.get("results", []))))
# 形态过滤与汇总一致性（取物理机过滤数 >= 汇总对应数）
s, vf = call("GET", "/cmdb/devices/?is_virtual=0&page_size=500", admin)
phys_sum = next((m["count"] for m in ss.get("morph", []) if not m.get("is_virtual")), 0)
check("B11 is_virtual 过滤与汇总一致", len(vf.get("results", [])) == phys_sum,
      f"list={len(vf.get('results', []))} sum={phys_sum}")
# 清理
call("DELETE", f"/cmdb/businesses/{bid}/", admin)
s, r7 = call("GET", "/cmdb/devices/business-summary/", admin)
check("B12 清理后无残留业务", all(x["id"] != bid for x in r7.get("businesses", [])), "")

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
