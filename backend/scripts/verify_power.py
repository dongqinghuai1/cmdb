"""PDU 电源 E2E：SNMP mock 走查纯函数 / 建 PDU 设备(额定) / mock 轮询写实测 /
总览(利用率+总功率+超阈值) / 历史样本 / 权限正负例 / purge 联动清理。

用法: python scripts/verify_power.py [BASE]
默认 sqlite 8010；容器 PG: http://127.0.0.1:8000/api/v1
前置: init_nops_data（dcim.power.view/edit 授权；pdu/ups 模型预置）；
admin/nops@2025、dcim_demo/NopsTest@2025(power view+edit)、
net_demo/NopsTest@2025(power view)、auditor/NopsTest@2025(无 power)。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # backend 根
os.environ.setdefault("NOPS_DB", "sqlite")

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


# P1 纯函数（无网络/无 Django ORM）：snmp.collect_pdu mock 演练 seam
from apps.cmdb import snmp as S  # noqa: E402  —— 顶层仅 stdlib，可独立导入
_pdu = S.collect_pdu("127.0.0.1", "public", mock=True)
P1 = len(_pdu.get("outlets", [])) >= 2 and all(
    "watts" in o and "current_a" in o and "voltage_v" in o for o in _pdu["outlets"])
check("P1 collect_pdu mock 返回 2+ 输出口(功率/电流/电压)", P1, _pdu)
P2 = False
try:
    S.collect_pdu("127.0.0.1", "public", mock=False)
except S.RequiresCalibration:
    P2 = True
check("P2 真实模板未校准主动 raise RequiresCalibration", P2)

admin = login("admin", "nops@2025")
dcim = login("dcim_demo", "NopsTest@2025")
net = login("net_demo", "NopsTest@2025")
aud = login("auditor", "NopsTest@2025")

# ---- 预清理 ----
_, dv = call("GET", "/cmdb/devices/?search=PWR-&page_size=100", admin)
for d in dv.get("results", []):
    call("POST", f"/cmdb/devices/{d['id']}/purge/?confirm=1", admin)

# 找 pdu 模型
_, models = call("GET", "/cmdb/models/?page_size=200", admin)
pm = next((m for m in models.get("results", []) if m.get("code") == "pdu"), None)
if not pm:
    pm = models["results"][0]
_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]


def mk_pdu(name, rated):
    s, r = call("POST", "/cmdb/devices/", admin, {
        "name": name, "vendor": "PDU-Test", "model": pm["id"], "site": base["site"],
        "region": base["region"], "driver_type": "",
        "rated_power_w": rated})
    return s, r


s, pdu1 = mk_pdu(f"PWR-A-{TS}", 3000)
s2, pdu2 = mk_pdu(f"PWR-B-{TS}", 2400)
check("S1 建 2 台 PDU 设备(额定 3000/2400W)", s == 201 and s2 == 201, (s, s2))
p1, p2 = pdu1["id"], pdu2["id"]

# ---- 读门 ----
s, _ = call("GET", "/dcim/power-samples/summary/", net)
check("S2 net_demo(view) 读汇总 200", s == 200, s)
s, _ = call("GET", "/dcim/power-samples/summary/", aud)
check("S3 auditor 读汇总 403", s == 403, s)
s, _ = call("GET", "/dcim/power-samples/?device_id=%d" % p1, aud)
check("S4 auditor 读样本 403", s == 403, s)

# ---- mock 轮询（SNMP 演练 seam → dcim_powersample） ----
s, r = call("POST", "/dcim/power-samples/poll/", dcim, {"mock": 1})
applied = r.get("applied", 0)
check("S5 dcim_demo mock 轮询写入样例", s == 200 and applied >= 2
      and all(x.get("watts") for x in r.get("detail", [])), str(r)[:200])
s, r = call("POST", "/dcim/power-samples/poll/", net, {"mock": 1})
check("S6 net_demo(view) 轮询 -> 403（写需 edit）", s == 403, s)

# 样本数（每台 2 outlet → >=2）
_, sm = call("GET", f"/dcim/power-samples/?device_id={p1}&page_size=50", net)
check("S7 PDU-A 历史样本 2 条(PDU-A1/PDU-B1)", sm.get("count", 0) >= 2, sm.get("count"))
_, sm = call("GET", f"/dcim/power-samples/?device_id={p2}&page_size=50", net)
check("S8 PDU-B 历史样本 2 条", sm.get("count", 0) >= 2, sm.get("count"))

# ---- 汇总（最近实测/利用率/总功率；同刻多输出口取末行=每台 B1 口） ----
_, su = call("GET", "/dcim/power-samples/summary/", dcim)
items = {i["device_id"]: i for i in su.get("items", [])}
a, b = items.get(p1), items.get(p2)
check("S9 汇总含两台最近实测(源 snmp)", su.get("devices", 0) >= 2 and a and b
      and a.get("watts") == 2480 and b.get("watts") == 2480
      and a.get("source") == "snmp", str(su)[:220])
check("S10 利用率=功率/额定(2480/3000=82.7%、2480/2400=103.3%)", a and b
      and abs((a.get("utilization_pct") or 0) - 82.7) < 0.6
      and abs((b.get("utilization_pct") or 0) - 103.3) < 0.6, (a and a.get("utilization_pct"), b and b.get("utilization_pct")))
check("S11 总功率 4960W 且两台均超阈值(≥80%)", su.get("total_watts") == 4960.0
      and su.get("over_threshold", 0) >= 2, su.get("total_watts"))

# ---- 更新额定后重新轮询（新样本按新额定快照重算利用率） ----
s, _ = call("PATCH", f"/cmdb/devices/{p1}/", admin, {"rated_power_w": 3500})
_, _rp = call("POST", "/dcim/power-samples/poll/", dcim, {"mock": 1})
_, su2 = call("GET", "/dcim/power-samples/summary/", net)
a2 = next((i for i in su2.get("items", []) if i["device_id"] == p1), None)
check("S12 额定 3000→3500 后重采样利用率回落 70.9%(2480/3500)", s == 200 and _rp.get("applied", 0) >= 2 and a2
      and abs((a2.get("utilization_pct") or 0) - 70.9) < 0.6, a2)

# ---- 无 edit 权限者建不了，purge 联动清样本 ----
s, _ = call("POST", f"/cmdb/devices/{p1}/purge/?confirm=1", admin)
s2, _ = call("POST", f"/cmdb/devices/{p2}/purge/?confirm=1", admin)
_, sm = call("GET", f"/dcim/power-samples/?device_id={p1}&page_size=50", net)
_, sm2 = call("GET", f"/dcim/power-samples/?device_id={p2}&page_size=50", net)
check("S13 purge 设备联动清除电源样本", s in (200, 204) and s2 in (200, 204)
      and sm.get("count", 0) == 0 and sm2.get("count", 0) == 0, (sm.get("count"), sm2.get("count")))

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
