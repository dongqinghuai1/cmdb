"""Seed demo data for first-run UX (idempotent). python scripts/seed_demo.py"""
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/api/v1"


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
        return e.code, {}


_, r = call("POST", "/auth/login/", body={"username": "admin", "password": "nops@2025"})
tok = r["access"]

_, ml = call("GET", "/cmdb/models/", tok)
models = {m["code"]: m["id"] for m in ml.get("results", [])}


def ensure(path_list, match, create_path, payload):
    st, page = call("GET", path_list, tok)
    for it in page.get("results", []):
        if match(it):
            return it, False
    st, obj = call("POST", create_path, tok, payload)
    return obj, st in (200, 201)


r1, _ = ensure("/dcim/regions/?search=cn-east", lambda x: x["code"] == "cn-east",
               "/dcim/regions/", {"name": "华东", "code": "cn-east"})
r2, _ = ensure("/dcim/regions/?search=cn-north", lambda x: x["code"] == "cn-north",
               "/dcim/regions/", {"name": "华北", "code": "cn-north"})
s1, _ = ensure("/dcim/sites/?search=idc-sh", lambda x: x["code"] == "idc-sh",
               "/dcim/sites/", {"name": "上海核心机房", "code": "idc-sh", "region": r1["id"]})
s2, _ = ensure("/dcim/sites/?search=idc-bj", lambda x: x["code"] == "idc-bj",
               "/dcim/sites/", {"name": "北京分支机房", "code": "idc-bj", "region": r2["id"]})

for site, names in [(s1, ["A01", "A02"]), (s2, ["B01"])]:
    for n in names:
        ensure("/dcim/racks/?search=" + n, lambda x, n=n: x["name"] == n and x["site"] == site["id"],
               "/dcim/racks/", {"name": n, "site": site["id"], "u_total": 42})

demo_devices = [
    ("SW-CORE-01", "switch", "H3C", "S6520X-24ST", "10.1.1.1", s1),
    ("SW-ACC-02", "switch", "H3C", "S5130S-28P", "10.1.1.2", s1),
    ("SW-ACC-03", "switch", "H3C", "S5130S-28P", "10.1.1.3", s1),
    ("FW-EXIT-01", "firewall", "Fortinet", "FG-600F", "10.1.0.254", s1),
    ("AC-WLC-01", "wlc", "Cisco", "C9800-L", "10.1.1.10", s1),
    ("AC-WLC-02", "wlc", "Cisco", "3504", "10.1.1.11", s1),
    ("SWG-01", "sangfor_ac", "Sangfor", "AC-1000", "10.1.0.253", s1),
    ("SRV-DB-01", "server", "Dell", "R740(2U)", "10.2.1.1", s1),
    ("SRV-APP-01", "server", "Lenovo", "SR650(1U)", "10.2.1.2", s1),
    ("SW-BJ-01", "switch", "H3C", "S5130S", "10.3.1.1", s2),
]
created = 0
for name, code, vendor, hw, ip, site in demo_devices:
    st, page = call("GET", "/cmdb/devices/?search=" + name, tok)
    if any(d["name"] == name for d in page.get("results", [])):
        continue
    st, _ = call("POST", "/cmdb/devices/", tok, {
        "name": name, "model": models[code], "vendor": vendor, "hw_model": hw,
        "manage_ip": ip, "region": site["region"], "site": site["id"],
        "sn": "DEMO-" + name})
    created += st in (200, 201)

print("demo seeded, new devices:", created)
