"""真实采集链路验证：可达IP->online(ping)、不可达IP->offline、VM指标落库。"""
import json
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

# 取 postgres 容器内网 IP（从 api 容器可达，作为"真实可达设备"替身）
ip = subprocess.run(["docker", "exec", "nops-api", "python", "-c",
                     "import socket; print(socket.gethostbyname('postgres'))"],
                    capture_output=True, text=True).stdout.strip()
check("got reachable target ip", bool(ip), ip)
print("target ip:", ip)

_, ml = call("GET", "/cmdb/models/", tok)
sw = next(m["id"] for m in ml["results"] if m["code"] == "switch")
_, rl = call("GET", "/dcim/regions/?search=cn-east", tok)
reg = rl["results"][0]["id"]
_, sl = call("GET", "/dcim/sites/?search=idc-sh", tok)
site = sl["results"][0]["id"]

# 清理旧测试设备
for nm in ["T-UP", "T-DOWN"]:
    _, lst = call("GET", "/cmdb/devices/?search=" + nm, tok)
    for d in lst.get("results", []):
        call("DELETE", "/cmdb/devices/" + str(d["id"]) + "/?hard=1", tok)

# 一台可达（ping 通）+ 一台不可达
call("POST", "/cmdb/devices/", tok, {"name": "T-UP", "model": sw, "vendor": "T",
                                     "manage_ip": ip, "region": reg, "site": site})
call("POST", "/cmdb/devices/", tok, {"name": "T-DOWN", "model": sw, "vendor": "T",
                                     "manage_ip": "203.0.113.99", "region": reg, "site": site})

# 触发全量采集并同步等待 worker 完成（两台，很快）
st, r = call("POST", "/monitor/collect/", tok, {})
check("collect triggered", st in (200, 201), (st, r))
time.sleep(12)

_, up = call("GET", "/cmdb/devices/?search=T-UP", tok)
_, down = call("GET", "/cmdb/devices/?search=T-DOWN", tok)
up_dev = up["results"][0]
down_dev = down["results"][0]
check("reachable device -> online", up_dev["online_status"] == "online", up_dev["online_status"])
check("unreachable device -> offline", down_dev["online_status"] == "offline", down_dev["online_status"])
check("last_seen_at set", bool(up_dev["last_seen_at"]), up_dev["last_seen_at"])

# VM 指标落库（用临时脚本文件避免 shell 引号问题）
vm_script = '''
import requests
r = requests.get("http://victoriametrics:8428/api/v1/query", params={"query": "device_up"}, timeout=5)
print(len(r.json()["data"]["result"]))
'''
with open("_vmq.py", "w") as f:
    f.write(vm_script)
subprocess.run(["docker", "cp", "_vmq.py", "nops-api:/tmp/_vmq.py"], capture_output=True)
vm = subprocess.run(["docker", "exec", "nops-api", "python", "/tmp/_vmq.py"],
                    capture_output=True, text=True).stdout.strip()
import os
os.remove("_vmq.py")
check("metrics in VictoriaMetrics", int(vm or 0) >= 2, vm)

# 清理
for nm in ["T-UP", "T-DOWN"]:
    _, lst = call("GET", "/cmdb/devices/?search=" + nm, tok)
    for d in lst.get("results", []):
        call("DELETE", "/cmdb/devices/" + str(d["id"]) + "/?hard=1", tok)

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
