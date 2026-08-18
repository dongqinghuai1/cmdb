"""Ghost-device scenario: soft-deleted devices must not block site/rack/region delete."""
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

# 建独立链：region -> site -> rack -> 两台设备（一台上架）
_, reg = call("POST", "/dcim/regions/", tok, {"name": "G-Region", "code": "g-reg"})
_, site = call("POST", "/dcim/sites/", tok, {"name": "G-Site", "code": "g-site", "region": reg["id"]})
_, rack = call("POST", "/dcim/racks/", tok, {"name": "G-RACK", "site": site["id"], "u_total": 42})
_, d1 = call("POST", "/cmdb/devices/", tok, {"name": "G-DEV-1", "model": sw, "vendor": "H3C",
                                             "region": reg["id"], "site": site["id"],
                                             "rack": rack["id"], "rack_start_u": 10})
_, d2 = call("POST", "/cmdb/devices/", tok, {"name": "G-DEV-2", "model": sw, "vendor": "H3C",
                                             "region": reg["id"], "site": site["id"]})

# 1. 可见设备仍拦截删除
st, msg = call("DELETE", "/dcim/sites/" + str(site["id"]) + "/", tok)
check("active device blocks site delete", st == 400 and "引用" in msg.get("detail", ""), (st, msg))

# 2. 软删除全部设备（UI 删除路径）
call("DELETE", "/cmdb/devices/" + str(d1["id"]) + "/", tok)
call("DELETE", "/cmdb/devices/" + str(d2["id"]) + "/", tok)

# 3. 幽灵设备不再阻塞：rack -> site -> region 应可删
st, _ = call("DELETE", "/dcim/racks/" + str(rack["id"]) + "/", tok)
check("ghost purge: delete rack", st in (200, 204), st)
st, _ = call("DELETE", "/dcim/sites/" + str(site["id"]) + "/", tok)
check("ghost purge: delete site", st in (200, 204), st)
st, _ = call("DELETE", "/dcim/regions/" + str(reg["id"]) + "/", tok)
check("ghost purge: delete region", st in (200, 204), st)

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
