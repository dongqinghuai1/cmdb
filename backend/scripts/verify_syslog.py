"""Syslog E2E: hostname映射 -> UDP发包 -> 检索 -> 关键字告警规则 -> 评估 -> 事件。"""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

B = "http://localhost:8000/api/v1"
ok = fail = 0


def call(method, path, tok=None, body=None):
    req = urllib.request.Request(B + path, method=method)
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
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra)[:160] if not cond else ""))
    globals()["ok" if cond else "fail"] += 1


tok = call("POST", "/auth/login/", body={"username": "admin", "password": "nops@2025"})[1]["access"]

# 1. 给 SW-CORE-01 设置 hostname（syslog 设备映射锚点）
_, dv = call("GET", "/cmdb/devices/?search=SW-CORE-01", tok)
dev = dv["results"][0]
call("PATCH", "/cmdb/devices/" + str(dev["id"]) + "/", tok, {"hostname": "SW-CORE-01"})

# 2. 发送 RFC3164 UDP syslog：一条 OSPF down（严重）+ 一条普通 info + 一条未知主机
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
packets = [
    b"<187>Aug 20 21:00:01 SW-CORE-01 %%01OSPF/3/NBR_DOWN(l): Neighbor 10.1.1.2 went Down (DeadTimer expired).",
    b"<190>Aug 20 21:00:05 SW-CORE-01 LINEPROTO-5-UPDOWN: Line protocol on Interface GE1/0/1, changed state to UP",
]
for p in packets:
    sock.sendto(p, ("127.0.0.1", 514))
# UDP 可能丢包：未知主机包多发几次
for _ in range(3):
    sock.sendto(b"<191>Aug 20 21:00:08 unknown-host some random message from nowhere",
                ("127.0.0.1", 514))
    time.sleep(0.3)
time.sleep(4)

# 3. 检索
st, logs = call("GET", "/monitor/logs/?severity_lte=7&page_size=20", tok)
rows = logs.get("results", [])
matched = [r for r in rows if "OSPF" in r.get("message", "")]
check("syslog received & searchable", len(rows) >= 3, (st, len(rows)))
check("device mapped by hostname", matched and matched[0]["device_id"] == dev["id"],
      matched[:1])
check("severity parsed (pri187=local7.error)", matched and matched[0]["severity"] == 3, matched[:1])
check("unknown host -> device null", any(r["device_id"] is None for r in rows), [r["device_id"] for r in rows])

# 4. 日志关键字告警规则
st, rule = call("POST", "/alerts/rules/", tok, {
    "name": "T-OSPF-Down", "rule_type": "log_keyword", "log_pattern": "OSPF.*Down",
    "severity": "critical", "for_duration_s": 600})
check("log rule created", st in (200, 201), (st, rule))

# 5. 同步执行一次评估（不等 beat 60s）
r = subprocess.run(["docker", "exec", "nops-api", "manage_eval"], capture_output=True)  # 占位
r = subprocess.run(["docker", "exec", "nops-api", "python", "-c",
                    "import sys; sys.path.insert(0,'/app'); import os;"
                    "os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');"
                    "import django; django.setup();"
                    "from apps.alert.engine import evaluate_alert_rules as t; print(t())"],
                   capture_output=True, text=True, timeout=120)
print("evaluate:", (r.stdout or r.stderr).strip()[:100])

# 6. 校验事件
st, evs = call("GET", "/alerts/events/?status=firing&page_size=20", tok)
hit = [e for e in evs.get("results", []) if e.get("device_id") == dev["id"]
       and "T-OSPF" in (e.get("title") or "")]
check("log keyword alert fired", len(hit) >= 1, evs.get("results", [])[:2])
if hit:
    check("alert detail has sample", "OSPF" in str(hit[0].get("detail", {})), hit[0].get("detail"))

# 7. 清理规则（事件保留演示）
call("DELETE", "/alerts/rules/" + str(rule.get("id", 0)) + "/", tok)

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
