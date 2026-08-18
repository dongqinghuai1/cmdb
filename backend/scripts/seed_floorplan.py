"""Seed a sample floor-plan for idc-sh so users see the panorama immediately."""
import json
import urllib.request

BASE = "http://localhost:8000/api/v1"


def call(method, path, tok=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data) as r:
        return r.status, json.loads(r.read() or b"{}")


_, r = call("POST", "/auth/login/", body={"username": "admin", "password": "nops@2025"})
tok = r["access"]

_, sl = call("GET", "/dcim/sites/?search=idc-sh", tok)
site = next((s for s in sl["results"] if s["code"] == "idc-sh"), None)
if not site:
    print("site idc-sh missing; run seed_demo first")
    raise SystemExit(1)

_, rks = call("GET", "/dcim/racks/?page_size=100", tok)
racks = {k["name"]: k["id"] for k in rks["results"] if k["site"] == site["id"]}

objects = [
    # 两排机柜：A 排靠上，B 排靠下
    {"obj_type": "rack", "name": "A01", "rack_id": racks.get("A01"), "x": 1.0, "y": 1.0, "w": 0.6, "h": 1.2},
    {"obj_type": "rack", "name": "A02", "rack_id": racks.get("A02"), "x": 2.0, "y": 1.0, "w": 0.6, "h": 1.2},
    {"obj_type": "rack", "name": "预留位", "rack_id": None, "x": 3.0, "y": 1.0, "w": 0.6, "h": 1.2, "meta": {"note": "future"}},
    # B 排
    {"obj_type": "rack", "name": "B01", "rack_id": racks.get("B01"), "x": 1.0, "y": 4.0, "w": 0.6, "h": 1.2},
    # 基础设施
    {"obj_type": "ups", "name": "UPS主机", "x": 6.0, "y": 1.0, "w": 1.5, "h": 1.0},
    {"obj_type": "power", "name": "配电箱", "x": 6.0, "y": 3.0, "w": 0.8, "h": 0.6},
    {"obj_type": "fire", "name": "气体灭火钢瓶", "x": 6.5, "y": 4.5, "w": 0.8, "h": 0.8},
    {"obj_type": "ap", "name": "AP-天花板", "x": 3.5, "y": 3.0, "w": 0.4, "h": 0.4},
    {"obj_type": "door", "name": "入口门", "x": 0.1, "y": 6.0, "w": 1.2, "h": 0.3},
]

st, r = call("POST", "/dcim/site-objects/bulk/", tok, {
    "site": site["id"], "floor_len_m": 8, "floor_w_m": 7, "objects": objects})
print("floorplan seeded:", st, r)
