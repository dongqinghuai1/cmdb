"""链路质量时间序列回归：按需取样(权限)/取样计数/概览聚合结构/降采样桶数。
用法: python scripts/verify_linkq.py [BASE]   （execute 账号=admin；只读验证用 NOPS_RO_USER）
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010/api/v1")
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


def call(method, path, tok=None, body=None, q=""):
    req = urllib.request.Request(BASE + path + (("?" + q) if q else ""), method=method)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def login(u, p):
    for _ in range(8):
        s, r = call("POST", "/auth/login/", body={"username": u, "password": p})
        if s == 200:
            return r["access"]
        if s == 429:
            time.sleep(6)
            continue
        break
    raise SystemExit(f"login fail {u}: {s}")


admin = login("admin", "nops@2025")
ro = login(os.environ.get("NOPS_RO_USER", "op_low"), "NopsTest@2025")

s, r = call("POST", "/cmdb/devices/link-quality-sample/", ro, {})
check("Q1 只读取样 -> 403", s == 403, str(s))
s, r = call("POST", "/cmdb/devices/link-quality-sample/", admin, {"keep_days": 7})
check("Q2 按需取样执行", s == 200 and isinstance(r.get("sampled"), int), str(r)[:120])
s, r = call("POST", "/cmdb/devices/link-quality-sample/", admin, {"keep_days": "x"})
check("Q3 非法 keep_days -> 400", s == 400, str(s))
s, ov = call("GET", "/cmdb/devices/link-quality-overview/?hours=48", admin)
ifs_ = ov.get("interfaces", [])
check("Q4 概览结构", s == 200 and "hours" in ov and isinstance(ifs_, list), str(ov)[:160])
if ifs_:
    q = ifs_[0]
    ok_shape = all(k in q for k in ("interface_id", "device", "iface", "samples",
                                    "avg_in", "peak_in", "peak_err", "buckets"))
    check("Q5 接口条目字段", ok_shape, str(q)[:200])
    check("Q6 桶数 <=36 且单调时间", len(q.get("buckets", [])) <= 36
          and all(q["buckets"][i]["ts"] <= q["buckets"][i + 1]["ts"]
                  for i in range(len(q["buckets"]) - 1)), str(len(q.get("buckets", []))))
    check("Q7 平均 <= 峰值", q.get("avg_in", 0) <= q.get("peak_in", 1), "")
else:
    check("Q5-Q7 跳过（当前无接口统计源）", True, "no interfaces yet")
s, ro2 = call("GET", "/cmdb/devices/link-quality-overview/", ro)
check("Q8 只读可看概览", s == 200, str(s))
# 清理：保留 0 天清空历史
s, r = call("POST", "/cmdb/devices/link-quality-sample/", admin, {"keep_days": 0})
check("Q9 清理执行(keep_days=0)", s == 200 and isinstance(r.get("deleted"), int), str(r)[:120])

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
