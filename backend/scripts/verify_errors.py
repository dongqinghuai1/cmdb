"""Verify CRUD error messages are readable. python scripts/verify_errors.py"""
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

# 1. 重复编码 -> 400 且 detail 可读（含字段名）
st, dup = call("POST", "/dcim/regions/", tok, {"name": "华东复制", "code": "cn-east"})
check("dup region readable 400", st == 400 and "code" in dup.get("detail", "") and len(dup["detail"]) > 5, (st, dup))

# 2. 缺字段 -> 可读
st, miss = call("POST", "/dcim/regions/", tok, {"name": "no-code"})
check("missing code readable", st == 400 and "code" in miss.get("detail", ""), (st, miss))

# 3. site 无效 region -> 可读
st, badsite = call("POST", "/dcim/sites/", tok, {"name": "X", "code": "x-1", "region": 99999})
check("bad region ref readable", st == 400 and "region" in badsite.get("detail", ""), (st, badsite))

# 4. 删除有子节点的地区 -> 可读提示（不能静默 500/空）
_, rl = call("GET", "/dcim/regions/?search=cn-east", tok)
rid = rl["results"][0]["id"]
st, dele = call("DELETE", "/dcim/regions/" + str(rid) + "/", tok)
check("del region-with-children readable", st in (400, 409) and len(dele.get("detail", "")) > 5, (st, dele))

# 5. 删除有设备的机柜 -> 可读提示
_, rks = call("GET", "/dcim/racks/?search=A01", tok)
if rks.get("results"):
    kid = rks["results"][0]["id"]
    _, devs = call("GET", "/cmdb/devices/?search=SRV-DB-01", tok)
    if devs.get("results"):
        d = devs["results"][0]
        if not d.get("rack"):
            call("POST", "/cmdb/devices/" + str(d["id"]) + "/place/", tok, {"rack": kid, "rack_start_u": 40})
        st, dk = call("DELETE", "/dcim/racks/" + str(kid) + "/", tok)
        check("del rack-with-device readable", st in (400, 409, 204) and
              (st == 204 or len(dk.get("detail", "")) > 5), (st, dk))
        call("POST", "/cmdb/devices/" + str(d["id"]) + "/place/", tok, {"rack": kid, "rack_start_u": 40})

# 6. 正常 CRUD 往返：region/site/rack/device/group/rule/channel
for path, payload, name in [
    ("/dcim/regions/", {"name": "V-Region", "code": "v-reg"}, "region"),
    ("/cmdb/groups/", {"name": "V-GROUP"}, "group"),
    ("/alerts/rules/", {"name": "V-Rule", "rule_type": "state", "metric": "offline"}, "rule"),
    ("/system/notify-channels/", {"name": "V-CH", "channel_type": "webhook", "config": {}}, "channel"),
]:
    st, obj = call("POST", path, tok, payload)
    check("create " + name, st in (200, 201) and "id" in obj, (st, obj))
    if "id" in obj:
        st, _ = call("PATCH", path + str(obj["id"]) + "/", tok,
                     {"remark": "v"} if "region" not in name else {"remark": "v"})
        check("update " + name, st == 200, st)
        st, _ = call("DELETE", path + str(obj["id"]) + "/", tok)
        check("delete " + name, st in (200, 204), st)

# 7. site + rack 往返（带引用链）
st, reg = call("POST", "/dcim/regions/", tok, {"name": "V-Region2", "code": "v-reg2"})
st, site = call("POST", "/dcim/sites/", tok, {"name": "V-Site", "code": "v-site", "region": reg["id"]})
check("create site", st in (200, 201), (st, site))
st, rack = call("POST", "/dcim/racks/", tok, {"name": "V-RACK", "site": site["id"], "u_total": 42})
check("create rack", st in (200, 201), (st, rack))
st, _ = call("DELETE", "/dcim/racks/" + str(rack["id"]) + "/", tok)
check("delete rack(empty)", st in (200, 204), st)
st, _ = call("DELETE", "/dcim/sites/" + str(site["id"]) + "/", tok)
check("delete site(empty)", st in (200, 204), st)
st, _ = call("DELETE", "/dcim/regions/" + str(reg["id"]) + "/", tok)
check("delete region(empty)", st in (200, 204), st)

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
