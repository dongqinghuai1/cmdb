"""Silence + AP sync E2E."""
import json
import subprocess
import sys
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
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra)[:170] if not cond else ""))
    globals()["ok" if cond else "fail"] += 1


tok = call("POST", "/auth/login/", body={"username": "admin", "password": "nops@2025"})[1]["access"]


def evaluate():
    r = subprocess.run(["docker", "exec", "nops-api", "python", "-c",
                        "import sys; sys.path.insert(0,'/app'); import os;"
                        "os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');"
                        "import django; django.setup();"
                        "from apps.alert.engine import evaluate_alert_rules as t; print(t())"],
                       capture_output=True, text=True, timeout=120)
    return r.stdout.strip()


# ---- 1. AP 同步 ----
_, dv = call("GET", "/cmdb/devices/?search=AC-WLC-01", tok)
wlc = next((d for d in dv["results"]), None)
check("WLC device exists", wlc is not None, dv.get("results", [])[:1])
sample = """
AP Name             Slots  AP Model        MAC Address       Location Country IP Address  State
AP-F3-01            2      AIR-AP2802I     aabb.ccdd.ee01    default  CN      10.1.1.101  Up
AP-F3-02            2      AIR-AP2802I     aabb.ccdd.ee02    default  CN      10.1.1.102  Up
AP-F4-01            2      AIR-AP3802I     aabb.ccdd.ee03    default  CN      10.1.1.103  Down
Total Number of APs: 3
"""
st, r = call("POST", "/cmdb/devices/ap-sync/", tok, {"wlc": wlc["id"], "text": sample})
check("ap sync parsed", st == 200 and r.get("parsed") == 3
      and r.get("created") + r.get("updated") == 3, (st, r))
st, aps = call("GET", "/cmdb/devices/?search=AP-F3", tok)
check("ap devices created", aps.get("count", 0) >= 2, aps.get("count"))
# 幂等：再同步不新建
st, r2 = call("POST", "/cmdb/devices/ap-sync/", tok, {"wlc": wlc["id"], "text": sample})
check("ap sync idempotent", r2.get("created") == 0 and r2.get("updated") == 3, r2)
# ---- 2. 静默窗口 ----
_, dv2 = call("GET", "/cmdb/devices/?search=AP-F3-01", tok)
dev = dv2["results"][0]["id"]
# 制造离线设备
call("PATCH", "/cmdb/devices/" + str(dev) + "/", tok, {"online_status": "offline"})
st, rule = call("POST", "/alerts/rules/", tok, {"name": "T-Sil-Offline", "rule_type": "state",
                                                "metric": "offline", "severity": "major"})
print("baseline evaluate:", evaluate()[:80])

# 2.1 无静默 -> 触发
st, evs = call("GET", "/alerts/events/?status=firing&device_id=" + str(dev), tok)
check("alert fires before silence", evs.get("count", 0) >= 1, evs.get("count"))

# 2.2 静默该设备 -> 清掉事件再评估 -> 不再触发
call("POST", "/alerts/silences/", tok, {"scope": {"device_ids": [dev]}, "reason": "T-maint",
                                        "silence_type": "maintenance",
                                        "started_at": "2026-01-01T00:00:00Z",
                                        "ended_at": "2099-01-01T00:00:00Z"})
st, evs = call("GET", "/alerts/events/?status=firing&device_id=" + str(dev), tok)
for e in evs.get("results", []):
    call("PATCH", "/alerts/events/" + str(e["id"]) + "/", tok, {"status": "closed"})
evaluate()
st, evs2 = call("GET", "/alerts/events/?status=firing&device_id=" + str(dev), tok)
check("silenced device no new alert", evs2.get("count", 0) == 0, evs2.get("count"))

# 2.3 提前结束静默 -> 再评估 -> 重新触发
_, sils = call("GET", "/alerts/silences/?page_size=5", tok)
sid = next(s["id"] for s in sils["results"] if s["reason"] == "T-maint")
call("POST", "/alerts/silences/" + str(sid) + "/end/", tok)
evaluate()
st, evs3 = call("GET", "/alerts/events/?status=firing&device_id=" + str(dev), tok)
check("alert resumes after silence ends", evs3.get("count", 0) >= 1, evs3.get("count"))

# 清理
call("DELETE", "/alerts/rules/" + str(rule.get("id", 0)) + "/", tok)
call("DELETE", "/alerts/silences/" + str(sid) + "/", tok)
call("PATCH", "/cmdb/devices/" + str(dev) + "/", tok, {"online_status": "offline"})

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
