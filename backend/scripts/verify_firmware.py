"""固件升级编排 E2E（automate 域 FirmwarePackage + FirmwareUpgradePlan，补完"固件升级/值班"对）。

用法: python scripts/verify_firmware.py [BASE]
默认 BASE=http://127.0.0.1:8010/api/v1 (sqlite, NOPS_EAGER=1 内联任务)；容器 PG: http://127.0.0.1:8000/api/v1
前置: init_nops_data；admin/nops@2025、sys_demo/NopsTest@2025(automate.run.view)、
      net_demo/NopsTest@2025(无 automate)、auditor/NopsTest@2025(仅审计)
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
sysu = login("sys_demo", "NopsTest@2025")     # automate.run.view（可读不可实施）
net = login("net_demo", "NopsTest@2025")      # 无 automate.*
aud = login("auditor", "NopsTest@2025")

# ---- 预清理（幂等重跑）----
_, dv = call("GET", "/cmdb/devices/?search=FW-&page_size=100", admin)
for d in dv.get("results", []):
    call("POST", f"/cmdb/devices/{d['id']}/purge/?confirm=1", admin)
_, pkgs = call("GET", "/automate/firmware-packages/?search=FW-&page_size=100", admin)
for p in pkgs.get("results", []):
    call("DELETE", f"/automate/firmware-packages/{p['id']}/", admin)

_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]

# ---- 权限读门 ----
s, _ = call("GET", "/automate/firmware-packages/", sysu)
check("F1 sys_demo 读固件库 200", s == 200, s)
s, _ = call("GET", "/automate/firmware-packages/", net)
check("F2 net_demo 读固件库 403", s == 403, s)
s, _ = call("GET", "/automate/firmware-upgrades/", aud)
check("F3 auditor 读升级计划 403", s == 403, s)

# ---- 固件包 ----
s, pkg = call("POST", "/automate/firmware-packages/", admin, {
    "name": f"FW-PKG-{TS}", "vendor": "H3C", "hw_model": "S5130",
    "version": "R6628", "file_name": "S5130E-CMW710-R6628.bin",
    "file_size": 123456, "sha256": "a" * 64, "notes": "回归固件包"})
check("F4 建固件包", s == 201 and pkg.get("version") == "R6628", str(pkg)[:160])
pkg_id = pkg["id"]
s, _ = call("POST", "/automate/firmware-packages/", admin, {
    "name": f"FW-PKG-{TS}", "vendor": "H3C", "version": "R6628"})
check("F5 同名包重复 -> 400", s == 400, s)

# ---- 设备与计划 ----
s, dev = call("POST", "/cmdb/devices/", admin, {
    "name": f"FW-DEV-{TS}", "vendor": "H3C", "model": base["model"],
    "site": base["site"], "region": base["region"],
    "driver_type": "h3c_comware", "manage_ip": f"198.51.{int(TS) % 240}.{int(TS[4:6]) % 250 + 1}"})
check("F6 造临时设备", s == 201, str(dev)[:140])
did = dev["id"]

s, plan = call("POST", "/automate/firmware-upgrades/", admin,
               {"device_id": did, "package_id": pkg_id, "current_version": "R6608"})
check("F7 建升级计划(快照+设备名)", s == 201
      and plan.get("package_name_snapshot") == pkg["name"]
      and plan.get("package_version_snapshot") == "R6628"
      and plan.get("status") == "pending" and plan.get("device_name"), str(plan)[:180])
pid = plan["id"]
s, _ = call("POST", "/automate/firmware-upgrades/", sysu,
            {"device_id": did, "package_id": pkg_id})
check("F8 无 execute 权限建计划 -> 403", s == 403, s)
s, _ = call("POST", "/automate/firmware-upgrades/", admin,
            {"device_id": did, "package_id": pkg_id})
check("F9 同设备进行中计划重复 -> 400", s == 400, s)

# ---- 执行（mock 演练 / confirm 门禁 / 权限）----
s, r = call("POST", f"/automate/firmware-upgrades/{pid}/execute/", admin, {"mock": 1})
check("F10 缺 confirm 拒绝", s == 400, str(r)[:120])
s, _ = call("POST", f"/automate/firmware-upgrades/{pid}/execute/", sysu,
            {"mock": 1, "confirm": True})
check("F11 无 execute 权限执行 -> 403", s == 403, s)
s, r = call("POST", f"/automate/firmware-upgrades/{pid}/execute/", admin,
            {"mock": 1, "confirm": True})
# 容器环境为异步队列（automate.* -> ssh），轮询至终态再断言
plan_status, waited = r.get("status"), 0
while plan_status in ("pending", "running") and waited < 60:
    time.sleep(0.5)
    waited += 1
    plan_status = call("GET", f"/automate/firmware-upgrades/{pid}/", admin)[1].get("status")
check("F12 mock 演练执行成功", s == 200 and plan_status == "success",
      f"status={plan_status} waited={waited}s")
_, pl = call("GET", f"/automate/firmware-upgrades/{pid}/", admin)
check("F13 结果回显含 mock 演练日志", "[mock]" in (pl.get("result_log") or "")
      and pl.get("executed_at"), str(pl.get("result_log"))[:150])

s, r = call("POST", f"/automate/firmware-upgrades/{pid}/cancel/", admin, {})
check("F14 success 态不可取消 -> 400", s == 400, str(r)[:120])

# ---- 真实预检（无凭据 -> failed，不触网）----
s, plan2 = call("POST", "/automate/firmware-upgrades/", admin,
                {"device_id": did, "package_id": pkg_id, "current_version": "R6608"})
pid2 = plan2["id"]
s, r = call("POST", f"/automate/firmware-upgrades/{pid2}/execute/", admin,
            {"mock": 0, "confirm": True})
st2, waited2 = r.get("status"), 0
while st2 in ("pending", "running") and waited2 < 60:
    time.sleep(0.5)
    waited2 += 1
    st2 = call("GET", f"/automate/firmware-upgrades/{pid2}/", admin)[1].get("status")
_, pl2 = call("GET", f"/automate/firmware-upgrades/{pid2}/", admin)
check("F15 真实预检无凭据 -> failed 并提示", s == 200 and st2 == "failed"
      and "凭据" in (pl2.get("error") or ""),
      str({k: pl2.get(k) for k in ("status", "error")})[:160])

# ---- 取消 pending ----
s, plan3 = call("POST", "/automate/firmware-upgrades/", admin,
                {"device_id": did, "package_id": pkg_id})
pid3 = plan3["id"]
s, r = call("POST", f"/automate/firmware-upgrades/{pid3}/cancel/", admin,
            {"reason": "窗口调整"})
check("F16 取消 pending 计划", s == 200 and r.get("status") == "cancelled", str(r)[:120])
s, _ = call("POST", f"/automate/firmware-upgrades/{pid3}/cancel/", admin)
check("F17 已取消再取消 -> 400", s == 400, s)

# ---- 汇总 ----
s, sumr = call("GET", "/automate/firmware-upgrades/summary/", admin)
counts = sumr.get("counts", {})
check("F18 总览含 success/cancelled/failed 计数", s == 200
      and counts.get("success", 0) >= 1 and counts.get("cancelled", 0) >= 1
      and counts.get("failed", 0) >= 1, str(counts)[:160])

# ---- 清理：purge 设备清计划 + 删除包 ----
call("POST", f"/cmdb/devices/{did}/purge/?confirm=1", admin)
_, plans = call("GET", f"/automate/firmware-upgrades/?device_id={did}&page_size=100", admin)
check("F19 purge 清该设备升级计划", plans.get("count", 0) == 0, str(plans.get("count")))
s, _ = call("DELETE", f"/automate/firmware-packages/{pkg_id}/", admin)
check("F20 删除固件包", s == 204, s)

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
