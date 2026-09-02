"""机房作业工单回归：CRUD/越权/状态机(开工→完成/取消)/过滤/清理。
用法: python scripts/verify_dcimops.py [BASE]   （只读账号可用 NOPS_RO_USER 覆盖）
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


s, racks = call("GET", "/dcim/racks/?page_size=1", admin)
rack_id = pk(racks["results"][0]) if s == 200 and racks.get("results") else None
s, devs = call("GET", "/cmdb/devices/?page_size=1", admin)
dev = devs["results"][0] if devs.get("results") else None

s, r = call("POST", "/dcim/op-tickets/", op, {"kind": "rack_in", "title": "越权测试"})
check("D1 只读建单 -> 403", s == 403, str(s))
body = {"kind": "rack_in", "title": f"回归上架-{TS[:6]}", "rack": rack_id,
        "device_id": pk(dev) if dev else None,
        "device_name": dev["name"] if dev else "", "u_from": 20, "u_to": 22,
        "assignee": "机房A组", "note": "回归单"}
s, t = call("POST", "/dcim/op-tickets/", admin, body)
check("D2 建单", s == 201 and t.get("id") and t.get("kind") == "rack_in"
      and t.get("status") == "planned", str(t)[:200])
tid = t["id"]
s, lst = call("GET", "/dcim/op-tickets/?status=planned&kind=rack_in", admin)
check("D3 过滤查询含新单", any(x["id"] == tid for x in lst.get("results", [])), "")
s, r = call("POST", f"/dcim/op-tickets/{tid}/start/", admin)
check("D4 开工 -> doing", s == 200 and r.get("status") == "doing", str(r)[:100])
s, r = call("POST", f"/dcim/op-tickets/{tid}/start/", admin)
check("D5 重复开工 -> 400", s == 400, str(s))
s, r = call("POST", f"/dcim/op-tickets/{tid}/finish/", admin, {"result": "已完成上架，标签贴妥"})
check("D6 完成 -> done+结果", s == 200 and r.get("status") == "done" and r.get("finished_at"),
      str(r)[:150])
_, t = call("GET", f"/dcim/op-tickets/{tid}/", admin)
check("D7 结果落库", t.get("result") == "已完成上架，标签贴妥", str(t.get("result")))
s, r = call("POST", f"/dcim/op-tickets/{tid}/cancel/", admin, {"reason": "x"})
check("D8 已完成不可取消 -> 400", s == 400, str(s))
# 第二单：取消流程
s, t2 = call("POST", "/dcim/op-tickets/", admin,
             {**body, "title": f"回归取消-{TS[:6]}", "kind": "repair"})
tid2 = t2["id"]
s, r = call("POST", f"/dcim/op-tickets/{tid2}/cancel/", admin, {"reason": "现场已自行处理"})
check("D9 取消 -> cancelled", s == 200 and r.get("status") == "cancelled", str(r)[:100])
s, lst = call("GET", "/dcim/op-tickets/?status=cancelled", admin)
check("D10 cancelled 过滤可见", any(x["id"] == tid2 for x in lst.get("results", [])), "")
# PATCH 编辑标题
s, r = call("PATCH", f"/dcim/op-tickets/{tid2}/", admin, {"note": "已同步"})
check("D11 编辑工单", s == 200 and r.get("note") == "已同步", str(s))
# 清理
call("DELETE", f"/dcim/op-tickets/{tid}/", admin)
call("DELETE", f"/dcim/op-tickets/{tid2}/", admin)
s, lst = call("GET", "/dcim/op-tickets/?page_size=500", admin)
check("D12 清理后无残留", all(x["id"] not in (tid, tid2) for x in lst.get("results", [])), "")

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
