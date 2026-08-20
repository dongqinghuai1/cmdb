import json
import urllib.error
import urllib.request

B = "http://localhost:8000/api/v1"
ok = fail = 0


def call(method, path, tok=None, body=None):
    req = urllib.request.Request(B + path, method=method)
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
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra)[:160] if not cond else ""))
    globals()["ok" if cond else "fail"] += 1


tok = call("POST", "/auth/login/", body={"username": "admin", "password": "nops@2025"})[1]["access"]
_, dv = call("GET", "/cmdb/devices/?search=SW-CORE-01", tok)
dev = dv["results"][0]["id"]

cfg1 = ("sysname SW-CORE-01\nvlan 10\nvlan 20\ninfo-center loghost 10.0.0.100\n"
        "interface GE1/0/1\n port link-type trunk\nntp-service unicast-server 10.0.0.1\n")
cfg2 = cfg1.replace("vlan 20", "vlan 30").replace("loghost 10.0.0.100", "loghost 10.0.0.200")

st, r1 = call("POST", "/ncm/backups/import/", tok, {"device": dev, "content": cfg1})
check("import v1", st == 200 and r1.get("changed"), (st, r1))
st, r2 = call("POST", "/ncm/backups/import/", tok, {"device": dev, "content": cfg1})
check("import same v1 dedup (changed=False)", st == 200 and r2.get("changed") is False, (st, r2))
st, r3 = call("POST", "/ncm/backups/import/", tok, {"device": dev, "content": cfg2})
check("import v2 changed", st == 200 and r3.get("changed"), (st, r3))

st, evs = call("GET", "/ncm/change-events/?device_id=" + str(dev), tok)
check("change event created", evs.get("count", 0) >= 1 and evs["results"][0]["changed_lines"] >= 2,
      evs.get("results", [])[:1])
ev = evs["results"][0]

st, d = call("GET", "/ncm/backups/diff/?a=%d&b=%d" % (ev["old_backup_id"], ev["new_backup_id"]), tok)
check("diff has +/- lines", st == 200 and "-vlan 20" in d.get("diff", "") and "+vlan 30" in d.get("diff", ""),
      (st, d.get("diff", "")[:120]))

st, c = call("GET", "/ncm/backups/" + str(ev["new_backup_id"]) + "/content/", tok)
check("content readable (decrypt)", st == 200 and "SW-CORE-01" in c.get("content", ""), (st, c))

st, rule = call("POST", "/ncm/baseline-rules/", tok,
                {"name": "T-loghost", "rule_type": "must_present", "pattern": "info-center loghost"})
check("baseline rule create", st in (200, 201), (st, rule))
if "id" in rule:
    st, rc = call("POST", "/ncm/baseline-rules/check/", tok, {"rule_ids": [rule["id"]]})
    st2, rs = call("GET", "/ncm/baseline-results/?rule=%d&compliant=true" % rule["id"], tok)
    check("baseline check compliant", st == 200 and rc.get("checked", 0) >= 1 and rs.get("count", 0) >= 1,
          (rc, rs.get("results", [])[:1]))

# 清理基线规则（保留备份与事件作为演示数据）
call("DELETE", "/ncm/baseline-rules/" + str(rule.get("id", 0)) + "/", tok)

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
import sys
sys.exit(1 if fail else 0)
