"""vCenter 虚机同步 E2E：源 CRUD / mock 拉取 → cmdb.Device(虚机) upsert(幂等) /
收敛软删与恢复 / 真实模式校准提示 / 权限正负例 / 删源保留虚机记录。

用法: python scripts/verify_vcenter.py [BASE]
默认 sqlite 8010；容器 PG: http://127.0.0.1:8000/api/v1
前置: init_nops_data（cmdb.vmware.view/edit + vm 模型预置）；
admin/nops@2025、sys_demo(NopsTest@2025, vmware view+edit)、
net_demo(NopsTest@2025, vmware view)、auditor(NopsTest@2025, 无)。
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
sysu = login("sys_demo", "NopsTest@2025")
net = login("net_demo", "NopsTest@2025")
aud = login("auditor", "NopsTest@2025")

# ---- 预清理 ----
_, sv = call("GET", "/cmdb/vmware-sources/?search=VC-&page_size=100", admin)
for s in sv.get("results", []):
    call("DELETE", f"/cmdb/vmware-sources/{s['id']}/", admin)
_, dv = call("GET", f"/cmdb/devices/?search=VC-{TS}&is_virtual=1&page_size=100", admin)
for d in dv.get("results", []):
    call("POST", f"/cmdb/devices/{d['id']}/purge/?confirm=1", admin)
# 历史回退名遗留（旧版 pull 空名单用 vc-demo 前缀）
_, dvx = call("GET", "/cmdb/devices/?search=vc-demo&is_virtual=1&page_size=100", admin)
for d in dvx.get("results", []):
    call("POST", f"/cmdb/devices/{d['id']}/purge/?confirm=1", admin)

_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]
NAME = f"VC-{TS}"

# ---- 权限读门 + 建源负例 ----
s, _ = call("GET", "/cmdb/vmware-sources/", net)
check("V1 net_demo(view) 读源 200", s == 200, s)
s, _ = call("GET", "/cmdb/vmware-sources/", aud)
check("V2 auditor 读源 403", s == 403, s)
s, _ = call("POST", "/cmdb/vmware-sources/", net, {"name": f"VC-N-{TS}", "host": "vc.mock"})
check("V3 net_demo 建源 -> 403(需 edit)", s == 403, s)

s, src = call("POST", "/cmdb/vmware-sources/", sysu, {
    "name": NAME, "host": "vc001.mock.local", "username": "administrator@vsphere.local",
    "secret": "NopsTest@2025", "site_id": base["site"], "region_id": base["region"],
    "mock_vms": [], "remark": "回归源"})
sid = src.get("id")
check("V4 sys 建 vCenter 源(host/账号加密存)", s == 201 and sid and "secret" not in src,
      str(src)[:170])
s, _ = call("GET", f"/cmdb/vmware-sources/{sid}/", net)
check("V5 net 读单源 200", s == 200, s)

# ---- mock 同步 → Device upsert ----
s, r = call("POST", f"/cmdb/vmware-sources/{sid}/sync/", sysu, {"mock": 1})
check("V6 首轮 mock 同步创建 2 台虚机", s == 200 and r.get("created") == 2
      and r.get("removed") == 0, str(r)[:200])
_, devs = call("GET", f"/cmdb/devices/?search={NAME}&is_virtual=1&page_size=100", admin)
marks = {d["name"]: d for d in devs.get("results", [])}
w, d0 = marks.get(f"{NAME}-web-01"), marks.get(f"{NAME}-db-01")
check("V7 虚机落库为 Device(vm_source=vcenter:pk, vm_uuid, attrs, 电源态)", len(marks) == 2 and w and d0
      and w.get("vm_source") == f"vcenter:{sid}" and len(w.get("vm_uuid") or "") == 32
      and w.get("attrs", {}).get("cluster") == "MOCK-CLUSTER"
      and w.get("online_status") == "online" and d0.get("online_status") == "offline",
      str(marks.keys()))
s, r2 = call("POST", f"/cmdb/vmware-sources/{sid}/sync/", sysu, {"mock": 1})
check("V8 二次同步幂等(created 0/removed 0)", r2.get("created") == 0
      and r2.get("updated") == 0 and r2.get("removed") == 0, str(r2)[:160])

# ---- 收敛软删 + 恢复 ----
s, _ = call("PATCH", f"/cmdb/vmware-sources/{sid}/", sysu,
            {"mock_vms": [f"{NAME}-web-01"]})
s, r3 = call("POST", f"/cmdb/vmware-sources/{sid}/sync/", sysu, {"mock": 1})
_, devs3 = call("GET", f"/cmdb/devices/?search={NAME}&is_virtual=1&page_size=100", admin)
check("V9 收敛：不在清单 db-01 被软删(可见仅 web-01)", s == 200 and r3.get("removed", 0) >= 1
      and len(devs3.get("results", [])) == 1, str(r3)[:160])
s, _ = call("PATCH", f"/cmdb/vmware-sources/{sid}/", sysu, {"mock_vms": []})
s, r4 = call("POST", f"/cmdb/vmware-sources/{sid}/sync/", sysu, {"mock": 1})
_, devs4 = call("GET", f"/cmdb/devices/?search={NAME}&is_virtual=1&page_size=100", admin)
check("V10 恢复名单后 db-01 复活(可见 2 台)", (r4.get("created", 0) + r4.get("resurrected", 0)) >= 1
      and len(devs4.get("results", [])) == 2, str(r4)[:160])

# ---- 真实模式（依赖未装 → 校准提示，不写假数据） ----
s, r5 = call("POST", f"/cmdb/vmware-sources/{sid}/sync/", sysu, {"mock": 0})
_, devs5 = call("GET", f"/cmdb/devices/?search={NAME}&is_virtual=1&page_size=100", admin)
check("V11 真实拉取未校准提示且不落数据", s == 200 and r5.get("calibration") is True
      and len(devs5.get("results", [])) == 2, str(r5)[:160])
s, _ = call("POST", f"/cmdb/vmware-sources/{sid}/sync/", net, {"mock": 1})
check("V12 net sync -> 403(写需 edit)", s == 403, s)

# ---- 删源保留虚机记录；随后清理设备 ----
s, _ = call("DELETE", f"/cmdb/vmware-sources/{sid}/", sysu)
_, devs6 = call("GET", f"/cmdb/devices/?search={NAME}&is_virtual=1&page_size=100", admin)
check("V13 删除同步源后虚机记录保留", s in (200, 204)
      and len(devs6.get("results", [])) == 2, len(devs6.get("results", [])))
for d in devs6.get("results", []):
    call("POST", f"/cmdb/devices/{d['id']}/purge/?confirm=1", admin)
_, devs7 = call("GET", f"/cmdb/devices/?search={NAME}&is_virtual=1&page_size=100", admin)
check("V14 清理虚机(purge 物理删)", len(devs7.get("results", [])) == 0,
      len(devs7.get("results", [])))

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
