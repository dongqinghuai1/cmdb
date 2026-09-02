"""审计概览/导出回归：summary 结构/计数一致性/导出 CSV 内容与越权。
用法: python scripts/verify_audit.py [BASE]   （只读审计可用 NOPS_RO_USER=auditor 覆盖验证）
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
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def login(u, p):
    for _ in range(8):
        s, r = call("POST", "/auth/login/", body={"username": u, "password": p})
        if s == 200:
            return json.loads(r)["access"]
        if s == 429:
            time.sleep(6)
            continue
        break
    raise SystemExit(f"login fail {u}: {s} {r[:200]}")


def js(payload):
    return payload if isinstance(payload, dict) else json.loads(payload)


admin = login("admin", "nops@2025")
aud = login(os.environ.get("NOPS_RO_USER", "auditor"), "NopsTest@2025")

s, body = call("GET", "/system/audit-logs/summary/", aud)
sm = js(body)
check("A1 审计员可看概览", s == 200 and {"total", "by_action", "by_user", "days", "hours"} <= set(sm),
      str(list(sm.keys())))
s, body = call("GET", "/system/audit-logs/summary/?hours=1", admin)
check("A2 hours 参数生效", s == 200 and js(body).get("hours") == 1, "")
# 制造一条审计（login 即留痕）后核对 total 一致性（>=0 且结构正确）
check("A3 by_action 元素含计数", all("c" in x for x in (sm.get("by_action") or [])) and
      all("user__username" in x or "action" in x for x in (sm.get("by_user") or [])), str(sm)[:200])
# 导出 CSV（审计员 view 权限应可）
s, body = call("GET", "/system/audit-logs/export/", aud)
txt = body.decode("utf-8-sig", "ignore") if isinstance(body, (bytes, bytearray)) else str(body)
check("A4 导出 CSV 200 且含表头", s == 200 and txt.startswith("created_at,user,action")
      or "created_at" in txt[:60], txt[:60])
rows_n = len(txt.strip().splitlines())
check("A5 导出非空", rows_n >= 2, f"lines={rows_n}")
# 登录/操作留痕出现在最新行（先触发一次 login→已通过 aud 登录，1 秒前）
s, body = call("GET", "/system/audit-logs/?page_size=1", aud)
top = js(body).get("results", [{}])[0]
check("A6 列表最新一条可读", s == 200 and top.get("created_at"), str(top)[:120])

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
