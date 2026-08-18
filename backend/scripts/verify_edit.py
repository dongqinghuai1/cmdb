"""Device location edit scenarios: move rack / conflict / unplace / change site."""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8000/api/v1"
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
            return e.code, {}


def check(name, cond, extra=""):
    global ok, fail
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra)[:150] if not cond else ""))
    globals()["ok" if cond else "fail"] += 1


_, r = call("POST", "/auth/login/", body={"username": "admin", "password": "nops@2025"})
tok = r["access"]
_, ml = call("GET", "/cmdb/models/", tok)
sw = next(m["id"] for m in ml["results"] if m["code"] == "switch")

_, rl = call("GET", "/dcim/regions/?search=cn-east", tok)
reg = rl["results"][0]
_, sl = call("GET", "/dcim/sites/?search=idc-sh", tok)
site = sl["results"][0]
_, sl2 = call("GET", "/dcim/sites/?search=idc-bj", tok)
site2 = sl2["results"][0]
_, rks = call("GET", "/dcim/racks/?search=A01", tok)
a01 = next(k for k in rks["results"] if k["name"] == "A01")
_, rks2 = call("GET", "/dcim/racks/?search=A02", tok)
a02 = next(k for k in rks2["results"] if k["name"] == "A02")

# 准备两台设备：d1 上架 A01-U10, d2 上架 A01-U20
ids = []
for name, u in [("V-EDIT-1", 10), ("V-EDIT-2", 20)]:
    st, d = call("POST", "/cmdb/devices/", tok, {"name": name, "model": sw, "vendor": "H3C",
                                                 "region": reg["id"], "site": site["id"],
                                                 "rack": a01["id"], "rack_start_u": u})
    ids.append(d["id"])
d1, d2 = ids

# 1. 换 U 位：d1 -> U15
st, r = call("PATCH", "/cmdb/devices/" + str(d1) + "/", tok, {"rack_start_u": 15})
check("move to U15", st == 200 and r.get("rack_start_u") == 15, (st, r))

# 2. 换机柜：d1 -> A02-U3
st, r = call("PATCH", "/cmdb/devices/" + str(d1) + "/", tok, {"rack": a02["id"], "rack_start_u": 3})
check("move to A02-U3", st == 200 and r.get("rack") == a02["id"], (st, r))

# 3. 冲突：d1 -> A01-U20（d2 占用）应 409
st, r = call("PATCH", "/cmdb/devices/" + str(d1) + "/", tok, {"rack": a01["id"], "rack_start_u": 20})
check("move conflict -> 409", st == 409, (st, r))

# 4. 下架：rack 清空
st, r = call("PATCH", "/cmdb/devices/" + str(d1) + "/", tok, {"rack": None, "rack_start_u": None})
check("unplace (rack=null)", st == 200 and r.get("rack") is None, (st, r))

# 5. 换机房（下架状态）：d1 -> 北京机房
st, r = call("PATCH", "/cmdb/devices/" + str(d1) + "/", tok, {"site": site2["id"]})
check("change site (unplaced)", st == 200 and r.get("site") == site2["id"], (st, r))

# 6. 已上架设备直接换机房（应允许：换机房即换归属，rack 同时清空才合理；后端允许 rack 不动）
st, r = call("PATCH", "/cmdb/devices/" + str(d2) + "/", tok, {"site": site2["id"], "rack": None, "rack_start_u": None})
check("change site with unplace", st == 200, (st, r))

# 7. 不传 rack 只改其他字段（部分更新语义不误伤位置）
st, r = call("PATCH", "/cmdb/devices/" + str(d1) + "/", tok, {"vendor": "Cisco"})
check("partial patch keeps pos", st == 200 and r.get("vendor") == "Cisco", (st, r))

# cleanup
for i in ids:
    call("DELETE", "/cmdb/devices/" + str(i) + "/?hard=1", tok)

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
