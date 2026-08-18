import json
import urllib.error
import urllib.request

B = "http://localhost:8000/api/v1"


def call(method, path, token=None, body=None):
    req = urllib.request.Request(B + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {"raw": e.read().decode()[:150]}


_, r = call("POST", "/auth/login/", body={"username": "admin", "password": "nops@2025"})
tok = r["access"]

_, m = call("GET", "/cmdb/models/", tok)
sw = next(x["id"] for x in m["results"] if x["code"] == "switch")
_, rl = call("GET", "/dcim/regions/?search=t-reg", tok)
reg = rl["results"][0]["id"]
_, sl = call("GET", "/dcim/sites/?search=t-site", tok)
site = sl["results"][0]["id"]

st, dev = call("POST", "/cmdb/devices/", tok, {"name": "T-HARD", "model": sw, "region": reg, "site": site})
print("created", st, dev.get("id"))
print("delete:", call("DELETE", "/cmdb/devices/%d/?hard=1" % dev["id"], tok))
