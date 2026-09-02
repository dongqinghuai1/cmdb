"""报表中心 E2E：快照生成幂等(手动四类型) / 订阅 CRUD+立即运行 / 汇总端点 / 权限正负例。

用法: python scripts/verify_report.py [BASE]
默认 sqlite 8010 (NOPS_EAGER=1)；容器 PG: http://127.0.0.1:8000/api/v1
前置: init_nops_data；admin/nops@2025、sys_demo(NopsTest@2025, report.snapshot.view+edit)、
      net_demo(NopsTest@2025, view 无 edit)、auditor(NopsTest@2025, 无 report)。
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010/api/v1"
TS = time.strftime("%m%d%H%M%S")
ok = fail = 0


def call(method, path, token=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "replace")[:120]}


def login(u, p):
    s, r = call("POST", "/auth/login/", body={"username": u, "password": p})
    if s != 200:
        print("login fail", u)
        sys.exit(1)
    return r["access"]


def check(name, cond, extra=""):
    global ok, fail
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra)[:170] if not cond else ""))
    globals()["ok" if cond else "fail"] += 1


admin = login("admin", "nops@2025")
sysu = login("sys_demo", "NopsTest@2025")
net = login("net_demo", "NopsTest@2025")
aud = login("auditor", "NopsTest@2025")

# 预清理（幂等重跑：删掉本脚本旧订阅）
_, old = call("GET", "/reports/schedules/?search=REP-&page_size=100", admin)
for s in old.get("results", []):
    call("DELETE", f"/reports/schedules/{s['id']}/", admin)

# ---- 权限读门 ----
s, _ = call("GET", "/reports/snapshots/", sysu)
check("R1 sys_demo 读快照 200", s == 200, s)
s, _ = call("GET", "/reports/snapshots/", aud)
check("R2 auditor 读快照 403", s == 403, s)
s, _ = call("GET", "/reports/schedules/", net)
check("R3 net_demo(view) 读订阅 200", s == 200, s)

# ---- 手动生成四类快照（幂等） ----
ids = {}
for t in ("inventory", "alerts", "changes", "ncm"):
    s, r = call("POST", "/reports/snapshots/generate/", sysu, {"report_type": t})
    check(f"R4 {t} 手动生成", s == 201 and r.get("report_type") == t and r.get("content"),
          str(r)[:150])
    ids[t] = r.get("id")
_, inv = call("POST", "/reports/snapshots/generate/", sysu, {"report_type": "inventory"})
check("R5 inventory 同日重复生成幂等(同 id 覆盖)", inv.get("id") == ids["inventory"]
      and inv.get("content", {}).get("total", -1) >= 0, str(inv.get("id")))
_, latest = call("GET", "/reports/snapshots/latest/", admin)
check("R6 latest 每类一份含 content", all(t in latest for t in ("inventory", "alerts", "changes", "ncm"))
      and latest["inventory"]["content"].get("total", -1) >= 0, str(list(latest))[:120])

# ---- 生成权限负例 ----
s, _ = call("POST", "/reports/snapshots/generate/", net, {"report_type": "inventory"})
check("R7 net_demo(view) 生成 -> 403", s == 403, s)
s, _ = call("POST", "/reports/snapshots/generate/", aud, {"report_type": "alerts"})
check("R8 auditor 生成 -> 403", s == 403, s)
s, _ = call("POST", "/reports/snapshots/generate/", admin, {"report_type": "bogus"})
check("R9 非法类型 -> 400", s == 400, s)

# ---- 订阅 ----
s, sch = call("POST", "/reports/schedules/", sysu, {
    "name": f"REP-{TS}", "report_type": "alerts", "hour": 7, "enabled": True,
    "notify_channel_ids": [], "remark": "回归订阅"})
check("R10 sys 建订阅", s == 201 and sch.get("created_by_id") and sch.get("report_type_label"),
      str(sch)[:140])
sid = sch["id"]
s, _ = call("POST", "/reports/schedules/", net, {"name": f"REP-N-{TS}", "report_type": "ncm"})
check("R11 net 建订阅 -> 403", s == 403, s)
s, _ = call("POST", "/reports/schedules/", sysu, {"name": f"REP-{TS}", "report_type": "alerts"})
check("R12 同名订阅重复 -> 400", s == 400, s)
s, _ = call("PATCH", f"/reports/schedules/{sid}/", sysu, {"enabled": False})
check("R13 sys 停用订阅", s == 200, s)
s, r = call("POST", f"/reports/schedules/{sid}/run/", sysu, {})
check("R14 手动 run 生成快照 + last_run", s == 201 and r.get("content")
      and r.get("content", {}).get("summary"), str(r)[:160])
s, r = call("POST", f"/reports/schedules/{sid}/run/", net, {})
check("R15 net run -> 403", s == 403, s)
s, ov = call("GET", "/reports/schedules/overview/", admin)
check("R16 overview 含订阅与最近快照", s == 200 and ov.get("schedules", 0) >= 1
      and "alerts" in ov.get("latest_per_type", {}), str(ov)[:160])
s, _ = call("DELETE", f"/reports/schedules/{sid}/", sysu)
check("R17 sys 删订阅", s == 204, s)

# ---- 幂等校验：多次生成仅保留当日一份（(type, period_start) 唯一） ----
_, al = call("GET", "/reports/snapshots/?report_type=alerts&page_size=100", admin)
check("R18 同日多生成幂等(alerts 仅 1 份)", al.get("count", 0) == 1, str(al.get("count")))

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
