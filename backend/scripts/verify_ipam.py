"""IPAM E2E（含收尾）：vlan/subnet/ip CRUD + usage + ARP 文本导入(新增/更新/冲突/范围外/
同 mac 触达) + SNMP ARP 周期采集演练(mock, interface 回填) + 大网段格子图切片 + 写门负例。

用法: python scripts/verify_ipam.py [BASE]
默认 sqlite 8010；容器 PG: http://127.0.0.1:8000/api/v1
前置: init_nops_data；admin/nops@2025、auditor/NopsTest@2025（无 cmdb.device 权限）。
"""
import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010/api/v1")
ok = fail = 0


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
            return e.code, {"raw": (e.read() or b"")[:120]}


def check(name, cond, extra=""):
    global ok, fail
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra)[:170] if not cond else ""))
    globals()["ok" if cond else "fail"] += 1


tok = call("POST", "/auth/login/", body={"username": "admin", "password": "nops@2025"})[1]["access"]
aud = call("POST", "/auth/login/", body={"username": "auditor", "password": "NopsTest@2025"})[1]["access"]


def ensure(list_path, create_path, payload, match):
    st, page = call("GET", list_path, tok)
    for it in page.get("results", []):
        if match(it):
            return it
    st, obj = call("POST", create_path, tok, payload)
    assert st in (200, 201), (st, obj)
    return obj


# 清理旧测试数据（幂等）
_, old = call("GET", "/ipam/subnets/?search=10.99.", tok)
for it in old.get("results", []):
    call("DELETE", "/ipam/subnets/" + str(it["id"]) + "/", tok)

vlan = ensure("/ipam/vlans/?page_size=100", "/ipam/vlans/",
              {"vid": 990, "name": "T-Vlan", "purpose": "test"},
              lambda x: x["vid"] == 990)
sn = ensure("/ipam/subnets/?search=10.99.1.0", "/ipam/subnets/",
            {"cidr": "10.99.1.0/24", "vlan_id": vlan["id"], "gateway": "10.99.1.1",
             "purpose": "T-Subnet"}, lambda x: x["cidr"] == "10.99.1.0/24")
check("P1 vlan+subnet created", vlan.get("id") and sn.get("id"), (vlan, sn))

# 登记 IP：网关保留 + 一台已用
st, gw = call("POST", "/ipam/ips/", tok,
              {"subnet": sn["id"], "address": "10.99.1.1", "status": "reserved", "assignee": "网关"})
check("P2 register reserved gw", st in (200, 201), (st, gw))
st, used = call("POST", "/ipam/ips/", tok,
                {"subnet": sn["id"], "address": "10.99.1.10", "status": "used",
                 "mac": "aa:bb:cc:00:01:10", "assignee": "T-PC"})
check("P3 register used ip", st in (200, 201), (st, used))
st, bad = call("POST", "/ipam/ips/", tok, {"subnet": sn["id"], "address": "10.99.2.10"})
check("P4 out-of-subnet rejected 400", st == 400, (st, bad))

st, u = call("GET", "/ipam/subnets/" + str(sn["id"]) + "/usage/", tok)
check("P5 usage stats", u.get("used") == 1 and u.get("reserved") == 1 and u.get("total") == 254, u)

# 文本 ARP 导入：新增/保留位→used/冲突/范围外
st, r = call("POST", "/ipam/ips/import-arp/", tok, {"text": (
    "10.99.1.11  6c92bf3a2211\n"
    "10.99.1.1   6c92bf000001\n"
    "10.99.1.10  deadbeef0010\n"
    "10.9.9.9    aaaaaaaaaaaa\n")})
check("P6 arp import summary", r.get("created") == 1 and r.get("updated") == 1
      and r.get("conflict") == 1 and r.get("out_of_scope") == 1, r)
_, ips = call("GET", "/ipam/ips/?subnet=" + str(sn["id"]), tok)
rows = {i["address"]: i for i in ips.get("results", [])}
check("P7 arp created .11 + reserved→used .1", rows.get("10.99.1.11", {}).get("status") == "used"
      and rows.get("10.99.1.1", {}).get("status") == "used"
      and rows.get("10.99.1.11", {}).get("source") == "arp_discover", rows.get("10.99.1.11"))
check("P8 conflict .10 detected", rows.get("10.99.1.10", {}).get("status") == "conflict",
      rows.get("10.99.1.10"))
st, r2 = call("POST", "/ipam/ips/import-arp/", tok, {"text": "10.99.1.10  aa:bb:cc:00:01:10"})
check("P9 same-mac import no new conflict", r2.get("conflict") == 0, r2)

# ---- 写门负例（cmdb.device.execute 门禁） ----
st, _ = call("POST", "/ipam/ips/import-arp/", aud, {"text": "10.99.1.12 aa:aa:aa:aa:aa:aa"})
check("P10 auditor import-arp 403", st == 403, st)
st, _ = call("GET", "/ipam/ips/?subnet=" + str(sn["id"]), aud)
check("P11 auditor 读 IP 403", st == 403, st)

# ---- SNMP ARP 周期采集演练（mock → 登记 .22/.23 + interface 回填字段） ----
_, base = call("GET", "/cmdb/devices/?page_size=1", tok)
st, poll = call("POST", "/ipam/ips/arp-poll/", tok, {"mock": 1,
                                                     "device_ids": [base["results"][0]["id"]]})
summ = poll.get("summary", {})
check("P12 mock ARP poll 登记 2 台(created 2)", st == 200
      and summ.get("created", 0) == 2 and poll.get("checked", 0) >= 1
      and all("device_id" in d for d in poll.get("detail", [])), str(poll)[:220])
_, ips2 = call("GET", f"/ipam/ips/?subnet={sn['id']}&page_size=200", tok)
rows2 = {i["address"]: i for i in ips2.get("results", [])}
check("P13 poll 落库 .22/.23 used(arp_discover) mac 归一", rows2.get("10.99.1.22", {}).get("status") == "used"
      and rows2["10.99.1.22"]["mac"] == "6c:92:bf:00:00:16"
      and rows2.get("10.99.1.23", {}).get("source") == "arp_discover",
      rows2.get("10.99.1.22"))
st, poll2 = call("POST", "/ipam/ips/arp-poll/", tok, {"mock": 1,
                                                      "device_ids": [base["results"][0]["id"]]})
check("P14 重复 poll 不新增(created 0)", st == 200 and poll2.get("summary", {}).get("created", 9) == 0,
      poll2.get("summary"))

# ---- 大网段格子图切片 ----
st, mp = call("GET", f"/ipam/subnets/{sn['id']}/map/?offset=0&limit=40", tok)
cells = {c["address"]: c for c in mp.get("rows", [])}
check("P15 map 切片(40 格起点 .1, .22 used, 含 usage)", st == 200 and mp.get("usable_total") == 254
      and len(mp.get("rows", [])) >= 39 and cells.get("10.99.1.1", {}).get("status") == "used"
      and cells.get("10.99.1.22", {}).get("status") == "used"
      and mp.get("usage", {}).get("used", 0) >= 3, str(mp)[:220])
st, mp2 = call("GET", f"/ipam/subnets/{sn['id']}/map/?offset=200&limit=60", tok)
check("P16 尾部切片(offset=200 到达末尾)", st == 200
      and mp2.get("count", 0) == mp2.get("usable_total", 0) - 200, mp2.get("count"))
st, _ = call("GET", f"/ipam/subnets/{sn['id']}/map/", aud)
check("P17 auditor map 403", st == 403, st)

# 清理
call("DELETE", "/ipam/subnets/" + str(sn["id"]) + "/", tok)
print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
