"""SNMP 采集驱动回归：BER 走查(本地 UDP mock 服务器验证收发)/权限/mock 采集落库幂等/无凭据前置校验。
用法: python scripts/verify_snmp.py [BASE]
"""
import json
import os
import socket
import sys
import threading
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


# ---------- 本地 UDP mock SNMP 服务器（真走查，验证 BER 收发） ----------
def _mock_snmp_server():
    from apps.cmdb import snmp as S

    def seq(*tlvs):
        return S._tlv(S._TAG_SEQ, b"".join(tlvs))

    table = [
        ("1.3.6.1.2.1.2.2.1.2.1", S._TAG_OCTET, b"GigabitEthernet0/0/0"),
        ("1.3.6.1.2.1.2.2.1.3.1", S._TAG_INT, S._enc_int(6)),
        ("1.3.6.1.2.1.2.2.1.5.1", S._TAG_INT, S._enc_int(1000000000)),
        ("1.3.6.1.2.1.2.2.1.8.1", S._TAG_INT, S._enc_int(1)),
        ("1.3.6.1.2.1.2.2.1.14.1", S._TAG_CTR, S._enc_int(7)),
    ]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    state = {"n": 0, "stop": False}

    def serve():
        sock.settimeout(8)
        while not state["stop"] and state["n"] <= len(table) + 2:
            try:
                data, addr = sock.recvfrom(65535)
                outer = S._parse_tlvs(data)
                req_inner = S._parse_tlvs(outer[0][1]) if outer else []
                reqid = S._decode_value(*S._parse_tlvs(req_inner[2][1])[0])
                i = state["n"]
                state["n"] += 1
                if i >= len(table):
                    pdu = seq(S._tlv(S._TAG_INT, S._enc_int(reqid)),
                              S._tlv(S._TAG_INT, S._enc_int(1)),
                              S._tlv(S._TAG_INT, S._enc_int(0)), b"")
                    resp = seq(S._tlv(S._TAG_INT, S._enc_int(1)),
                               S._tlv(S._TAG_OCTET, b"public"), pdu)
                else:
                    oid, tag, raw = table[i]
                    vb = seq(S._tlv(S._TAG_OID, S._enc_oid(oid)),
                             S._tlv(tag, raw))
                    pdu = seq(S._tlv(S._TAG_INT, S._enc_int(reqid)),
                              S._tlv(S._TAG_INT, S._enc_int(0)),
                              S._tlv(S._TAG_INT, S._enc_int(0)), seq(vb))
                    resp = seq(S._tlv(S._TAG_INT, S._enc_int(1)),
                               S._tlv(S._TAG_OCTET, b"public"), pdu)
                sock.sendto(resp, addr)
            except Exception as e:  # noqa: BLE001 —— 暴露服务器侧错误
                import traceback
                traceback.print_exc()
                state["error"] = str(e)
                break
        sock.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return port, table, state


def test_walk():
    from apps.cmdb import snmp as S
    port, table, state = _mock_snmp_server()
    rows = S.snmpwalk("127.0.0.1", "public", "1.3.6.1.2.1.2.2.1", port=port, timeout=2)
    state["stop"] = True
    return rows, table


admin = login("admin", "nops@2025")
ro = login(os.environ.get("NOPS_RO_USER", "op_low"), "NopsTest@2025")

# 1) BER 走查
rows, table = test_walk()
check("S1 本地 UDP 走查条数与 OID 顺序", [r[0] for r in rows] == [t[0] for t in table]
      and len(rows) == len(table), str([r[0] for r in rows]))
check("S2 值解码(octet/int/counter)", rows[0][1] == "GigabitEthernet0/0/0"
      and rows[2][1] == 1000000000 and rows[4][1] == 7,
      str([r[1] for r in rows]))

# 2) HTTP：权限 + mock 采集落库 + 幂等
_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]


def pk(x):
    return x if isinstance(x, int) else x.get("id")


s, td = call("POST", "/cmdb/devices/", admin, {
    "name": f"SNMP回归-{TS[:6]}", "vendor": "Cisco",
    "model": pk(base["model"]), "site": pk(base["site"]), "region": pk(base["region"]),
    "driver_type": "cisco_wlc_9800", "manage_ip": "10.200.210.9"})
check("S3 造临时设备(9800)", s == 201, str(td)[:100])
tid = td["id"]
s, r = call("POST", f"/cmdb/devices/{tid}/snmp-test/", ro, {"mock": 1})
check("S4 只读触发 -> 403", s == 403, str(s))
s, r = call("POST", f"/cmdb/devices/{tid}/snmp-test/", admin, {"mock": 1})
check("S5 mock 采集落接口", s == 200 and r.get("created") >= 3
      and r.get("interfaces") == 3 and r.get("profile") == "if-mib", str(r)[:200])
s, r2 = call("POST", f"/cmdb/devices/{tid}/snmp-test/", admin, {"mock": 1})
check("S6 二次幂等(created=0)", s == 200 and r2.get("created") == 0
      and r2.get("interfaces") == 3, str(r2)[:160])
s, r = call("POST", f"/cmdb/devices/{tid}/snmp-test/", admin, {"mock": 0})
check("S7 真实采集无凭据 -> 400", s == 400 and "SNMP 凭据" in r.get("detail", ""), str(r)[:140])
# 清理
call("DELETE", f"/cmdb/devices/{tid}/", admin)
call("POST", f"/cmdb/devices/{tid}/purge/?confirm=1", admin)

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
