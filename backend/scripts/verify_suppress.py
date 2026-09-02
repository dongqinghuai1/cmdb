"""告警收敛/静默收官 E2E：根因抑制 v1（拓扑邻接×级别）+ 变更窗口自动静默（change 实施联动）。

语义：设备离线(父宕)时，若其 LLDP 直连邻居上有**更高级别**活跃事件，则该设备事件
被标记 suppressed_by_id（下游噪音）；根因事件自身不被抑制；同级互不吞。变更单
实施开始 → 受影响设备 maintenance 静默(窗口)，收尾(回滚/关闭) → 提前结束。

用法: python scripts/verify_suppress.py [BASE]
默认 sqlite 8010 (NOPS_EAGER=1)；容器 PG: http://127.0.0.1:8000/api/v1
前置: init_nops_data；admin/nops@2025、net_demo(NopsTest@2025, alert.event.view 无 execute)。
"""
import datetime
import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010/api/v1"
TS = time.strftime("%m%d%H%M%S")
TOK = f"SUP-{TS}"
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
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra)[:160] if not cond else ""))
    globals()["ok" if cond else "fail"] += 1


def evs(admin, dev_id, rule_id=None, status="firing"):
    _, r = call("GET", f"/alerts/events/?device_id={dev_id}&page_size=100", admin)
    out = [e for e in r.get("results", [])
           if (rule_id is None or e.get("rule_id") == rule_id) and e.get("status") == status]
    return out


admin = login("admin", "nops@2025")
net = login("net_demo", "NopsTest@2025")

# ---------- 预清理（幂等重跑） ----------
_, dv = call("GET", "/cmdb/devices/?search=SUP-&page_size=100", admin)
for d in dv.get("results", []):
    call("POST", f"/cmdb/devices/{d['id']}/purge/?confirm=1", admin)
_, rl = call("GET", "/alerts/rules/?page_size=200", admin)
for r in rl.get("results", []):
    if r.get("name", "").startswith("SUP-"):
        call("DELETE", f"/alerts/rules/{r['id']}/", admin)
_, sl = call("GET", "/alerts/silences/?page_size=200", admin)
for s in sl.get("results", []):
    if "SUP-" in (s.get("reason") or "") and s.get("silence_type") == "maintenance":
        call("DELETE", f"/alerts/silences/{s['id']}/", admin)

_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]


def mk(name, ip):
    s, r = call("POST", "/cmdb/devices/", admin, {
        "name": name, "vendor": "H3C", "model": base["model"],
        "site": base["site"], "region": base["region"],
        "driver_type": "h3c_comware", "manage_ip": ip})
    return s, r


# ---- 拓扑对 R(父/根) / C(子/下游)：mock 发现造 LLDP 邻接（勿触网） ----
sR, R = mk(f"SUP-R-{TS}", "198.51.100.31")
sC, C = mk(f"SUP-C-{TS}", "198.51.100.32")
check("S1 造父/子设备 R、C", sR == 201 and sC == 201, f"{sR}/{sC}")
s, cred = call("POST", "/system/credentials/", admin,
               {"name": f"SUP-cred-{TS}", "cred_type": "snmp_v2c", "username": "",
                "secret": "public", "params": {"port": 161}})
cid = cred["id"]
okbind = True
for did in (R["id"], C["id"]):
    s, _ = call("PATCH", f"/cmdb/devices/{did}/", admin, {"credential_id": cid})
    okbind = okbind and s == 200
    s, r = call("POST", f"/cmdb/devices/{did}/snmp-test/", admin, {"mock": 1})
    okbind = okbind and (s == 200 and r.get("interfaces", 0) >= 2)
check("S2 凭据绑定+接口预铺(≥2)", okbind)
s, r = call("POST", "/topo/lldp-discover/", admin, {"mock": 1})
check("S3 mock 发现", s == 200 and r.get("ok", 0) >= 2, str(r)[:120])

# ---- 规则：全局离线(major) + R 专属日志(critical) ----
s, off = call("POST", "/alerts/rules/", admin, {
    "name": f"SUP-OFF-{TS}", "rule_type": "state", "metric": "offline",
    "severity": "major", "enabled": True})
s, crit = call("POST", "/alerts/rules/", admin, {
    "name": f"SUP-CRIT-{TS}", "rule_type": "log_keyword",
    "log_pattern": f"SUP-PANIC-{TS}", "severity": "critical", "enabled": True})
check("S4 建离线(major)/日志(critical)规则", s == 201 and crit.get("id"),
      str({k: (off.get(k) if k == "name" else crit.get("id")) for k in ["name"]}))
off_id, crit_id = off["id"], crit["id"]

# R 上写一条致命日志 → R 得 critical 事件（根因源）
s, lg = call("POST", "/monitor/logs/test-write/", admin,
             {"device": R["id"], "message": f"SUP-PANIC-{TS} kernel oops on core",
              "severity": 2})
check("S5 向 R 写致命日志", s == 200 and lg.get("id"), str(lg)[:100])

s, evres = call("POST", "/alerts/rules/evaluate/", admin, {})
r_ev = evs(admin, R["id"])
c_ev = evs(admin, C["id"])
check("S6 评估后 R/C 各有活跃事件", evres.get("fired_new", 0) >= 0
      and len(r_ev) >= 2 and len(c_ev) >= 1, f"R={len(r_ev)} C={len(c_ev)}")
r_crit = next((e for e in r_ev if e.get("rule_id") == crit_id), None)
c_off = next((e for e in c_ev if e.get("rule_id") == off_id), None)
r_off = next((e for e in r_ev if e.get("rule_id") == off_id), None)
check("S7 找到根因 critical 与下游离线事件", bool(r_crit) and bool(c_off) and bool(r_off),
      f"crit={r_crit and r_crit.get('id')} c_off={c_off and c_off.get('id')}")

# 权限负例 + 手动同步
s, _ = call("POST", "/alerts/events/suppress-sync/", net, {})
check("S8 无 execute 权限触发抑制同步 -> 403", s == 403, s)
s, sync1 = call("POST", "/alerts/events/suppress-sync/", admin, {})
c_off2 = evs(admin, C["id"], off_id)[0]
r_crit2 = evs(admin, R["id"], crit_id)[0]
root = call("GET", f"/alerts/events/{c_off2['suppressed_by_id']}/", admin)[1] \
    if c_off2.get("suppressed_by_id") else {}
check("S9 抑制同步：C 离线被 R 上 critical 根事件抑制", s == 200
      and c_off2.get("suppressed") is True
      and root.get("device_id") == R["id"] and root.get("severity") == "critical",
      str({k: c_off2.get(k) for k in ("suppressed_by_id", "suppressed")})
      + " root=" + str(root.get("id")))
check("S10 根因事件自身不被抑制", r_crit2.get("suppressed_by_id") is None,
      str(r_crit2.get("suppressed_by_id")))

# 根因恢复（本规则 critical 事件先确认，含其它规则下 R 的 critical 一并恢复）
for e in evs(admin, R["id"]):
    if e.get("severity") == "critical" and e.get("status") == "firing":
        call("POST", f"/alerts/events/{e['id']}/resolve/", admin, {})
s, sync2 = call("POST", "/alerts/events/suppress-sync/", admin, {})
c_off3 = evs(admin, C["id"], off_id)[0]
check("S11 根因恢复后下游抑制清除", s == 200 and sync2.get("cleared", 0) >= 1
      and c_off3.get("suppressed_by_id") is None and c_off3.get("suppressed") is False,
      str({k: c_off3.get(k) for k in ("suppressed_by_id", "suppressed")})
      + " cleared=" + str(sync2.get("cleared")))

# ---------- 变更窗口自动静默 ----------
now = datetime.datetime.now()
plan_start = (now - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
plan_end = (now + datetime.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
s, ct = call("POST", "/changes/change-tickets/", admin, {
    "title": f"SUP 变更窗口联动 {TS}", "change_type": "config", "risk_level": "high",
    "content": {"summary": "核心设备固件窗口", "impact": "测试",
                "affected_device_ids": [C["id"]]}})
check("S12 建变更单草稿", s == 201 and ct.get("id"), str(ct)[:120])
ctid = ct["id"]
s, r = call("POST", f"/changes/change-tickets/{ctid}/submit/", admin, {
    "plan_start": plan_start, "plan_end": plan_end, "approver_id": 1,
    "content": ct["content"]})
check("S13 提交审批", s == 200 and r.get("status") == "approving", str(r)[:140])
s, r = call("POST", f"/changes/change-tickets/{ctid}/approve/", admin, {})
check("S14 审批通过", s == 200 and r.get("status") == "approved", str(r)[:140])
s, r = call("POST", f"/changes/change-tickets/{ctid}/start/", admin, {})
check("S15 开始实施", s == 200 and r.get("status") == "implementing", str(r)[:140])
_, sl2 = call("GET", "/alerts/silences/?silence_type=maintenance&page_size=100", admin)
win = [x for x in sl2.get("results", []) if x.get("device_usage_id") == ctid]
check("S16 实施开始自动建窗口静默", len(win) == 1
      and C["id"] in (win[0].get("scope", {}).get("device_ids") or [])
      and (win[0].get("ended_at") or "")[:10] >= now.strftime("%Y-%m-%d")
      and "维护窗口" in (win[0].get("reason") or ""), str(win[0] if win else win)[:200])
s, r = call("POST", f"/changes/change-tickets/{ctid}/rollback/", admin,
            {"rollback_plan": "回退镜像版本并观察"})
check("S17 回滚收尾", s == 200 and r.get("status") == "rolledback", str(r)[:140])
_, sl3 = call("GET", "/alerts/silences/?silence_type=maintenance&page_size=100", admin)
win2 = [x for x in sl3.get("results", []) if x.get("device_usage_id") == ctid]
check("S18 收尾提前结束窗口静默", len(win2) == 1 and win2[0].get("ended_at") is not None,
      str(win2[0].get("ended_at"))[:40])

# ---------- 清理 ----------
for d in dv.get("results", []):  # noqa: 上一轮残留已清，此处清本轮回
    pass
call("POST", f"/cmdb/devices/{R['id']}/purge/?confirm=1", admin)
call("POST", f"/cmdb/devices/{C['id']}/purge/?confirm=1", admin)
call("DELETE", f"/alerts/rules/{off_id}/", admin)
call("DELETE", f"/alerts/rules/{crit_id}/", admin)
_, sl4 = call("GET", "/alerts/silences/?page_size=200", admin)
for s in sl4.get("results", []):
    if "SUP-" in (s.get("reason") or "") and s.get("silence_type") == "maintenance":
        call("DELETE", f"/alerts/silences/{s['id']}/", admin)
_, dv2 = call("GET", "/cmdb/devices/?search=SUP-&page_size=100", admin)
check("S19 清理完成（SUP 设备归零）", dv2.get("count", 0) == 0, str(dv2.get("count")))

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
