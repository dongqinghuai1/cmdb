"""Prometheus 接入回归：只读权限/mock 拉取落 DeviceInterfaceStat/webhook 贯通(created/去重/resolved)。
用法: python scripts/verify_prom.py [BASE]
服务端需带 NOPS_PROM_WEBHOOK_TOKEN=testtok 启动（否则 webhook 不鉴权，测试同样可过）。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

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


def call(method, path, tok=None, body=None, q="", headers=None):
    req = urllib.request.Request(BASE + path + (("?" + q) if q else ""), method=method)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
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
    raise SystemExit(f"login fail {u}")


admin = login("admin", "nops@2025")
ro = login(os.environ.get("NOPS_RO_USER", "op_low"), "NopsTest@2025")

_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]

s, td = call("POST", "/cmdb/devices/", admin, {
    "name": f"Prom回归-{TS[:6]}", "vendor": "Linux",
    "model": base["model"], "site": base["site"], "region": base["region"],
    "driver_type": "linux", "manage_ip": "10.200.210.10"})
check("P1 造临时设备", s == 201, str(td)[:100])
tid = td["id"]

# 先铺一个接口（prom 写入按 device 首个接口）
s, _ = call("POST", f"/cmdb/devices/{tid}/snmp-test/", admin, {"mock": 1})

s, r = call("POST", f"/cmdb/devices/{tid}/prom-test/", ro, {"mock": 1})
check("P2 只读触发 -> 403", s == 403, str(s))
s, r = call("POST", f"/cmdb/devices/{tid}/prom-test/", admin, {"mock": 1})
samples = r.get("samples") or {}
check("P3 mock 拉取写入 stat",
      s == 200 and r.get("applied") is True
      and samples.get("in_bps") == 1234000, str(r)[:180])

# 未配 NOPS_PROM_URL 时 mock=0 → 400 提示
s, r = call("POST", f"/cmdb/devices/{tid}/prom-test/", admin, {"mock": 0})
if os.getenv("NOPS_PROM_URL"):
    check("P4 真拉取(环境已配)", s == 200, str(s))
else:
    check("P4 未配 URL -> 400 提示", s == 400 and "NOPS_PROM_URL" in r.get("detail", ""),
          str(r)[:140])

# webhook：firing → created；同 key firing → updated；resolved → resolved
wh = "/alerts/webhook/prometheus/"


def fire(status="firing", extra=None):
    a = {"status": status,
         "labels": {"alertname": "IfDown", "instance": "10.200.210.10",
                    "severity": "critical"},
         "annotations": {"summary": "接口 down: eth0"}}
    if extra:
        a.update(extra)
    return a


s, r = call("POST", wh, body={"status": "firing", "alerts": [fire()]},
            headers={"X-Webhook-Token": "testtok"})
check("P5 webhook 首报 created=1(命中设备)",
      s == 200 and r.get("created") == 1, str(r)[:160])
s, r = call("POST", wh, body={"status": "firing", "alerts": [fire()]},
            headers={"X-Webhook-Token": "testtok"})
check("P6 同 key 重复 firing updated=1 不重复建", s == 200 and r.get("updated") == 1, str(r)[:120])
s, r = call("POST", wh, body={"status": "firing", "alerts": [fire(extra={
    "labels": {"alertname": "IfDown",
               "instance": f"10.200.{__import__('uuid').uuid4().int % 250}.{__import__('uuid').uuid4().int % 250}",
               "severity": "warning"}})]},
            headers={"X-Webhook-Token": "testtok"})
check("P7 未命中设备 created=1(device 0)", s == 200 and r.get("created") == 1, str(r)[:120])
s, r = call("POST", wh, body={"status": "firing", "alerts": [fire()]},
            headers={"X-Webhook-Token": "bad"})
check("P8 webhook 错误 token -> 403", s == 403, str(s))
s, r = call("POST", wh, body={"status": "resolved", "alerts": [fire(status="resolved")]},
            headers={"X-Webhook-Token": "testtok"})
check("P9 resolved 关闭 firing -> 1", s == 200 and r.get("resolved") == 1, str(r)[:120])

# 事件落库可见（events 列表含 summary）
s, ev = call("GET", "/alerts/events/?page_size=100&ordering=-id", admin)
titles = [x.get("title", "") for x in ev.get("results", [])]
check("P10 AlertEvent 落库可见", s == 200 and any("eth0" in t for t in titles),
      str(titles[:3])[:140])

# 清理
call("DELETE", f"/cmdb/devices/{tid}/", admin)
call("POST", f"/cmdb/devices/{tid}/purge/?confirm=1", admin)

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
