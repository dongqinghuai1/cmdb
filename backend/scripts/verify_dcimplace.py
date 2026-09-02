"""机房作业落位联动回归：上架落位/冲突 400(工单不完成)/下架清位/设备位置断言。
用法: python scripts/verify_dcimplace.py [BASE]
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
    raise SystemExit(f"login fail {u}")


admin = login("admin", "nops@2025")
mgr = login(os.environ.get("NOPS_MGR", "mgr_approver"), "NopsTest@2025")


def pk(x):
    return x if isinstance(x, int) else x.get("id")


_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]
s, td = call("POST", "/cmdb/devices/", admin, {
    "name": f"落位测试-{TS[:6]}", "vendor": "V",
    "model": pk(base["model"]), "site": pk(base["site"]), "region": pk(base["region"]),
    "rack": None, "rack_start_u": None})
check("P0 造临时设备", s == 201, str(td)[:100])
tid = td["id"]

# 目标机柜（取第一台 u_total 够大的；无则自建 区域→站点→临时机柜 链）
def ensure_region_site():
    s, rr = call("GET", "/dcim/regions/?page_size=1", admin)
    if not rr.get("results"):
        s, region = call("POST", "/dcim/regions/", admin,
                         {"name": f"落位回归区-{TS[:6]}", "code": f"reg{TS[:6]}"})
        region = region or {}
    else:
        region = rr["results"][0]
    s, ss = call("GET", "/dcim/sites/?page_size=1", admin)
    if not ss.get("results"):
        s, site = call("POST", "/dcim/sites/", admin,
                       {"name": f"落位回归站-{TS[:6]}", "code": f"st{TS[:6]}",
                        "region": pk(region)})
        site = site or {}
    else:
        site = ss["results"][0]
    return pk(region), pk(site)


_, site_id = ensure_region_site()
s, racks = call("GET", "/dcim/racks/?page_size=10", admin)
rack = next((r for r in racks.get("results", []) if (r.get("u_total") or 0) >= 10), None)
if rack is None:
    s, rack = call("POST", "/dcim/racks/", admin, {
        "name": f"落位回归柜-{TS[:6]}", "site": site_id, "u_total": 42})
check("P1 有可用机柜(>=10U)", rack is not None and (rack.get("u_total") or 0) >= 10, str(rack)[:120])
rid = pk(rack)

s, t1 = call("POST", "/dcim/op-tickets/", mgr, {
    "kind": "rack_in", "title": f"落位上架-{TS[:6]}", "rack": rid,
    "device_id": tid, "device_name": td["name"], "u_from": 1, "u_to": 2, "note": "联动回归"})
tid1 = t1["id"]
s, r = call("POST", f"/dcim/op-tickets/{tid1}/start/", mgr)
check("P2 开工", s == 200, str(s))
s, r = call("POST", f"/dcim/op-tickets/{tid1}/finish/", mgr, {"result": "ok"})
p = r.get("placement") or {}
check("P3 完成并落位 U1-2", s == 200 and r.get("status") == "done"
      and p.get("rack_id") == rid and p.get("rack_start_u") == 1 and p.get("units") == 2, str(r)[:200])
_, dev = call("GET", f"/cmdb/devices/{tid}/", admin)
check("P4 设备已占位", dev.get("rack") == rid and dev.get("rack_start_u") == 1
      and dev.get("rack_units") == 2, str(dev)[:160])

# 冲突：同 U 区再上架第二台设备 → 400 且工单保持 doing
s, td2 = call("POST", "/cmdb/devices/", admin, {
    "name": f"落位冲突-{TS[:6]}", "vendor": "V",
    "model": pk(base["model"]), "site": pk(base["site"]), "region": pk(base["region"])})
tid2 = td2["id"]
s, t2 = call("POST", "/dcim/op-tickets/", mgr, {
    "kind": "rack_in", "title": f"冲突上架-{TS[:6]}", "rack": rid,
    "device_id": tid2, "device_name": td2["name"], "u_from": 1, "u_to": 2})
tid2t = t2["id"]
call("POST", f"/dcim/op-tickets/{tid2t}/start/", mgr)
s, r = call("POST", f"/dcim/op-tickets/{tid2t}/finish/", mgr, {"result": "x"})
check("P5 冲突上架 -> 400 提示", s == 400 and ("冲突" in r.get("detail", "") or "U" in r.get("detail", "")),
      str(r)[:160])
_, t2s = call("GET", f"/dcim/op-tickets/{tid2t}/", admin)
check("P6 冲突时工单未完成", t2s.get("status") == "doing", t2s.get("status"))
_, dev2 = call("GET", f"/cmdb/devices/{tid2}/", admin)
check("P7 冲突设备未占位", dev2.get("rack") in (None, ""), str(dev2.get("rack")))
# 调整到空 U 区(10U 柜 U5-6)后可完成（工单仍在 doing，直接改 U 再完成）
s, r = call("PATCH", f"/dcim/op-tickets/{tid2t}/", mgr,
            {"kind": "rack_in", "u_from": 5, "u_to": 6})
check("P7b 调整目标 U 成功", s == 200 and r.get("u_from") == 5, str(r)[:120])
s, r = call("POST", f"/dcim/op-tickets/{tid2t}/finish/", mgr, {"result": "ok"})
check("P8 改 U5-6 完成落位", s == 200 and (r.get("placement") or {}).get("rack_start_u") == 5, str(r)[:160])
# 下架清位
s, t3 = call("POST", "/dcim/op-tickets/", mgr, {
    "kind": "rack_out", "title": f"下架-{TS[:6]}", "device_id": tid2,
    "device_name": dev2["name"], "note": "联动回归"})
tid3 = t3["id"]
call("POST", f"/dcim/op-tickets/{tid3}/start/", mgr)
s, r = call("POST", f"/dcim/op-tickets/{tid3}/finish/", mgr, {"result": "移出库房"})
check("P9 下架完成清位", s == 200 and (r.get("placement") or {}).get("rack_id") is None, str(r)[:160])
_, dev2b = call("GET", f"/cmdb/devices/{tid2}/", admin)
check("P10 设备机柜已清空", dev2b.get("rack") in (None, "") and dev2b.get("rack_start_u") in (None, ""),
      str(dev2b)[:140])
# 清理
for t in (tid1, tid2t, tid3):
    call("DELETE", f"/dcim/op-tickets/{t}/", admin)
call("DELETE", f"/cmdb/devices/{tid}/", admin)
call("DELETE", f"/cmdb/devices/{tid2}/", admin)

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
