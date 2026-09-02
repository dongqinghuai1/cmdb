"""CMDB 基础补齐 Round-1 回归：数据质量/回收站恢复与彻底删除/附件上传下载/维保License/变更历史/动态分组evaluate/软件版本一致性。
用法: python scripts/verify_cmdb_r1.py [BASE]
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010/api/v1")
TS = time.strftime("%m%d%H%M%S")
PASS = 0
FAIL = 0


def check(name, ok, extra=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"PASS {name}")
    else:
        FAIL += 1
        print(f"FAIL {name} | {extra}")


def call(method, path, tok=None, body=None, raw=False):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=20) as r:
            code, rawb = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, rawb = e.code, e.read()
    if raw:
        return code, rawb
    try:
        return code, json.loads(rawb or b"{}")
    except Exception:
        return code, {}


def upload(device_id, fname, content, tok, ftype="other"):
    boundary = "BOUNDARY" + uuid.uuid4().hex
    def part(name, value, isfile=False):
        if not isfile:
            return (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                    f'{value}\r\n').encode()
        return (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{fname}"\r\nContent-Type: text/plain\r\n\r\n').encode() + value + b"\r\n"
    body = (part("device_id", device_id) + part("file_type", ftype) +
            part("file", content, True) + f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(BASE + "/cmdb/attachments/", data=body, method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
    req.add_header("Authorization", "Bearer " + tok)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def login(u, p):
    for _ in range(8):
        s, r = call("POST", "/auth/login/", body={"username": u, "password": p})
        if s == 200:
            return r["access"]
        if s == 429:
            time.sleep(6)
            continue
        break
    raise SystemExit(f"login fail {u}: {s} {r}")


def pk(x):
    return x if isinstance(x, int) else x.get("id")


admin = login("admin", "nops@2025")
ro_user = os.environ.get("NOPS_RO_USER", "op_low")
op = login(ro_user, "NopsTest@2025")

# 基准设备
_, lst = call("GET", "/cmdb/devices/?page_size=1", admin)
base = lst["results"][0]
DEV = {"model": pk(base["model"]), "site": pk(base["site"]), "region": pk(base["region"])}

# ---------- A 数据质量看板 ----------
s, q = call("GET", "/cmdb/devices/data-quality/", admin)
keys = ["no_sn", "no_owner", "no_warranty", "no_vendor", "no_sw_version", "no_rack", "no_manage_ip"]
check("A1 数据质量 summary 含全部指标", s == 200 and all(k in q.get("summary", {}) for k in keys) and
      all(isinstance(v, int) for v in q["summary"].values()), str(q.get("summary"))[:200])
s, q = call("GET", "/cmdb/devices/data-quality/?kind=no_sn", admin)
check("A2 缺失清单返回行", s == 200 and isinstance(q.get("rows"), list) and
      len(q["rows"]) == q["summary"]["no_sn"], f"rows={len(q.get('rows', []))}")

# ---------- B 回收站：软删->列表->恢复->再删->彻底删除 ----------
bname = f"回收站测试-{TS}"
s, d = call("POST", "/cmdb/devices/", admin, {**DEV, "name": bname, "vendor": "Acme",
                                             "hw_model": "SW-1", "sw_version": "1.2.3"})
check("B1 建测试设备", s == 201, str(d)[:200])
tid = d["id"]
s, _ = call("DELETE", f"/cmdb/devices/{tid}/", admin)
check("B2 软删除 204", s == 204, str(s))
s, page = call("GET", "/cmdb/devices/?deleted=1&page_size=500", admin)
ids = [r["id"] for r in page["results"]]
check("B3 回收站列表含该设备", tid in ids, f"deleted list={len(ids)}")
s, rd = call("POST", f"/cmdb/devices/{tid}/restore/", admin)
check("B4 恢复 -> 200", s == 200 and rd.get("id") == tid, str(rd)[:200])
s, page = call("GET", "/cmdb/devices/?deleted=1&page_size=500", admin)
check("B5 恢复后不在回收站", tid not in [r["id"] for r in page["results"]])
s, _ = call("DELETE", f"/cmdb/devices/{tid}/", admin)
s, rp = call("POST", f"/cmdb/devices/{tid}/purge/", admin, {"confirm": "1"})
check("B6 彻底删除", s == 200 and rp.get("detail") == "purged", str(rp)[:120])
s, page = call("GET", "/cmdb/devices/?deleted=1&page_size=500", admin)
check("B7 彻底删除后消失", tid not in [r["id"] for r in page["results"]])
s, _ = call("POST", f"/cmdb/devices/{pk(base['id']) if False else base['id']}/restore/", op)
check("B8 只读用户 restore -> 403", s == 403, str(s))
s, _ = call("POST", f"/cmdb/devices/{base['id']}/purge/", op, {"confirm": "1"})
check("B9 只读用户 purge -> 403", s == 403, str(s))

# ---------- C 维保/合同 License ----------
s, _ = call("POST", "/cmdb/licenses/", op, {"device_id": base["id"], "license_type": "OS"})
check("C1 只读用户建维保 -> 403", s == 403, str(s))
s, lic = call("POST", "/cmdb/licenses/", admin, {"device_id": base["id"], "license_type": "OS",
                                                 "seats": 10, "expire_at": "2027-12-31",
                                                 "supplier": "Acme", "contract_no": "C-1"})
check("C2 建维保记录", s == 201 and lic.get("license_type") == "OS", str(lic)[:200])
lid = lic["id"]
s, page = call("GET", f"/cmdb/licenses/?device_id={base['id']}", admin)
check("C3 按设备查维保", s == 200 and any(r["id"] == lid for r in page["results"]))
s, lic2 = call("PATCH", f"/cmdb/licenses/{lid}/", admin, {"seats": 20})
check("C4 更新维保", s == 200 and lic2.get("seats") == 20, str(lic2)[:120])
s, _ = call("DELETE", f"/cmdb/licenses/{lid}/", op)
check("C5 只读用户删维保 -> 403", s == 403, str(s))
s, _ = call("DELETE", f"/cmdb/licenses/{lid}/", admin)
check("C6 删除维保", s == 204, str(s))

# ---------- D 附件 上传/下载/删除 ----------
content = b"cmdb-attach-check-12345-" + TS.encode()
s, _ = upload(base["id"], "t.txt", content, op)
check("D1 只读用户上传 -> 403", s == 403, str(s))
s, at = upload(base["id"], f"证明-{TS}.txt", content, admin, ftype="contract")
check("D2 上传附件", s == 201 and at.get("file_name", "").endswith(".txt") and at.get("size") == len(content),
      str(at)[:160])
aid = at["id"]
s, rows = call("GET", f"/cmdb/attachments/?device_id={base['id']}", admin)
check("D3 附件列表", s == 200 and any(r["id"] == aid for r in rows) and rows[0]["uploaded_by"] == "admin",
      str(rows)[:200])
s, rawb = call("GET", f"/cmdb/attachments/{aid}/download/", admin, raw=True)
check("D4 下载内容一致", s == 200 and rawb == content, f"len={len(rawb)}")
s, _ = call("DELETE", f"/cmdb/attachments/{aid}/", admin)
check("D5 删除附件", s == 204, str(s))

# ---------- E 变更历史（审计流水） ----------
orig_name = base["name"]
s, _ = call("PATCH", f"/cmdb/devices/{base['id']}/", admin, {"name": orig_name + "-hist"})
s, _ = call("PATCH", f"/cmdb/devices/{base['id']}/", admin, {"name": orig_name})
s, rows = call("GET", f"/cmdb/devices/{base['id']}/history/", admin)
acts = [r["action"] for r in rows] if isinstance(rows, list) else []
check("E1 变更历史含 update 流水", s == 200 and acts.count("update") >= 2,
      f"actions={acts[:6]}" if isinstance(rows, list) else str(rows)[:160])
s, rows = call("GET", f"/cmdb/devices/{base['id']}/history/", op)
check("E2 只读用户可看历史", s == 200 and isinstance(rows, list), str(s))

# ---------- F 动态分组 evaluate ----------
rule = {}
if base.get("vendor"):
    rule["vendor"] = base["vendor"]
else:
    bcode = base["model"].get("code") if isinstance(base["model"], dict) else None
    if bcode:
        rule["model"] = bcode
s, g = call("POST", "/cmdb/groups/", admin, {"name": f"回归动态组-{TS}", "group_type": "dynamic",
                                             "filter": rule})
check("F1 建动态分组", s == 201, str(g)[:200])
gid = g["id"]
s, _ = call("POST", f"/cmdb/groups/{gid}/evaluate/", op, {"apply": True})
check("F2 只读用户 evaluate -> 403", s == 403, str(s))
s, ev = call("POST", f"/cmdb/groups/{gid}/evaluate/", admin, {"apply": True})
check("F3 动态分组评估并应用", s == 200 and ev.get("applied") == ev.get("matched") and
      ev.get("applied", 0) >= 1, str(ev)[:160])
s, mem = call("GET", f"/cmdb/groups/{gid}/members/", admin)
check("F4 成员数与规则一致", s == 200 and mem.get("count") == ev.get("applied"), str(mem)[:160])
s, _ = call("POST", "/cmdb/groups/", admin, {"name": f"回归动态组2-{TS}", "group_type": "dynamic"})
g2 = json.loads('{}')
if s == 201:
    g2 = {"id": _["id"]}
s, ev0 = call("POST", f"/cmdb/groups/{g2['id']}/evaluate/", admin, {"filter": {}, "apply": True})
check("F5 空规则命中全部在用设备", s == 200 and ev0.get("matched", 0) >= 1, str(ev0)[:160])
for gid2 in (gid, g2["id"]):
    call("DELETE", f"/cmdb/groups/{gid2}/", admin)
s, _ = call("POST", f"/cmdb/groups/{gid}/evaluate/", admin, {"filter": {}})
check("F6 删除后的组不可用", s in (404, 405), str(s))

# ---------- G 软件版本一致性 ----------
s, sv = call("GET", "/cmdb/devices/software-summary/", admin)
check("G1 版本分布接口", s == 200 and isinstance(sv, list) and all("c" in r for r in sv),
      str(sv)[:160])
s, dev2 = call("POST", "/cmdb/devices/", admin, {**DEV, "name": f"版本测试-{TS}", "vendor": "Acme",
                                                 "hw_model": "SW-9", "sw_version": "9.9.9"})
check("G2 再造一台带版本设备", s == 201, str(dev2)[:120])
s, sv = call("GET", "/cmdb/devices/software-summary/", admin)
hit = any(r.get("hw_model") == "SW-9" and r.get("sw_version") == "9.9.9" and r.get("c", 0) >= 1 for r in sv)
check("G3 版本分布含新设备", s == 200 and hit, str(sv)[:200])

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
