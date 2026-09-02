"""CMDB 基础补齐 R2 回归：360 技术概览端点 / 动态分组预览不改成员 / 软件版本与 hw_model 过滤一致性。
用法: python scripts/verify_cmdb_r2.py [BASE]   （只读负例账号可用 NOPS_RO_USER 覆盖）
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
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
base = lst["results"][0]
bid = base["id"]

# ---------- T 360 技术概览 ----------
s, t = call("GET", f"/cmdb/devices/{bid}/tech/", admin)
keys = ["neighbors", "routes", "route_meta", "ap", "vlans", "sessions", "extensions"]
check("T1 tech 端点返回全部区块", s == 200 and all(k in t for k in keys), str(t)[:200])
check("T2 扩展入口含 acl/ipsec 说明", isinstance(t.get("extensions", {}).get("acl"), dict)
      and isinstance(t.get("extensions", {}).get("ipsec"), dict), str(t.get("extensions"))[:200])
check("T3 邻居/路由/会话为列表", isinstance(t.get("neighbors"), list)
      and isinstance(t.get("routes"), list) and isinstance(t.get("sessions"), list)
      and isinstance(t.get("vlans"), list))
s, t2 = call("GET", f"/cmdb/devices/{bid}/tech/", op)
check("T4 只读用户可看技术概览", s == 200 and all(k in t2 for k in keys), str(s))

# ---------- U 动态分组：预览不改成员 ----------
gname = f"R2分组-{TS}"
s, g = call("POST", "/cmdb/groups/", admin, {"name": gname, "group_type": "dynamic",
                                             "filter": {"vendor": base.get("vendor") or ""}})
check("U1 建动态分组", s == 201, str(g)[:150])
gid = g["id"]
s, ev = call("POST", f"/cmdb/groups/{gid}/evaluate/", admin, {"apply": True})
check("U2 应用规则", s == 200 and ev.get("applied", 0) >= 1, str(ev)[:120])
s, mem1 = call("GET", f"/cmdb/groups/{gid}/members/", admin)
s, ev2 = call("POST", f"/cmdb/groups/{gid}/evaluate/", admin, {"apply": False})
s, mem2 = call("GET", f"/cmdb/groups/{gid}/members/", admin)
check("U3 仅预览不改变成员", ev2.get("matched", -1) == mem1.get("count", -2)
      and mem1.get("count") == mem2.get("count"), f"pre={ev2.get('matched')} m1={mem1.get('count')} m2={mem2.get('count')}")
call("DELETE", f"/cmdb/groups/{gid}/", admin)

# ---------- V 软件版本 + hw_model 过滤一致性 ----------
s, sv = call("GET", "/cmdb/devices/software-summary/", admin)
grouped = {}
for r in sv:
    key = (r.get("vendor") or "", r.get("hw_model") or "")
    grouped.setdefault(key, []).append(r)
check("V1 版本分布可聚合", s == 200 and isinstance(sv, list) and len(grouped) >= 1,
      f"groups={len(grouped)}")
top = next(iter(grouped.items()))
(vendor, hw), rows = top
s, page = call("GET", "/cmdb/devices/?vendor=" + urllib.parse.quote(vendor) + "&hw_model="
               + urllib.parse.quote(hw) + "&page_size=500", admin)
total_dev = sum(r["c"] for r in rows)
check("V2 hw_model 过滤覆盖分布合计", s == 200 and page.get("count", 0) >= total_dev,
      f"filter={page.get('count')} summary={total_dev}")

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
