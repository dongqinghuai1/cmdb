"""安全基线闭环 E2E：规则库预置 / scope(驱动·设备) / 结果留痕 / 不合规联动告警 / 修复即恢复 / 汇总 / purge 清理。

用法: python scripts/verify_baseline.py [BASE]
默认 BASE=http://127.0.0.1:8010/api/v1 (sqlite)；容器 PG: http://127.0.0.1:8000/api/v1
前置: init_nops_data；ncm migrate（0002 规则库 seed）；admin/nops@2025、auditor/NopsTest@2025
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010/api/v1")
TS = time.strftime("%m%d%H%M%S")
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
aud = login("auditor", "NopsTest@2025")

# ---- 预清理（幂等重跑）----
_, rs = call("GET", "/ncm/baseline-rules/?page_size=200", admin)
for r in rs.get("results", []):
    if r["name"].startswith("T-"):
        call("DELETE", f"/ncm/baseline-rules/{r['id']}/", admin)
_, dv = call("GET", "/cmdb/devices/?search=BS-&page_size=100", admin)
for d in dv.get("results", []):
    call("POST", f"/cmdb/devices/{d['id']}/purge/?confirm=1", admin)

_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]


def mk(name, ip, driver):
    s, r = call("POST", "/cmdb/devices/", admin, {
        "name": name, "vendor": "H3C" if driver == "h3c_comware" else "Fortinet",
        "model": base["model"], "site": base["site"], "region": base["region"],
        "driver_type": driver, "manage_ip": ip})
    return s, r


def imp(dev_id, content):
    return call("POST", "/ncm/backups/import/", admin,
                {"device": dev_id, "content": content})


# ---- A. 规则库预置 ----
_, rules = call("GET", "/ncm/baseline-rules/?page_size=200", admin)
names = [r["name"] for r in rules.get("results", [])]
seed_names = ["禁止明文 Telnet 服务", "禁止默认 SNMP 团体字符串", "启用会话空闲超时",
              "禁止明文 HTTP 管理面", "口令加密存储"]
check("B1 规则库 seed(5 条预置)", all(n in names for n in seed_names),
      str(len(names)))
tel_rule = next(r for r in rules["results"] if r["name"] == "禁止明文 Telnet 服务")
snmp_rule = next(r for r in rules["results"] if r["name"] == "禁止默认 SNMP 团体字符串")

# ---- B. 设备与配置导入 ----
sA, A = mk(f"BS-A-{TS}", f"198.51.{int(TS) % 240}.{int(TS[4:6]) % 250 + 1}", "h3c_comware")
sB, B = mk(f"BS-B-{TS}", f"198.51.{int(TS) % 240 + 1}.{int(TS[4:6]) % 250 + 1}", "fortigate")
check("B2 造临时设备 A(h3c)/B(fortigate)", sA == 201 and sB == 201, f"{sA}/{sB}")
Aid, Bid = A["id"], B["id"]

bad_cfg = (
    "hostname BS-A\n"
    "snmp-agent community read public\n"      # 命中 SNMP 默认团体（major）
    "telnet server enable\n"                  # 命中明文 telnet（major）
    "user privilege level 15 password cipher x\n"   # 口令密文：满足加密规则
    "idle-timeout 5 0\n"                      # 会话超时：满足
    "ssh server enable\n"
)
clean_cfg = (
    "config system global\n"
    "set admin-sport 443\n"
    "set admin-http-redirect disable\n"
)
s, r1 = imp(Aid, bad_cfg)
s2, r2 = imp(Bid, clean_cfg)
check("B3 配置导入(两台)", s == 200 and r1.get("backup") and s2 == 200 and r2.get("backup"),
      f"{r1} / {r2}"[:160])

# ---- C. 核查与告警联动 ----
s, _ = call("POST", "/ncm/baseline-rules/check/", aud, {})
check("C1 无 cmdb 权限触发核查 -> 403", s == 403, s)

s, r = call("POST", "/ncm/baseline-rules/check/", admin, {"device_ids": [Aid, Bid]})
check("C2 全规则核查返回统计", s == 200 and r.get("checked", 0) == 10
      and r.get("devices") == 2 and r.get("violations", 0) >= 4,
      str({k: r.get(k) for k in ("checked", "devices", "violations")}))
check("C3 违规含 Telnet/SNMP 规则", any("Telnet" in (x.get("rule_name") or "")
      for x in r.get("violation_rows", []))
      and any("SNMP" in (x.get("rule_name") or "") for x in r.get("violation_rows", [])),
      str(r.get("violation_rows", [])[:2])[:160])

_, evs = call("GET", f"/alerts/events/?device_id={Aid}&page_size=100", admin)
keys = {e["dedup_key"] for e in evs.get("results", [])}
check("C4 违规联动告警(firing)", f"{Aid}:baseline:{tel_rule['id']}" in keys
      and f"{Aid}:baseline:{snmp_rule['id']}" in keys, str(len(keys)))

# ---- D. 修复后恢复 ----
fix_cfg = bad_cfg.replace("telnet server enable\n", "").replace(
    "snmp-agent community read public\n", "snmp-agent community read nops-ro-2026\n")
s, r = imp(Aid, fix_cfg)
check("D1 修复配置导入(changed)", s == 200 and r.get("changed") is True, str(r)[:100])
s, r = call("POST", "/ncm/baseline-rules/check/", admin, {"device_ids": [Aid, Bid]})
_, evs = call("GET", f"/alerts/events/?device_id={Aid}&page_size=100", admin)
evmap = {e["dedup_key"]: e for e in evs.get("results", [])}
k_t, k_s = f"{Aid}:baseline:{tel_rule['id']}", f"{Aid}:baseline:{snmp_rule['id']}"
check("D2 修复后告警自动恢复(resolved)", k_t in evmap and evmap[k_t]["status"] == "resolved"
      and k_s in evmap and evmap[k_s]["status"] == "resolved",
      str({k: evmap.get(k, {}).get("status") for k in (k_t, k_s)})[:160])
s, res = call("GET", f"/ncm/baseline-results/?rule={tel_rule['id']}&device_id={Aid}"
              "&compliant=true&page_size=10", admin)
check("D3 修复后结果为 compliant", s == 200 and res.get("count", 0) >= 1, str(res.get("count")))

# ---- E. scope：driver_types / device_ids ----
s, rdrv = call("POST", "/ncm/baseline-rules/", admin, {
    "name": f"T-drv-{TS}", "rule_type": "must_present", "pattern": "audit enable",
    "scope": {"driver_types": ["h3c_comware"]}, "severity": "warning"})
check("E1 建 driver 范围规则", s == 201, str(rdrv)[:120])
s, r = call("POST", "/ncm/baseline-rules/check/", admin,
            {"rule_ids": [rdrv["id"]], "device_ids": [Aid, Bid]})
_, res = call("GET", f"/ncm/baseline-results/?rule={rdrv['id']}&page_size=50", admin)
rdevs = {x["device_id"] for x in res.get("results", [])}
check("E2 driver 范围只查 h3c(A，不含 B)", s == 200 and r["checked"] == 1
      and rdevs == {Aid}, str(rdevs))
s, rdev = call("POST", "/ncm/baseline-rules/", admin, {
    "name": f"T-dev-{TS}", "rule_type": "must_absent", "pattern": "community read nops-ro-2026",
    "scope": {"device_ids": [Bid]}, "severity": "major"})
s, r = call("POST", "/ncm/baseline-rules/check/", admin,
            {"rule_ids": [rdev["id"]], "device_ids": [Aid, Bid]})
_, res = call("GET", f"/ncm/baseline-results/?rule={rdev['id']}&page_size=50", admin)
rdevs2 = {x["device_id"] for x in res.get("results", [])}
check("E3 device 范围只查 B(不含 A)", s == 200 and r["checked"] == 1 and rdevs2 == {Bid},
      str(rdevs2))

# ---- F. 汇总 ----
s, sumr = call("GET", "/ncm/baseline-results/summary/", admin)
tots = sumr.get("totals", {})
check("F1 合规总览结构", s == 200 and isinstance(sumr.get("rules"), list)
      and len(sumr["rules"]) >= 1 and tots.get("checked", 0) >= 1
      and tots.get("violations", 0) >= 1, str(tots)[:160])

# ---- G. purge 清理跨域残留 ----
for did in (Aid, Bid):
    call("POST", f"/cmdb/devices/{did}/purge/?confirm=1", admin)
_, evs = call("GET", f"/alerts/events/?device_id={Aid}&page_size=100", admin)
_, bks = call("GET", f"/ncm/backups/?device_id={Aid}&page_size=100", admin)
_, rrs = call("GET", f"/ncm/baseline-results/?device_id={Aid}&page_size=100", admin)
check("G1 purge 清事件/备份/基线结果孤儿", evs.get("count", 0) == 0
      and bks.get("count", 0) == 0 and rrs.get("count", 0) == 0,
      f"ev={evs.get('count')} bk={bks.get('count')} rs={rrs.get('count')}")

for rid in (rdrv["id"], rdev["id"]):
    call("DELETE", f"/ncm/baseline-rules/{rid}/", admin)

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
