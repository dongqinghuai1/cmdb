"""借还台账（占用/释放联动）回归：借出前置校验/占用标记/台账可见/重复与提前归还 400/归还释放/逾期与历史借出。
用法: python scripts/verify_loans.py [BASE]   （只读账号可用 NOPS_RO_USER 覆盖）
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

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


_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]
s, td = call("POST", "/cmdb/devices/", admin, {
    "name": f"借还测试-{TS[:6]}", "vendor": "V",
    "model": pk(base["model"]), "site": pk(base["site"]), "region": pk(base["region"]),
    "manage_ip": "10.200.201.1"})
check("L0 造临时设备", s == 201 and td.get("usage_status") == "idle", str(td)[:120])
tid = td["id"]

s, r = call("POST", f"/cmdb/devices/{tid}/usage-claim/", op, {"claim": "borrow", "counterparty": "回归-IT"})
check("L1 只读借出 -> 403", s == 403, str(s))
s, r = call("POST", f"/cmdb/devices/{tid}/usage-claim/", admin, {"claim": "borrow"})
check("L2 缺 counterparty -> 400", s == 400, str(r)[:100])
old_dt = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
s, r = call("POST", f"/cmdb/devices/{tid}/usage-claim/", admin,
            {"claim": "borrow", "counterparty": "回归-IT", "occurred_at": old_dt, "note": "40天前借出"})
check("L3 借出成功(历史时间)", s == 200 and r.get("usage_status") == "occupied" and r.get("claim") == "borrow",
      str(r)[:150])
s, r = call("POST", f"/cmdb/devices/{tid}/usage-claim/", admin, {"claim": "borrow", "counterparty": "x"})
check("L4 重复借出 -> 400", s == 400, str(r)[:120])
_, dev = call("GET", f"/cmdb/devices/{tid}/", admin)
check("L5 设备已标记占用", dev.get("usage_status") == "occupied", str(dev.get("usage_status")))
s, ls = call("GET", "/cmdb/devices/loan-summary/", admin)
hit = next((b for b in ls.get("borrowed", []) if b["device_id"] == tid), None)
check("L6 台账在借含此设备", s == 200 and hit is not None and hit["holder"] == "回归-IT"
      and hit["days"] >= 40 and ls.get("stats", {}).get("overdue", 0) >= 1,
      str(hit)[:200])
s, r = call("POST", f"/cmdb/devices/{tid}/usage-claim/", admin, {"claim": "return"})
check("L7 归还释放", s == 200 and r.get("usage_status") == "idle", str(r)[:120])
s, r = call("POST", f"/cmdb/devices/{tid}/usage-claim/", admin, {"claim": "return"})
check("L8 空闲提前归还 -> 400", s == 400, str(r)[:100])
s, ls = call("GET", "/cmdb/devices/loan-summary/", admin)
check("L9 台账移除该设备", all(b["device_id"] != tid for b in ls.get("borrowed", []))
      and any(a.get("device_id") == tid and a["event_type"] == "borrow"
              for a in ls.get("activity", [])), "activity?")
_, dev = call("GET", f"/cmdb/devices/{tid}/", admin)
check("L10 归还后状态 idle", dev.get("usage_status") == "idle", "")
# 事件留痕（audit/事件）
s, ev = call("GET", f"/cmdb/devices/{tid}/asset-events/", admin)
rows = ev if isinstance(ev, list) else (ev.get("results") or ev.get("events") or [])
types = [e["event_type"] for e in rows if "event_type" in e]
check("L11 借还事件各留痕", "borrow" in str(types) and "return" in str(types), str(types)[:120])
call("DELETE", f"/cmdb/devices/{tid}/", admin)
call("POST", f"/cmdb/devices/{tid}/purge/?confirm=1", admin)
s, ls = call("GET", "/cmdb/devices/loan-summary/", admin)
check("L12 purge 后孤儿不计入在借", all(b["device_id"] != tid for b in ls.get("borrowed", [])), "")

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
