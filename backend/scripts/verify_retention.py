"""TechSnapshot 保留策略回归：多快照写入/权限门禁(execute+confirm)/keep 保留最新/幂等。
用法: python scripts/verify_retention.py [BASE]
"""
import json
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


def call(method, path, tok=None, body=None, q=""):
    req = urllib.request.Request(BASE + path + (("?" + q) if q else ""), method=method)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=25) as r:
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
    raise SystemExit(f"login fail {u}: {s} {r}")


admin = login("admin", "nops@2025")
mgr = login("mgr_approver", "NopsTest@2025")

_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]


def pk(x):
    return x if isinstance(x, int) else x.get("id")


s, td = call("POST", "/cmdb/devices/", admin, {
    "name": f"保留策略测试-{TS[:6]}", "vendor": "V",
    "model": pk(base["model"]), "site": pk(base["site"]), "region": pk(base["region"])})
check("R0 造临时设备", s == 201, str(td)[:120])
tid = td["id"]

for i in range(7):
    s, _ = call("POST", f"/cmdb/devices/{tid}/tech-snapshot/", admin,
                {"kind": "acl", "payload": {"rows": [{"marker": i}], "count": 1}})
check("R1 写 7 条快照", s == 201, str(s))
_, t = call("GET", f"/cmdb/devices/{tid}/tech/", admin)
check("R2 最新透出 marker=6", t.get("extensions", {}).get("acl", {}).get("payload", {}).get("rows", [{}])[0].get("marker") == 6,
      str(t)[:200])

s, r = call("POST", "/cmdb/devices/tech-retention/", mgr, {"keep": 3})
check("R3 非超管无 confirm -> 400", s == 400, str(r)[:120])
s, r = call("POST", "/cmdb/devices/tech-retention/?confirm=1", mgr, {"keep": 3})
check("R4 execute+confirm 执行 keep=3", s == 200 and r.get("removed") == 4 and r.get("keep") == 3,
      str(r)[:160])
_, t = call("GET", f"/cmdb/devices/{tid}/tech/", admin)
rows = t.get("extensions", {}).get("acl", {}).get("payload", {}).get("rows", [])
check("R5 保留最新 3 条(最新仍 marker=6)", len(rows) == 1 and rows[0].get("marker") == 6
      and t.get("extensions", {}).get("acl", {}).get("supported") is True, str(t)[:200])
s, r = call("POST", "/cmdb/devices/tech-retention/?confirm=1", mgr, {"keep": 3})
check("R6 再次执行幂等(removed=0)", s == 200 and r.get("removed") == 0, str(r)[:120])
s, r = call("POST", "/cmdb/devices/tech-retention/?confirm=1", mgr, {"keep": "x"})
check("R7 非法 keep -> 400", s == 400, str(s))

call("DELETE", f"/cmdb/devices/{tid}/", admin)
call("POST", f"/cmdb/devices/{tid}/purge/?confirm=1", admin)
s, r = call("POST", "/cmdb/devices/tech-retention/?confirm=1", admin, {"keep": 3})
check("R8 purge 后全量清理仍正常", s == 200 and isinstance(r.get("removed"), int), str(r)[:120])

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
