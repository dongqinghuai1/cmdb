"""Comprehensive CRUD test with temp data (auto-cleanup). python scripts/api_test.py"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8000/api/v1"
ok = fail = 0


def call(method, path, token=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "replace")[:150]}


def check(name, cond, extra=""):
    global ok, fail
    print(("PASS " if cond else "FAIL ") + name + (f"  {str(extra)[:160]}" if not cond else ""))
    globals()["ok" if cond else "fail"] += 1


st, r = call("POST", "/auth/login/", body={"username": "admin", "password": "nops@2025"})
tok = r.get("access", "")
check("login", st == 200 and tok)


def preclean():
    """hard-delete leftovers incl soft-deleted rows (superuser all=1 view)."""
    st, lst = call("GET", "/cmdb/devices/?search=T-&all=1&page_size=100", tok)
    for it in (lst.get("results") or []):
        call("DELETE", "/cmdb/devices/" + str(it["id"]) + "/?hard=1", tok)
    for path in ["/dcim/racks/?search=T-RACK", "/dcim/sites/?search=t-site",
                 "/dcim/regions/?search=t-reg", "/cmdb/groups/?search=T-GROUP",
                 "/alerts/rules/?search=T-Offline", "/inspects/templates/?search=T-Tpl",
                 "/system/credentials/?search=T-CRED", "/system/notify-channels/?search=T-CH"]:
        st, lst = call("GET", path, tok)
        for it in (lst.get("results") or []):
            call("DELETE", "/" + path.split("?")[0].strip("/") + "/" + str(it["id"]) + "/", tok)


preclean()

# ---- 1. region / site / rack CRUD ----
st, reg = call("POST", "/dcim/regions/", tok, {"name": "T-Region", "code": "t-reg"})
check("region create", st in (200, 201), (st, reg))
if "id" not in reg:
    st, lst = call("GET", "/dcim/regions/?search=t-reg", tok)
    reg = next((x for x in lst.get("results", []) if x["code"] == "t-reg"), {})
st, site = call("POST", "/dcim/sites/", tok, {"name": "T-Site", "code": "t-site", "region": reg["id"]})
check("site create", st in (200, 201), (st, site))
if "id" not in site:
    st, lst = call("GET", "/dcim/sites/?search=t-site", tok)
    site = next((x for x in lst.get("results", []) if x["code"] == "t-site"), {})
st, rack = call("POST", "/dcim/racks/", tok, {"name": "T-RACK", "site": site["id"], "u_total": 42})
check("rack create", st in (200, 201), (st, rack))
if "id" not in rack:
    st, lst = call("GET", "/dcim/racks/?search=T-RACK", tok)
    rack = next((x for x in lst.get("results", []) if x["name"] == "T-RACK"), {})

st, _ = call("PATCH", "/dcim/regions/" + str(reg["id"]) + "/", tok, {"remark": "updated"})
check("region update", st == 200, st)
st, _ = call("GET", "/dcim/racks/" + str(rack["id"]) + "/elevation/", tok)
check("rack elevation", st == 200, st)

# ---- 2. models + devices ----
st, ml = call("GET", "/cmdb/models/", tok)
sw = next((m["id"] for m in ml.get("results", []) if m["code"] == "switch"), None)
srv = next((m["id"] for m in ml.get("results", []) if m["code"] == "server"), None)
check("models list", sw and srv, ml)

st, grp = call("POST", "/cmdb/groups/", tok, {"name": "T-GROUP"})
check("device group create", st in (200, 201), (st, grp))

st, dev = call("POST", "/cmdb/devices/", tok, {
    "name": "T-SW-01", "model": sw, "vendor": "H3C", "sn": "T-SN-001",
    "region": reg["id"], "site": site["id"]})
check("device create (unplaced)", st in (200, 201), (st, dev))

st, dev2 = call("POST", "/cmdb/devices/", tok, {
    "name": "T-SRV-01", "model": srv, "vendor": "Dell", "sn": "T-SN-002",
    "region": reg["id"], "site": site["id"], "rack": rack["id"],
    "rack_start_u": 5, "rack_units": 2})
check("device create (placed U5 2U)", st in (200, 201), (st, dev2))

st, dup = call("POST", "/cmdb/devices/", tok, {
    "name": "T-DUP", "model": sw, "region": reg["id"], "site": site["id"],
    "rack": rack["id"], "rack_start_u": 6, "rack_units": 1})
check("device conflict -> 409", st == 409, (st, dup))

st, un = call("GET", "/cmdb/devices/?rack__isnull=true", tok)
names = [d["name"] for d in un.get("results", [])]
check("unplaced filter", st == 200 and "T-SW-01" in names and "T-SRV-01" not in names, (st, names[:5]))

st, mv = call("POST", "/cmdb/devices/" + str(dev["id"]) + "/place/", tok,
              {"rack": rack["id"], "rack_start_u": 30})
check("device place U30", st == 200, (st, mv))

st, mv2 = call("POST", "/cmdb/devices/" + str(dev["id"]) + "/place/", tok,
               {"rack": rack["id"], "rack_start_u": 5})
check("place conflict -> 409", st == 409, (st, mv2))

st, elev = call("GET", "/dcim/racks/" + str(rack["id"]) + "/elevation/", tok)
u30 = next((u for u in elev.get("units", []) if u.get("u") == 30), {})
u5 = next((u for u in elev.get("units", []) if u.get("u") == 5), {})
check("elevation U30 occupied", u30.get("status") == "occupied" and
      u30.get("device", {}).get("name") == "T-SW-01", u30)
check("elevation U5 occupied", u5.get("status") == "occupied", u5)

st, d360 = call("GET", "/cmdb/devices/" + str(dev["id"]) + "/360/", tok)
check("device 360 + stat", st == 200 and "interfaces" in d360 and
      isinstance(d360["interfaces"], list), (st, d360 if st != 200 else ""))

st, upd = call("PATCH", "/cmdb/devices/" + str(dev["id"]) + "/", tok, {"vendor": "H3C", "hw_model": "S6520X"})
check("device update", st == 200, (st, upd))

st, attr_list = call("GET", "/cmdb/models/" + str(sw) + "/attrs/", tok)
if any(a.get("code") == "uplink_bw" for a in attr_list):
    check("model attr create", True, "(existing)")
else:
    st, attr = call("POST", "/cmdb/models/" + str(sw) + "/attrs/", tok,
                    {"code": "uplink_bw", "name": "uplink-bw", "attr_type": "int"})
    check("model attr create", st in (200, 201), (st, attr))
st, badattr = call("POST", "/cmdb/devices/", tok, {
    "name": "T-BAD", "model": sw, "region": reg["id"], "site": site["id"],
    "attrs": {"uplink_bw": "not-a-number"}})
check("attrs type check 400", st == 400, (st, badattr))
st, builtin = call("POST", "/cmdb/models/" + str(sw) + "/attrs/", tok,
                   {"code": "hostname", "name": "x", "attr_type": "text"})
check("attr builtin-name 400", st == 400, (st, builtin))

# ---- 3. alert / inspect ----
st, ar = call("POST", "/alerts/rules/", tok, {"name": "T-Offline", "rule_type": "state",
                                              "metric": "offline", "severity": "critical"})
check("alert rule create", st in (200, 201), (st, ar))
st, ae = call("GET", "/alerts/events/", tok)
check("alert events list", st == 200, st)
st, tpl = call("POST", "/inspects/templates/", tok, {"name": "T-Tpl"})
check("inspect template create", st in (200, 201), (st, tpl))

# ---- 4. system ----
st, cred = call("POST", "/system/credentials/", tok,
                {"name": "T-CRED-" + str(__import__("random").randint(10000, 99999)),
                 "cred_type": "ssh_password", "secret": "x"})
check("credential create", st in (200, 201), (st, cred))
st, ch = call("POST", "/system/notify-channels/", tok, {"name": "T-CH", "channel_type": "webhook",
                                                        "config": {"url": "http://localhost:9999/hook"}})
check("channel create", st in (200, 201), (st, ch))
st, usr = call("GET", "/system/users/", tok)
check("users list", st == 200, st)
st, aud = call("GET", "/system/audit-logs/", tok)
check("audit list has rows", st == 200 and aud.get("count", 0) > 0, aud)

# ---- 5. cleanup ----
for name, path in [("del dev", "/cmdb/devices/" + str(dev["id"]) + "/?hard=1"),
                   ("del dev2", "/cmdb/devices/" + str(dev2["id"]) + "/?hard=1"),
                   ("del rack", "/dcim/racks/" + str(rack["id"]) + "/"),
                   ("del site", "/dcim/sites/" + str(site["id"]) + "/"),
                   ("del region", "/dcim/regions/" + str(reg["id"]) + "/")]:
    st, _ = call("DELETE", path, tok)
    check(name, st in (200, 204), st)

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
