"""资产生命周期 + 保修提醒回归：状态流转留事件 / 资产事件读写 / 越权 / 保修汇总。
用法: python scripts/verify_lifecycle.py [BASE]   （只读账号可用 NOPS_RO_USER 覆盖）
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

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


def call(method, path, tok=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=20) as r:
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


def pk(x):
    return x if isinstance(x, int) else x.get("id")


admin = login("admin", "nops@2025")
ro_user = os.environ.get("NOPS_RO_USER", "op_low")
op = login(ro_user, "NopsTest@2025")

_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]
bid = pk(base["id"])
DEV = {"model": pk(base["model"]), "site": pk(base["site"]), "region": pk(base["region"])}

# Y1 越权
s, _ = call("POST", f"/cmdb/devices/{bid}/lifecycle/", op, {"lifecycle_status": "spare"})
check("Y1 只读流转 -> 403", s == 403, str(s))
s, _ = call("POST", f"/cmdb/devices/{bid}/asset-events/", op, {"event_type": "borrow"})
check("Y2 只读写事件 -> 403", s == 403, str(s))

# Y3/Y4 流转 + 事件留痕
cur = base.get("lifecycle_status") or "deployed"
target = "spare" if cur != "spare" else "repairing"
s, r = call("POST", f"/cmdb/devices/{bid}/lifecycle/", admin, {"lifecycle_status": target})
check("Y3 流转到 " + target, s == 200 and r.get("lifecycle_status") == target, str(r)[:120])
s, evs = call("GET", f"/cmdb/devices/{bid}/asset-events/", admin)
events = evs if isinstance(evs, list) else []
hit = next((e for e in events if e.get("detail", {}).get("to") == target), None)
check("Y4 自动留资产事件", hit is not None and hit.get("event_type") in
      ("spare", "repair", "deploy", "in_stock", "purchase", "retire") and hit.get("operator") == "admin",
      str(events[:3]))
s, _ = call("POST", f"/cmdb/devices/{bid}/lifecycle/", admin, {"lifecycle_status": target})
check("Y5 同状态 -> 400", s == 400, str(s))
s, _ = call("POST", f"/cmdb/devices/{bid}/lifecycle/", admin, {"lifecycle_status": "nope"})
check("Y6 非法状态 -> 400", s == 400, str(s))
# 还原
call("POST", f"/cmdb/devices/{bid}/lifecycle/", admin, {"lifecycle_status": cur})

# Y7 手工事件
s, ev = call("POST", f"/cmdb/devices/{bid}/asset-events/", admin,
             {"event_type": "borrow", "counterparty": "研发部-张三", "detail": {"note": "临时借用一周"}})
check("Y7 写资产事件", s == 201 and ev.get("event_type") == "borrow", str(ev)[:120])
s, evs = call("GET", f"/cmdb/devices/{bid}/asset-events/", op)
events = evs if isinstance(evs, list) else []
check("Y8 只读可查事件(含备注)", s == 200 and any(
    e.get("counterparty") == "研发部-张三" and e.get("detail", {}).get("note") == "临时借用一周" for e in events),
    str(events[:2])[:200])

# Y9 保修提醒汇总与清单
today = date.today()
n1, n2 = "保修临期-" + TS[:6], "保修过期-" + TS[:6]
s, d1 = call("POST", "/cmdb/devices/", admin, {**DEV, "name": n1, "vendor": "W", "hw_model": "W-1",
                                               "warranty_until": (today + timedelta(days=35)).isoformat()})
s, d2 = call("POST", "/cmdb/devices/", admin, {**DEV, "name": n2, "vendor": "W", "hw_model": "W-2",
                                               "warranty_until": (today - timedelta(days=10)).isoformat()})
check("Y9 造临期/过期设备", s == 201 and s == 201, f"{d1.get('id')},{d2.get('id')}")
s, wr = call("GET", "/cmdb/devices/warranty-expiring/?within_days=180", admin)
ids = [r["id"] for r in wr.get("rows", [])]
check("Y10 汇总口径(60含/过期计数)", wr.get("summary", {}).get("60", -1) >= 1
      and wr.get("summary", {}).get("expired", -1) >= 1, str(wr.get("summary"))[:160])
hit1 = next((r for r in wr.get("rows", []) if r["id"] == d1.get("id")), None)
hit2 = next((r for r in wr.get("rows", []) if r["id"] == d2.get("id")), None)
check("Y11 清单含临期(≈35天)与过期(≈-10天)",
      hit1 is not None and 33 <= hit1["days_left"] <= 36
      and hit2 is not None and -11 <= hit2["days_left"] <= -8,
      f"{hit1} / {hit2}")
# 清理测试设备
for dev in (d1, d2):
    call("DELETE", f"/cmdb/devices/{dev['id']}/", admin)
    call("POST", f"/cmdb/devices/{dev['id']}/purge/?confirm=1", admin)
# 保修只读可读
s, wr2 = call("GET", "/cmdb/devices/warranty-expiring/", op)
check("Y12 只读可查保修提醒", s == 200 and "summary" in wr2, str(s))

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
