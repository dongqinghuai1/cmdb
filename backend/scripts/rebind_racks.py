"""Re-bind floor rack objects to real racks by name (repair lost rack_id)."""
import json
import urllib.request

B = "http://localhost:8000/api/v1"


def call(method, path, tok=None, body=None):
    req = urllib.request.Request(B + path, method=method)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data) as r:
        return json.loads(r.read() or b"{}")


tok = call("POST", "/auth/login/", body={"username": "admin", "password": "nops@2025"})["access"]

for code in ["idc-sh", "idc-bj"]:
    sl = call("GET", "/dcim/sites/?search=" + code, tok)["results"]
    if not sl:
        continue
    s = sl[0]
    objs = call("GET", "/dcim/site-objects/?site=" + str(s["id"]) + "&page_size=500", tok)["results"]
    racks = call("GET", "/dcim/racks/?site=" + str(s["id"]) + "&page_size=200", tok)["results"]
    by_name = {r["name"]: r["id"] for r in racks}
    # 补建缺失的实体机柜（以平面图上的机柜元素名为准）
    for o in objs:
        if o["obj_type"] == "rack" and o["name"] and o["name"] not in by_name:
            try:
                nr = call("POST", "/dcim/racks/", tok, {"name": o["name"], "site": s["id"], "u_total": 42})
                by_name[o["name"]] = nr["id"]
                print(code, "created rack:", o["name"])
            except Exception as e:
                print("create rack failed:", o["name"], e)
    fixed = 0
    for o in objs:
        if o["obj_type"] == "rack" and not o["rack_id"] and o["name"] in by_name:
            o["rack_id"] = by_name[o["name"]]
            fixed += 1
    # 机柜元素尺寸规范化为标准机柜（0.6m x 1.2m）——用户之前误拉伸
    for o in objs:
        if o["obj_type"] == "rack" and o["rack_id"]:
            o["w"], o["h"] = 0.6, 1.2
    if objs:
        r = call("POST", "/dcim/site-objects/bulk/", tok,
                 {"site": s["id"], "floor_len_m": s["floor_len_m"] or 12,
                  "floor_w_m": s["floor_w_m"] or 8, "objects": objs})
        print(code, "rebound:", fixed, "saved:", r.get("saved"))
