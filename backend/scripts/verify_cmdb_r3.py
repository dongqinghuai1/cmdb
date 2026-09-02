"""CMDB 基础补齐 R3 回归：TechSnapshot(ACL/IPSec) 建模——写入/越权/tech 透出/最新快照语义。
用法: python scripts/verify_cmdb_r3.py [BASE]   （只读账号可用 NOPS_RO_USER 覆盖）
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


def call(method, path, tok=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=20) as r:
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
ro_user = os.environ.get("NOPS_RO_USER", "op_low")
op = login(ro_user, "NopsTest@2025")

_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
bid = lst["results"][0]["id"]

# W1 越权
s, _ = call("POST", f"/cmdb/devices/{bid}/tech-snapshot/", op, {"kind": "acl", "payload": {}})
check("W1 只读用户写快照 -> 403", s == 403, str(s))
# W2 参数校验
s, _ = call("POST", f"/cmdb/devices/{bid}/tech-snapshot/", admin, {"kind": "nope", "payload": {}})
check("W2 非法 kind -> 400", s == 400, str(s))
s, _ = call("POST", f"/cmdb/devices/{bid}/tech-snapshot/", admin, {"kind": "acl", "payload": []})
check("W3 payload 非对象 -> 400", s == 400, str(s))
# W4/W5 写入 + 最新覆盖语义
acl1 = {"policies": [{"name": "permit_ssh", "action": "permit", "hits": 1234},
                     {"name": "deny_all", "action": "deny", "hits": 5}]}
s, snap1 = call("POST", f"/cmdb/devices/{bid}/tech-snapshot/", admin,
                {"kind": "acl", "payload": acl1})
check("W4 写 ACL 快照", s == 201 and snap1.get("kind") == "acl", str(snap1)[:120])
acl2 = {"policies": [{"name": "permit_ssh", "action": "permit", "hits": 2000}]}
s, _ = call("POST", f"/cmdb/devices/{bid}/tech-snapshot/", admin, {"kind": "acl", "payload": acl2})
s, t = call("GET", f"/cmdb/devices/{bid}/tech/", admin)
ext = t.get("extensions", {}).get("acl", {})
check("W5 tech 透出最新快照", ext.get("supported") is True and ext.get("payload") == acl2,
      str(ext)[:200])
# W6 ipsec 仍为占位
s, t = call("GET", f"/cmdb/devices/{bid}/tech/", admin)
ipx = t.get("extensions", {}).get("ipsec", {})
check("W6 ipsec 未写前为占位", ipx.get("supported") is False and "note" in ipx, str(ipx)[:120])
s, t = call("GET", f"/cmdb/devices/{bid}/tech/", op)
check("W7 只读用户可见快照透出", t.get("extensions", {}).get("acl", {}).get("supported") is True, str(s))

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
