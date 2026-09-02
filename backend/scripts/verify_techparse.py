"""采集解析（tech-parse）回归：ACL/NAT/IPSec 预览/垃圾输入/越权/落库/tech 透出/总览聚合/清理。
用法: python scripts/verify_techparse.py [BASE]   （只读账号可用 NOPS_RO_USER 覆盖）
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

ACL_TXT = """ciscoasa# show access-list
access-list ACL-OUT extended permit tcp host 10.1.1.1 host 8.8.8.8 eq 443 (hitcnt=1234)
access-list ACL-OUT extended deny ip any any (hitcnt=4321)
"""
NAT_TXT = """branch-fw # show firewall vip
config firewall vip
    edit "web-https"
        set extip 203.0.113.10
        set mappedip "10.0.0.8"
        set extintf "wan1"
    next
    edit "web-http"
        set extip 203.0.113.11
        set mappedip "10.0.0.9"
        set extintf "wan1"
    next
end
"""
IPSEC_TXT = """vd: root/0
name: branch1(101) proto=ikev2 peer=203.0.113.2 local=203.0.113.10 status=up
name: branch2(102) proto=ikev1 peer=198.51.100.2 local=203.0.113.10 status=down
"""


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
ro_user = os.environ.get("NOPS_RO_USER", "op_low")
op = login(ro_user, "NopsTest@2025")


def pk(x):
    return x if isinstance(x, int) else x.get("id")


_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]
# 独立临时设备，避免污染演示设备
s, td = call("POST", "/cmdb/devices/", admin, {
    "name": f"采集解析测试-{TS[:6]}", "vendor": "Cisco",
    "model": pk(base["model"]), "site": pk(base["site"]), "region": pk(base["region"]),
    "manage_ip": "10.200.200.200"})
check("T0 造临时设备", s == 201, str(td)[:120])
tid = td["id"]

# 预览（不落库）
s, r = call("POST", f"/cmdb/devices/{tid}/tech-parse/", admin, {"kind": "acl", "text": ACL_TXT})
check("T1 ACL 预览解析", s == 200 and r.get("ok") and r.get("count") == 2
      and r.get("summary", {}).get("permit") == 1 and r.get("saved") is False, str(r)[:200])
s, r2 = call("GET", f"/cmdb/devices/{tid}/tech/", admin)
check("T2 预览未落库(acl 仍未接入)", r2.get("extensions", {}).get("acl", {}).get("supported") is False, "")
s, r = call("POST", f"/cmdb/devices/{tid}/tech-parse/", admin,
            {"kind": "nat", "text": "nothing relevant here\nprint hello"})
check("T3 不可识别输入 -> 400+hint", s == 400 and "hint" in r, str(r)[:160])
s, r = call("POST", f"/cmdb/devices/{tid}/tech-parse/", op, {"kind": "acl", "text": ACL_TXT})
check("T4 只读可预览", s == 200 and r.get("ok"), str(s))
s, r = call("POST", f"/cmdb/devices/{tid}/tech-parse/", op,
            {"kind": "acl", "text": ACL_TXT, "save": True})
check("T5 只读保存 -> 403", s == 403, str(s))
s, r = call("POST", f"/cmdb/devices/{tid}/tech-parse/", admin,
            {"kind": "acl", "text": ACL_TXT, "save": True})
check("T6 ACL 落库", s == 200 and r.get("saved") is True and r.get("snapshot_id"), str(r)[:160])
# nat / ipsec 落库
s, rn = call("POST", f"/cmdb/devices/{tid}/tech-parse/", admin,
             {"kind": "nat", "text": NAT_TXT, "save": True})
check("T7 NAT(VIP) 落库", s == 200 and rn.get("count") == 2, str(rn)[:160])
s, ri = call("POST", f"/cmdb/devices/{tid}/tech-parse/", admin,
             {"kind": "ipsec", "text": IPSEC_TXT, "save": True})
check("T8 IPSec 落库(up/down)", s == 200 and ri.get("count") == 2
      and ri.get("summary", {}).get("up") == 1 and ri.get("summary", {}).get("down") == 1, str(ri)[:160])
s, t = call("GET", f"/cmdb/devices/{tid}/tech/", admin)
ext = t.get("extensions", {})
check("T9 tech 三品类透出", ext.get("acl", {}).get("supported") is True
      and ext.get("nat", {}).get("supported") is True
      and ext.get("ipsec", {}).get("supported") is True
      and len(ext.get("acl", {}).get("payload", {}).get("rows", [])) == 2, str(ext)[:300])
# 总览聚合
s, ov = call("GET", "/cmdb/devices/network-overview/", admin)
emap = {e["key"]: e for e in ov.get("extensions", [])}
check("T10 总览扩展位已采集", emap.get("acl", {}).get("collected") is True
      and emap.get("nat", {}).get("collected") is True
      and emap.get("ipsec", {}).get("collected") is True
      and emap.get("acl", {}).get("total") >= 2
      and emap.get("quality_history", {}).get("collected") is False,
      str({k: {kk: v.get(kk) for kk in ("collected", "devices", "total")}
           for k, v in emap.items()}))
# 只读可见总览
s, ov2 = call("GET", "/cmdb/devices/network-overview/", op)
check("T11 只读可见总览扩展", s == 200, str(s))
# 清理：purge 设备后孤儿快照不计入
call("DELETE", f"/cmdb/devices/{tid}/", admin)
call("POST", f"/cmdb/devices/{tid}/purge/?confirm=1", admin)
s, ov3 = call("GET", "/cmdb/devices/network-overview/", admin)
emap3 = {e["key"]: e for e in ov3.get("extensions", [])}
# nat/ipsec 仅临时设备写过：purge 后孤儿快照不计入 → 回落未采集（acl 可能含 R3 遗留数据，不断言）
check("T12 purge 后 nat/ipsec 回落未采集",
      emap3.get("nat", {}).get("collected") is False
      and emap3.get("ipsec", {}).get("collected") is False, str(emap3)[:200])

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
