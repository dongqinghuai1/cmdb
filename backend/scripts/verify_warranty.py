"""保修到期提醒收尾 E2E：warranty-expiring 清单口径 + warranty-notify dry 触发
（30/60/90/180 汇总、行内容、dry 幂等、execute 写门负例、清理）。

用法: python scripts/verify_warranty.py [BASE]
默认 sqlite 8010；容器 PG: http://127.0.0.1:8000/api/v1
前置: init_nops_data；net_demo=cmdb.device.view 无 execute（负例）。
"""
import datetime as dt
import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010/api/v1")
ok = fail = 0
TS = dt.datetime.now().strftime("%H%M%S")


def call(method, path, tok=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def check(name, cond, extra=""):
    global ok, fail
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra)[:170] if not cond else ""))
    globals()["ok" if cond else "fail"] += 1


admin = call("POST", "/auth/login/", body={"username": "admin", "password": "nops@2025"})[1]["access"]
net = call("POST", "/auth/login/", body={"username": "net_demo", "password": "NopsTest@2025"})[1]["access"]
NAME = "W-T-" + TS

# 清理同前缀残留
_, olds = call("GET", "/cmdb/devices/?search=W-T-", admin)
for d in olds.get("results", []):
    call("DELETE", f"/cmdb/devices/{d['id']}/?hard=1", admin)

_, ml = call("GET", "/cmdb/models/", admin)
sw = next(m["id"] for m in ml["results"] if m["code"] == "switch")
_, rg = call("GET", "/dcim/regions/?search=cn-east", admin)
_, st2 = call("GET", "/dcim/sites/?search=idc-sh", admin)
until = (dt.date.today() + dt.timedelta(days=10)).isoformat()
_, dev = call("POST", "/cmdb/devices/", admin,
              {"name": NAME, "model": sw, "vendor": "T", "region": rg["results"][0]["id"],
               "site": st2["results"][0]["id"], "warranty_until": until})
check("W1 建临保设备(+10 天)", dev.get("id") and dev.get("warranty_until") == until, dev)

_, snap = call("GET", "/cmdb/devices/warranty-expiring/?within_days=30", admin)
row = next((r for r in snap.get("rows", []) if r.get("id") == dev.get("id")), None)
check("W2 30 天内清单含本设备 days_left=10", row is not None and row.get("days_left") == 10,
      row)
check("W3 summary.30 口径含本设备", snap.get("summary", {}).get("30", 0) >= 1,
      snap.get("summary"))

_, r1 = call("POST", "/cmdb/devices/warranty-notify/", admin,
             {"within_days": 30, "dry": 1})
ch1 = r1.get("channels", [])
check("W4 dry 触发返回汇总+清单+渠道(dry=True)", r1.get("summary", {}).get("30", 0) >= 1
      and next((r for r in r1.get("rows", []) if r.get("id") == dev.get("id")), None)
      and all(c.get("dry") is True for c in ch1), str(r1)[:200])
_, r2 = call("POST", "/cmdb/devices/warranty-notify/", admin,
             {"within_days": 30, "dry": 1})
check("W5 dry 幂等(无新增行/DB 无副作用)", len(r2.get("rows", [])) == len(r1.get("rows", [])),
      (len(r2.get("rows", [])), len(r1.get("rows", []))))

# 写门：net_demo 可读(execute 门禁前需 device.view) 但无 cmdb.device.execute → 403
st, _ = call("GET", "/cmdb/devices/warranty-expiring/?within_days=30", net)
check("W6 net_demo 只读 GET 200", st == 200, st)
st, rn = call("POST", "/cmdb/devices/warranty-notify/", net, {"dry": 1})
check("W7 net_demo 触发 notify 403", st == 403, (st, rn))

# 清理
if dev.get("id"):
    call("DELETE", f"/cmdb/devices/{dev['id']}/?hard=1", admin)
_, snap2 = call("GET", "/cmdb/devices/warranty-expiring/?within_days=30", admin)
check("W8 清理后清单不再含本设备",
      not any(r.get("id") == dev.get("id") for r in snap2.get("rows", [])))
print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
