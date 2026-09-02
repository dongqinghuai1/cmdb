"""告警收敛/静默增强 v1 E2E：占用(借出)自动静默 + dedup_window_s 复燃合并。

用法: python scripts/verify_alert_converge.py [BASE]
默认 BASE=http://127.0.0.1:8010/api/v1 (sqlite: NOPS_DB=sqlite NOPS_EAGER=1 runserver 8010)
容器 PG: http://127.0.0.1:8000/api/v1
前置: 种子数据(init_nops_data) + 演示账号 admin/nops@2025、net_demo/NopsTest@2025
"""
import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010/api/v1")
TS = __import__("time").strftime("%m%d%H%M%S")
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
net = login("net_demo", "NopsTest@2025")   # cmdb.device.view / alert.event.view，无写权

_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]

# ---- 造一台默认 offline 的临时设备（可被 state-offline 规则命中） ----
s, dev = call("POST", "/cmdb/devices/", admin, {
    "name": f"ALC-{TS}", "vendor": "H3C", "model": base["model"],
    "site": base["site"], "region": base["region"],
    "driver_type": "h3c_comware", "manage_ip": f"198.51.100.{int(TS) % 250 + 1}"})
check("S1 造临时设备(默认 offline)", s == 201, str(dev)[:140])
did = dev["id"]
silence_ids = []


def rule(name, window):
    s, r = call("POST", "/alerts/rules/", admin, {
        "name": name, "rule_type": "state", "metric": "offline",
        "severity": "major", "dedup_window_s": window})
    return s, r


def firing_for(d, rid):
    _, evs = call("GET", f"/alerts/events/?device_id={d}&page_size=100", admin)
    return [e for e in evs.get("results", [])
            if e.get("dedup_key") == f"{d}:{rid}"]


def all_for(d, rid):
    _, evs = call("GET", f"/alerts/events/?device_id={d}&page_size=100", admin)
    return [e for e in evs.get("results", [])
            if e.get("dedup_key") == f"{d}:{rid}"]


# ---- 占用(借出)自动静默 ----
s, r1 = rule(f"T-Alc-Win-{TS}", 3600)
check("S2 建 state-offline 规则(窗口3600)", s == 201, str(r1)[:120])
rid1 = r1["id"]

s, r = call("POST", f"/cmdb/devices/{did}/usage-claim/", admin,
            {"claim": "borrow", "counterparty": "回归占用-收敛静默"})
check("S3 借出占用", s == 200 and r.get("usage_status") == "occupied", str(r)[:140])

_, sils = call("GET", "/alerts/silences/?page_size=100", admin)
occ = [x for x in sils.get("results", [])
       if x.get("silence_type") == "occupation"
       and did in (x.get("scope") or {}).get("device_ids", [])]
check("S4 借出自动建 occupation 静默(未结束)", len(occ) >= 1
      and occ[0].get("ended_at") is None, str([x["id"] for x in occ]))
silence_ids += [x["id"] for x in occ]

s, r = call("POST", "/alerts/rules/evaluate/", admin, {})
check("S5 占用期间评估可执行", s == 200 and r.get("ts"), str(r)[:100])
check("S6 占用期间不产生 firing 事件", len(firing_for(did, rid1)) == 0,
      str(len(firing_for(did, rid1))))

s, r = call("POST", "/alerts/rules/evaluate/", net, {})
check("S7 无规则管理权限触发评估 -> 403", s == 403, str(s))

s, r = call("POST", f"/cmdb/devices/{did}/usage-claim/", net, {"claim": "borrow"})
check("S8 只读账号借出 -> 403", s == 403, str(s))

s, r = call("POST", f"/cmdb/devices/{did}/usage-claim/", admin,
            {"claim": "return", "counterparty": ""})
check("S9 归还释放占用", s == 200 and r.get("usage_status") == "idle", str(r)[:120])

_, sils = call("GET", "/alerts/silences/?page_size=100", admin)
occ = [x for x in sils.get("results", [])
       if x.get("silence_type") == "occupation"
       and did in (x.get("scope") or {}).get("device_ids", [])]
check("S10 归还自动结束 occupation 静默", len(occ) >= 1
      and occ[0].get("ended_at") is not None, str(occ[:1]))

# ---- 归还后评估触发 + dedup_window 复燃合并 ----
s, r = call("POST", "/alerts/rules/evaluate/", admin, {})
rows = firing_for(did, rid1)
check("S11 归还后恢复触发(1 条 firing/count=1)", len(rows) == 1
      and rows[0].get("fired_count") == 1, str(rows)[:160])

s, r2 = rule(f"T-Alc-Win2-{TS}", 3600)
rid2 = r2["id"]
s, r = call("POST", "/alerts/rules/evaluate/", admin, {})
rows = firing_for(did, rid2)
check("S12 窗口规则首触发", len(rows) == 1 and rows[0].get("fired_count") == 1, str(rows)[:140])
e2 = rows[0]["id"]
s, r = call("POST", f"/alerts/events/{e2}/resolve/", admin)
check("S13 resolve 动作带 resolved_at", s == 200 and r.get("status") == "resolved"
      and r.get("resolved_at"), str(r)[:120])
s, r = call("POST", "/alerts/rules/evaluate/", admin, {})
rows = firing_for(did, rid2)
check("S14 窗口内复燃合并同一行(不重开事件)", len(rows) == 1
      and rows[0].get("fired_count", 0) >= 2, str(rows)[:160])

s, r3 = rule(f"T-Alc-Zero-{TS}", 0)   # 窗口 0 = 不合并
rid3 = r3["id"]
s, r = call("POST", "/alerts/rules/evaluate/", admin, {})
rows = firing_for(did, rid3)
check("S15 零窗口规则首触发", len(rows) == 1, str(rows)[:140])
e3 = rows[0]["id"]
call("POST", f"/alerts/events/{e3}/resolve/", admin)
s, r = call("POST", "/alerts/rules/evaluate/", admin, {})
all3 = all_for(did, rid3)
fir3 = [x for x in all3 if x.get("status") == "firing"]
check("S16 窗口0 复燃新建事件(旧 resolved + 新 firing)", len(all3) >= 2
      and len(fir3) == 1 and fir3[0].get("id") != e3,
      str([(x["id"], x["status"]) for x in all3])[:160])

# ---- 清理：删规则 -> 删静默 -> purge 设备 ----
for rid in (rid1, rid2, rid3):
    call("DELETE", f"/alerts/rules/{rid}/", admin)
for sid in silence_ids:
    call("DELETE", f"/alerts/silences/{sid}/", admin)
s, r = call("POST", f"/cmdb/devices/{did}/purge/?confirm=1", admin)
check("S17 purge 临时设备", s == 200, str(r)[:120])
_, evs = call("GET", f"/alerts/events/?device_id={did}&page_size=100", admin)
check("S18 purge 后无该设备事件残留", evs.get("count", 0) == 0,
      str(evs.get("count")))

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
