"""值班排班 DutySchedule API E2E（system 域 V1.1#23 有表无 API -> 补齐）。

用法: python scripts/verify_duty.py [BASE]
默认 BASE=http://127.0.0.1:8010/api/v1 (sqlite)；容器 PG: http://127.0.0.1:8000/api/v1
前置: init_nops_data（含新 system.duty.view/edit 权限码）幂等重跑过
"""
import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010/api/v1")
ok = fail = 0


def call(method, path, token=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data) as r:
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
sysu = login("sys_demo", "NopsTest@2025")     # 有 system.duty.view+edit
net = login("net_demo", "NopsTest@2025")      # 无任何 system.duty.*
aud = login("auditor", "NopsTest@2025")       # 仅 system.audit.view

_, us = call("GET", "/system/users/?page_size=100", admin)
uid = {u["username"]: u["id"] for u in us.get("results", [])}
if "sys_demo" not in uid or "net_demo" not in uid:
    check("用户种子齐全", False, str(list(uid)[:8]))
    sys.exit(1)

# 预清理历史残留（幂等重跑）：清掉本组测试日期旧行
for day in ("2099-01-05", "2099-01-06"):
    _, rows = call("GET", f"/system/duty-schedules/?duty_date={day}&page_size=50", admin)
    for r in rows.get("results", []):
        call("DELETE", f"/system/duty-schedules/{r['id']}/", admin)

# ---- 权限门 ----
s, _ = call("GET", "/system/duty-schedules/", admin)
check("D1 admin 列表可读", s == 200, s)
s, _ = call("GET", "/system/duty-schedules/", sysu)
check("D2 sys_demo(有 duty.view) 可读", s == 200, s)
s, _ = call("GET", "/system/duty-schedules/", net)
check("D3 net_demo(无 duty 码) 读 -> 403", s == 403, s)
s, _ = call("GET", "/system/duty-schedules/", aud)
check("D4 auditor(仅 audit.view) 读 -> 403", s == 403, s)

# ---- 排班 CRUD ----
s, r = call("POST", "/system/duty-schedules/", admin,
            {"shift": "primary", "user": uid["sys_demo"], "duty_date": "2099-01-05",
             "region": None, "handover_note": ""})
check("D5 排主班(admin 写)", s == 201 and r.get("user_name") == "sys_demo"
      and r.get("duty_date") == "2099-01-05", str(r)[:160])
p1 = r["id"]
s, r = call("POST", "/system/duty-schedules/", admin,
            {"shift": "primary", "user": uid["sys_demo"], "duty_date": "2099-01-05"})
check("D6 同人同日同班次重复 -> 400", s == 400, str(r)[:140])
s, r = call("POST", "/system/duty-schedules/", admin,
            {"shift": "backup", "user": uid["net_demo"], "duty_date": "2099-01-05"})
check("D7 同日备班(不同人)可排", s == 201 and r.get("user_name") == "net_demo", str(r)[:140])
p2 = r["id"]
s, r = call("POST", "/system/duty-schedules/", sysu,
            {"shift": "primary", "user": uid["net_demo"], "duty_date": "2099-01-06"})
check("D8 sys_demo(有 edit) 可排班", s == 201, str(r)[:140])
p3 = r["id"]
s, r = call("POST", "/system/duty-schedules/", net,
            {"shift": "backup", "user": uid["sys_demo"], "duty_date": "2099-01-06"})
check("D9 net_demo 排班 -> 403", s == 403, str(r)[:120])

# ---- 日历视图 ----
s, cal = call("GET", "/system/duty-schedules/calendar/?month=2099-01", admin)
d5 = next((d for d in cal.get("days", []) if d["date"] == "2099-01-05"), None)
d6 = next((d for d in cal.get("days", []) if d["date"] == "2099-01-06"), None)
check("D10 日历含 31 天", s == 200 and len(cal.get("days", [])) == 31, s)
check("D11 01-05 主/备班呈现", d5 is not None
      and d5["primary"] and d5["primary"]["user_name"] == "sys_demo"
      and d5["backup"] and d5["backup"]["user_name"] == "net_demo",
      str({k: (v or {}).get("user_name") if isinstance(v, dict) else v
           for k, v in (d5 or {}).items()})[:160])
check("D12 01-06 主班(sys_demo 排)呈现", d6 is not None
      and d6["primary"] and d6["primary"]["user_name"] == "net_demo", str(d6)[:160])
s, _ = call("GET", "/system/duty-schedules/calendar/?month=2099-01", aud)
check("D13 auditor 看日历 -> 403", s == 403, s)

# ---- 交班 ----
s, r = call("POST", f"/system/duty-schedules/{p1}/handoff/", admin, {"note": "交接完成，SNMP 巡检已说明"})
check("D14 交班置 handed_off_at+备注", s == 200 and r.get("handed_off_at")
      and "SNMP" in (r.get("handover_note") or ""), str(r)[:160])
s, _ = call("POST", f"/system/duty-schedules/{p1}/handoff/", net)
check("D15 无权限交班 -> 403", s == 403, s)

# ---- 更新（edit 门禁）----
s, r = call("PATCH", f"/system/duty-schedules/{p2}/", sysu, {"handover_note": "备班待命"})
check("D16 sys_demo 更新备班", s == 200 and (r.get("handover_note") or "") == "备班待命", str(r)[:140])
s, _ = call("PATCH", f"/system/duty-schedules/{p2}/", aud, {"handover_note": "x"})
check("D17 auditor 更新 -> 403", s == 403, s)

# ---- 审计链 ----
s, logs = call("GET", "/system/audit-logs/?resource_type=DutySchedule&page_size=20", admin)
check("D18 排班写审计落库(create/handoff>=2)", s == 200
      and logs.get("count", 0) >= 2, str(logs.get("count")))

# ---- 清理 ----
for pid in (p1, p2, p3):
    call("DELETE", f"/system/duty-schedules/{pid}/", admin)
s, rows = call("GET", "/system/duty-schedules/?page_size=100", admin)
check("D19 清理后无本组排班残留", not any(x.get("duty_date", "").startswith("2099-01")
      for x in rows.get("results", [])), str(rows.get("count")))

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
