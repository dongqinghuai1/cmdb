"""Phase-1 smoke test (idempotent). Usage: python scripts/smoke_test.py [base] [user] [pass]"""
import json
import random
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
USER = sys.argv[2] if len(sys.argv) > 2 else "admin"
PASS = sys.argv[3] if len(sys.argv) > 3 else "nops@2025"
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
            parsed = json.loads(raw)
        except Exception:
            parsed = {"raw": raw.decode("utf-8", "replace")[:200]}
        return e.code, parsed


def check(name, cond, extra=""):
    global ok, fail
    print(("  PASS " if cond else "  FAIL ") + name + (" " + str(extra)[:150] if not cond else ""))
    globals()["ok" if cond else "fail"] += 1


def get_or_create(list_path, match_key, match_val, create_path, payload, token):
    st, page = call("GET", f"{list_path}?search={match_val}", token)
    items = page.get("results", page if isinstance(page, list) else [])
    for it in items:
        if str(it.get(match_key)) == str(match_val):
            return it
    st, obj = call("POST", create_path, token, payload)
    assert st in (200, 201), f"create {payload} -> {st} {obj}"
    return obj


st, body = call("POST", "/api/v1/auth/login/", body={"username": USER, "password": PASS})
check("login", st == 200 and "access" in body, body)
token = body.get("access", "")
st, me = call("GET", "/api/v1/auth/me/", token)
check("me+perm_codes", st == 200 and "*" in me.get("perm_codes", []))

region = get_or_create("/api/v1/dcim/regions/", "code", "cn-east",
                       "/api/v1/dcim/regions/", {"name": "region-east", "code": "cn-east"}, token)
site = get_or_create("/api/v1/dcim/sites/", "code", "idc-core",
                     "/api/v1/dcim/sites/", {"name": "idc-core", "code": "idc-core",
                                             "region": region["id"]}, token)
rack = get_or_create("/api/v1/dcim/racks/?search=A01", "name", "A01",
                     "/api/v1/dcim/racks/", {"name": "A01", "site": site["id"], "u_total": 42}, token)
check("region/site/rack ready", all([region.get("id"), site.get("id"), rack.get("id")]))

st, models = call("GET", "/api/v1/cmdb/models/?search=switch", token)
items = models.get("results", [])
sw = next((m["id"] for m in items if m.get("code") == "switch"), None)
if not sw:
    st, models = call("GET", "/api/v1/cmdb/models/", token)
    sw = next((m["id"] for m in models.get("results", []) if m.get("code") == "switch"), None)
check("ci_model switch", sw is not None)

u = random.randint(20, 40)
dev_payload = {"name": "SW-SMOKE", "model": sw, "vendor": "H3C", "manage_ip": "10.99.0.1",
               "region": region["id"], "site": site["id"],
               "rack": rack["id"], "rack_start_u": u, "rack_units": 1}
st, dev = call("POST", "/api/v1/cmdb/devices/", token, dev_payload)
if st in (400, 409):  # name repeat? devices allow same name; ignore fallback
    st, lst = call("GET", "/api/v1/cmdb/devices/?search=SW-SMOKE", token)
    dev = next((d for d in lst.get("results", []) if d.get("rack_start_u") == u), lst["results"][0])
check("device placed", bool(dev.get("id")))

st, dup = call("POST", "/api/v1/cmdb/devices/", token, {**dev_payload, "name": "SW-CONFLICT"})
check("u-slot conflict rejected(400/409)", st in (400, 409), (st, dup))

st, elev = call("GET", f"/api/v1/dcim/racks/{rack['id']}/elevation/", token)
unit = next((x for x in elev.get("units", []) if x.get("u") == dev.get("rack_start_u")), {})
check("elevation occupied", unit.get("status") == "occupied", unit)

st, alerts = call("GET", "/api/v1/alerts/events/", token)
check("alert api", st == 200)
st, insp = call("GET", "/api/v1/inspects/templates/", token)
check("inspect api", st == 200)
st, cred = call("POST", "/api/v1/system/credentials/", token,
                {"name": "smoke-cred", "cred_type": "snmp_v2c", "secret": "public"})
st2, cred2 = call("GET", "/api/v1/system/credentials/", token)
masked = [c for c in cred2.get("results", []) if c.get("name") == "smoke-cred"]
check("credential masked", bool(masked) and masked[0]["secret_masked"] == "****", (st, cred))

call("DELETE", f"/api/v1/cmdb/devices/{dev['id']}", token)
print(f"\nRESULT: {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
