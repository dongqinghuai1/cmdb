"""IPAM E2E: vlan/subnet/ip CRUD -> usage stats -> ARP 导入（新增/更新/冲突）-> 网段外。"""
import json
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


def ensure(list_path, create_path, payload, match):
    st, page = call("GET", list_path, tok)
    for it in page.get("results", []):
        if match(it):
            return it
    st, obj = call("POST", create_path, tok, payload)
    assert st in (200, 201), (st, obj)
    return obj


# 清理旧测试数据（幂等）
st, old = call("GET", "/ipam/subnets/?search=10.99.", tok)
for it in old.get("results", []):
    call("DELETE", "/ipam/subnets/" + str(it["id"]) + "/", tok)

vlan = ensure("/ipam/vlans/?page_size=100", "/ipam/vlans/",
              {"vid": 990, "name": "T-Vlan", "purpose": "test"},
              lambda x: x["vid"] == 990)
sn = ensure("/ipam/subnets/?search=10.99.1.0", "/ipam/subnets/",
            {"cidr": "10.99.1.0/24", "vlan_id": vlan["id"], "gateway": "10.99.1.1",
             "purpose": "T-Subnet"}, lambda x: x["cidr"] == "10.99.1.0/24")
check("vlan+subnet created", vlan.get("id") and sn.get("id"), (vlan, sn))

# 登记 IP：网关保留 + 一台已用
st, gw = call("POST", "/ipam/ips/", tok,
              {"subnet": sn["id"], "address": "10.99.1.1", "status": "reserved", "assignee": "网关"})
check("register reserved gw", st in (200, 201), (st, gw))
st, used = call("POST", "/ipam/ips/", tok,
                {"subnet": sn["id"], "address": "10.99.1.10", "status": "used",
                 "mac": "aa:bb:cc:00:01:10", "assignee": "T-PC"})
check("register used ip", st in (200, 201), (st, used))

# 越界 IP 拒绝
st, bad = call("POST", "/ipam/ips/", tok, {"subnet": sn["id"], "address": "10.99.2.10"})
check("out-of-subnet rejected 400", st == 400, (st, bad))

# usage
st, u = call("GET", "/ipam/subnets/" + str(sn["id"]) + "/usage/", tok)
check("usage stats", u.get("used") == 1 and u.get("reserved") == 1 and u.get("total") == 254, u)

# ARP 导入：新增 .11 / 更新保留 .1 -> used / 冲突 .10（mac不同）/ 网段外 .9
st, r = call("POST", "/ipam/ips/import-arp/", tok, {"text": (
    "10.99.1.11  6c92bf3a2211\n"
    "10.99.1.1   6c92bf3a0001\n"
    "10.99.1.10  deadbeef0010\n"
    "10.9.9.9    aaaaaaaaaaaa\n")})
check("arp import summary", r.get("created") == 1 and r.get("updated") == 1
      and r.get("conflict") == 1 and r.get("out_of_scope") == 1, r)

st, ips = call("GET", "/ipam/ips/?subnet=" + str(sn["id"]), tok)
rows = {i["address"]: i for i in ips.get("results", [])}
check("arp created .11 used", rows.get("10.99.1.11", {}).get("status") == "used"
      and rows["10.99.1.11"]["source"] == "arp_discover", rows.get("10.99.1.11"))
check("reserved->used .1", rows.get("10.99.1.1", {}).get("status") == "used")
check("conflict .10 detected", rows.get("10.99.1.10", {}).get("status") == "conflict",
      rows.get("10.99.1.10"))
check("out-of-scope not created", "10.9.9.9" not in rows)

# 同 mac 再导入 -> 冲突恢复? (同 mac 只刷新 last_seen)
st, r2 = call("POST", "/ipam/ips/import-arp/", tok, {"text": "10.99.1.10  aa:bb:cc:00:01:10"})
check("same-mac import no new conflict", r2.get("conflict") == 0, r2)

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
