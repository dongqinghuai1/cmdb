"""拓扑自动发现 + 线缆/LLDP 比对回归：
P 组: LLDP-MIB 解析纯函数（本地不触网）
S 组: mock 发现链路 → topo_lldpneighbor / 构图 / 线缆比对(确认/mismatch/自动补录) / 权限负例
用法: python scripts/verify_topo_lldp.py [BASE]
前置: 后端以 NOPS_DB=sqlite NOPS_EAGER=1 跑在 127.0.0.1:8010（容器栈 8000）。
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
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


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


# ---------- P 组：LLDP-MIB 解析纯函数（stdlib only，不触网） ----------
def test_parse():
    from apps.cmdb import snmp as S
    # lldpRemEntry col: chassis_id=5 / sys_name=9；索引 timeMark.localPort.remIndex
    rem_rows = [
        (S.LLDP_REM_ENTRY + ".9.0.17.2", "Peer-SW-01"),
        (S.LLDP_REM_ENTRY + ".5.0.17.2", "00:1a:2b:3c:4d:5e"),
        (S.LLDP_REM_ENTRY + ".7.0.17.2", "Gi1/0/1"),
        (S.LLDP_REM_ENTRY + ".8.0.17.2", "GigabitEthernet1/0/1"),
        (S.LLDP_REM_ENTRY + ".4.0.17.2", 4),
        (S.LLDP_REM_ENTRY + ".6.0.17.2", 5),
    ]
    rem = S.parse_lldp_rem(rem_rows)
    row = rem.get((17, 2)) or {}
    check("P1 rem 表 (local_port,rem_idx) 归组", (17, 2) in rem)
    check("P2 sys_name/port_id 解析", row.get("sys_name") == "Peer-SW-01"
          and row.get("port_id") == "Gi1/0/1")
    check("P3 chassis mac 与 subtype 解析",
          row.get("chassis_id") == "00:1a:2b:3c:4d:5e"
          and str(row.get("chassis_id_subtype")) == "4")
    # 超出 entry 前缀的行忽略
    stray = list(rem.keys())
    S.parse_lldp_rem(rem_rows + [(S.LLDP_REM_ENTRY + "9.1.0.17.2", "x")])  # 不抛
    check("P4 非目标列忽略（无异常）", True)
    # lldpLocPortTable col: port_id=3 / port_desc=4
    loc = S.parse_lldp_loc([(S.LLDP_LOC_ENTRY + ".3.17", "Gi1/0/1"),
                            (S.LLDP_LOC_ENTRY + ".4.17", "GigabitEthernet1/0/1")])
    check("P5 loc 表 port→描述", loc.get(17, {}).get("port_id") == "Gi1/0/1"
          and loc[17].get("port_desc") == "GigabitEthernet1/0/1")
    return stray


test_parse()

# ---------- S 组：HTTP 全链路 ----------
admin = login("admin", "nops@2025")
net = login("net_demo", "NopsTest@2025")      # 有 dcim.rack.view，无 rack.edit/device.execute

_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]
created_ids, cable_ids = [], []


def mk(name, ip):
    s, r = call("POST", "/cmdb/devices/", admin, {
        "name": name, "vendor": "H3C", "model": base["model"],
        "site": base["site"], "region": base["region"],
        "driver_type": "h3c_comware", "manage_ip": ip})
    return s, r


sA, A = mk(f"LLDP-A-{TS}", "198.51.100.11")
sB, B = mk(f"LLDP-B-{TS}", "198.51.100.12")
check("S1 造对端设备 A/B", sA == 201 and sB == 201, f"{sA}/{sB}")
created_ids += [A["id"], B["id"]]

s, cred = call("POST", "/system/credentials/", admin,
               {"name": f"lldp-cred-{TS}", "cred_type": "snmp_v2c", "username": "",
                "secret": "public", "params": {"port": 161}})
check("S2 建 snmp_v2c 凭据", s == 201, str(cred)[:120])
cid = cred["id"]
for did in (A["id"], B["id"]):
    s, _ = call("PATCH", f"/cmdb/devices/{did}/", admin, {"credential_id": cid})
    if s != 200:
        check("S3 绑定凭据", False, f"device {did} -> {s}")
        raise SystemExit(1)
check("S3 绑定 snmp_v2c 凭据到 A/B", True)

ifaces = {}
for did in (A["id"], B["id"]):
    s, r = call("POST", f"/cmdb/devices/{did}/snmp-test/", admin, {"mock": 1})
    if s != 200 or r.get("interfaces", 0) < 2:
        check("S4 预铺接口", False, str(r)[:120])
        raise SystemExit(1)
    _, d360 = call("GET", f"/cmdb/devices/{did}/360/", admin)
    ifaces[did] = {i["if_index"]: i["id"] for i in d360.get("interfaces", [])}
check("S4 两端接口就绪(≥2)", all(len(v) >= 2 for v in ifaces.values()))

# mock 发现（勿触网）
s, r = call("POST", "/topo/lldp-discover/", admin, {"mock": 1})
check("S5 mock 发现 ok>=2 台", s == 200 and r.get("ok", 0) >= 2, str(r)[:160])

s, r = call("POST", "/topo/lldp-discover/", net, {"mock": 1})
check("S6 只读账号触发发现 -> 403", s == 403, str(s))

# 邻居行可见且远端已回填
s, nb = call("GET", "/topo/lldp-neighbors/?page_size=100", admin)
mine_ids = {A["id"], B["id"]}
rows = [x for x in nb.get("results", [])
        if x.get("remote_device_id") in mine_ids]
check("S7 lldp-neighbors 落库且远端回填", s == 200 and len(rows) >= 4
      and all(x.get("remote_hostname") for x in rows), str(len(rows)))

# 构图出现 A-B LLDP 边
s, g = call("GET", f"/topo/graph/?site={base['site']}", admin)
edge = any(e.get("kind") == "lldp"
           and {str(e.get("source")), str(e.get("target"))} == {str(A["id"]), str(B["id"])}
           for e in g.get("edges", []))
check("S8 graph 含 A-B LLDP 自动边", s == 200 and edge, str(g.get("stats"))[:100])

a1, b1 = ifaces[A["id"]][1], ifaces[B["id"]][1]
a3, b3 = ifaces[A["id"]][3], ifaces[B["id"]][3]

# 台账：pair1(确认)、pair3(mismatch)；pair2 故意不录 → 待自动补录
for pair in ((a1, b1), (a3, b3)):
    s, c = call("POST", "/dcim/cables/", admin,
                {"a_interface_id": pair[0], "b_interface_id": pair[1],
                 "cable_type": "cat6", "source": "manual", "status": "active"})
    check("S9 建手工线缆", s == 201, str(c)[:120])
    cable_ids.append(c["id"])

s, r = call("POST", "/dcim/cables/compare-lldp/", net, {})
check("S10 无 edit 权限比对 -> 403（读权有、写权无）", s == 403, str(s))

s, r = call("POST", "/dcim/cables/compare-lldp/", admin, {})
check("S11 比对返回统计", s == 200 and r.get("confirmed", 0) >= 1
      and r.get("mismatch", 0) >= 1 and r.get("discovered", 0) >= 1,
      str({k: r.get(k) for k in ("cables", "confirmed", "mismatch", "discovered")}))
discovered = [x for x in r.get("discovered_links", [])
              if x["a_interface_id"] in ifaces[A["id"]].values()]

# 落库状态核对：pair1=active、pair3=mismatch、pair2(source=lldp) 补录
s, cs = call("GET", "/dcim/cables/?page_size=100&ordering=-id", admin)
by_id = {c["id"]: c for c in cs.get("results", [])}
pair1_ok = by_id.get(cable_ids[0], {}).get("status") == "active"
pair3_ok = by_id.get(cable_ids[1], {}).get("status") == "mismatch"
auto_ids = [c["id"] for c in cs.get("results", [])
            if c.get("source") == "lldp" and c.get("status") == "active"
            and c.get("a_interface_id") in ifaces[A["id"]].values()]
check("S12 pair1 确认 active", pair1_ok)
check("S13 pair3 台账无邻居 -> mismatch", pair3_ok)
check("S14 未录 pair2 自动补录 source=lldp", s == 200 and len(auto_ids) >= 1)

# 幂等：再比对一次不新增补录/不翻转
s2, r2 = call("POST", "/dcim/cables/compare-lldp/", admin, {})
check("S15 重复比对幂等", s2 == 200 and r2.get("discovered", 0) == 0
      and r2.get("confirmed", 0) >= 1 and r2.get("mismatch", 0) >= 1,
      str(r2.get("discovered")))

# 清理：线缆(含自动补录) → purge 清邻居与设备 → 凭据
for cid_ in list(cable_ids) + auto_ids:
    call("DELETE", f"/dcim/cables/{cid_}/", admin)
for did in created_ids:
    call("DELETE", f"/cmdb/devices/{did}/", admin)
    call("POST", f"/cmdb/devices/{did}/purge/?confirm=1", admin)
call("DELETE", f"/system/credentials/{cid}/", admin)

# purge 后邻居无孤儿（A 的本地邻居应被清）
s, nb = call("GET", f"/topo/lldp-neighbors/?page_size=200", admin)
orphan = [x for x in nb.get("results", [])
          if x.get("remote_device_id") in mine_ids]
check("S16 purge 清理 LLDP 邻居无孤儿", len(orphan) == 0, str(len(orphan)))

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
