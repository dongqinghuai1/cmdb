"""轻量变更单回归：权限护栏 / 申请->审批(复用 Approval)->实施->验证->关闭 / 驳回 / 回滚 / 审计。
用法：NOPS_DB=sqlite NOPS_EAGER=1 后端 127.0.0.1:8010（容器栈为 8000）。
"""
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010/api/v1"
TS = time.strftime("%m%d%H%M%S")
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" | {extra}" if extra and not cond else ""))


def call(method, path, tok=None, body=None, expect=None):
    if "?" in path:
        base, q = path.split("?", 1)
        path = base + "?" + urllib.parse.urlencode(urllib.parse.parse_qsl(q))
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=15) as r:
            code, raw = r.status, r.read() or b"{}"
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read() or b"{}"
    try:
        payload = json.loads(raw)
    except Exception:
        payload = {}
    if expect is not None and code != expect:
        raise AssertionError(f"{method} {path} -> {code}, want {expect}: {payload}")
    return code, payload


def login(u, p):
    for _ in range(8):
        s, r = call("POST", "/auth/login/", body={"username": u, "password": p})
        if s == 200:
            return r["access"]
        if s == 429:
            time.sleep(6)
            continue
        break
    raise AssertionError(f"login {u} failed: {s} {r}")


admin = login("admin", "nops@2025")
mgr = login("mgr_approver", "NopsTest@2025")
ro = login("op_low", "NopsTest@2025")
viewer = login("viewer_x", "NopsTest@2025")

_, us = call("GET", "/system/users/?page_size=200", admin)
by_name = {u["username"]: u["id"] for u in us["results"]}
mid, roid = by_name["mgr_approver"], by_name["op_low"]

PLAN = {"plan_start": "2026-09-10T01:00:00+08:00", "plan_end": "2026-09-10T03:00:00+08:00"}
CONTENT = {"summary": "核心交换机割接配置", "impact": "影响 1 分钟", "steps": "1)备份 2)下发 3)验证",
           "affected_device_ids": [1, 2]}
TITLE = f"回归-核心割接-{TS}"


def make_draft(title):
    return call("POST", "/changes/change-tickets/", admin,
                {"title": title, "change_type": "network", "risk_level": "high",
                 "content": CONTENT}, expect=201)


# A. 权限
s, _ = call("GET", "/changes/change-tickets/", ro)
check("A1 只读无变更查看? 读readonly授权view", s == 200, str(s))
s, _ = call("POST", "/changes/change-tickets/", ro, {"title": "x"})
check("A2 只读无编辑权限申请 -> 403", s == 403, str(s))
s, t1 = make_draft(TITLE)
check("A3 申请人建草稿", t1["status"] == "draft" and t1["ticket_no"].startswith("CHG-"), t1["ticket_no"])
tid = t1["id"]

# B. 提交校验
s, _ = call("POST", f"/changes/change-tickets/{tid}/submit/", admin, {"approver_id": mid, "content": CONTENT})
check("B1 缺窗口 -> 400", s == 400, str(s))
s, _ = call("POST", f"/changes/change-tickets/{tid}/submit/", admin,
            {"approver_id": mid, "implementer_id": mid, "verifier_id": mid,
             "content": CONTENT, **PLAN})
check("B2 验证=实施 -> 400", s == 400, str(s))
s, _ = call("POST", f"/changes/change-tickets/{tid}/submit/", admin,
            {"approver_id": mid, "implementer_id": mid, "verifier_id": roid,
             "content": {}, **PLAN})
check("B3 内容缺 summary -> 400", s == 400, str(s))
s, t = call("POST", f"/changes/change-tickets/{tid}/submit/", admin,
            {"approver_id": mid, "implementer_id": mid, "verifier_id": roid,
             "content": CONTENT, **PLAN}, expect=200)
check("B4 提交 -> approving + 审批单生成", t["status"] == "approving" and bool(t["approval_id"]), str(t))
s, _ = call("POST", f"/changes/change-tickets/{tid}/submit/", admin,
            {"approver_id": mid, "content": CONTENT, **PLAN})
check("B5 重复提交 -> 400", s == 400, str(s))

# C. 审批
s, _ = call("POST", f"/changes/change-tickets/{tid}/approve/", ro)
check("C1 非审批人 approve -> 403", s == 403, str(s))
s, t = call("POST", f"/changes/change-tickets/{tid}/approve/", mgr, {"comment": "同意割接"}, expect=200)
check("C2 审批人通过 -> approved", t["status"] == "approved" and t.get("approval") == "approved", str(t))
s, d = call("GET", f"/changes/change-tickets/{tid}/", admin)
check("C3 富化(申请人/实施人/审批意见)", d["applicant_name"] == "admin" and d["implementer_name"] == "mgr_approver"
      and d["approval_comment"] == "同意割接", str({k: d[k] for k in ("applicant_name", "implementer_name", "approval_comment")}))

# D. 实施/验证/关闭
s, t = call("POST", f"/changes/change-tickets/{tid}/start/", mgr, {}, expect=200)
check("D1 实施人 start -> implementing+actual_start", t["status"] == "implementing" and bool(t["actual_start"]))
s, _ = call("POST", f"/changes/change-tickets/{tid}/verify/", viewer, {"result_desc": "x"})
check("D2 非验证人且无执行权 verify -> 403", s == 403, str(s))
s, _ = call("POST", f"/changes/change-tickets/{tid}/verify/", mgr, {"result_desc": ""})
check("D3 空验证结果 -> 400", s == 400, str(s))
s, t = call("POST", f"/changes/change-tickets/{tid}/verify/", ro,
            {"result_desc": "割接完成，业务 2 分钟恢复"}, expect=200)
check("D4 验证人(身份) verify -> verifying", t["status"] == "verifying", str(t))
s, t = call("POST", f"/changes/change-tickets/{tid}/close/", mgr, {}, expect=200)
check("D5 关闭 -> closed", t["status"] == "closed", str(t))

# E. 驳回链路
s, t2 = make_draft(TITLE + "-驳回")
tid2 = t2["id"]
call("POST", f"/changes/change-tickets/{tid2}/submit/", admin,
     {"approver_id": mid, "implementer_id": mid, "verifier_id": roid,
      "content": CONTENT, **PLAN}, expect=200)
s, _ = call("POST", f"/changes/change-tickets/{tid2}/reject/", mgr, {})
check("E1 驳回缺原因 -> 400", s == 400, str(s))
s, t = call("POST", f"/changes/change-tickets/{tid2}/reject/", mgr, {"comment": "窗口冲突，改期重提"}, expect=200)
check("E2 驳回 -> rejected + 审批行驳回", t["status"] == "rejected" and t["approval"] == "rejected", str(t))
s, d2 = call("GET", f"/changes/change-tickets/{tid2}/", admin)
check("E2b 驳回原因入审批意见", d2["approval_comment"] == "窗口冲突，改期重提", str(d2.get("approval_comment")))
s, _ = call("POST", f"/changes/change-tickets/{tid2}/start/", mgr)
check("E3 驳回后不可实施 -> 400", s == 400, str(s))

# F. 回滚链路
s, t3 = make_draft(TITLE + "-回滚")
tid3 = t3["id"]
call("POST", f"/changes/change-tickets/{tid3}/submit/", admin,
     {"approver_id": mid, "implementer_id": mid, "verifier_id": roid,
      "content": CONTENT, **PLAN}, expect=200)
call("POST", f"/changes/change-tickets/{tid3}/approve/", mgr, {"comment": "同意"}, expect=200)
call("POST", f"/changes/change-tickets/{tid3}/start/", mgr, {}, expect=200)
s, _ = call("POST", f"/changes/change-tickets/{tid3}/rollback/", mgr, {})
check("F1 回滚缺方案 -> 400", s == 400, str(s))
s, t = call("POST", f"/changes/change-tickets/{tid3}/rollback/", mgr,
            {"rollback_plan": "恢复上一配置版本"}, expect=200)
check("F2 回滚 -> rolledback", t["status"] == "rolledback", str(t))
s, d3 = call("GET", f"/changes/change-tickets/{tid3}/", admin)
check("F2b 回滚方案已存", d3["rollback_plan"] == "恢复上一配置版本", str(d3.get("rollback_plan")))
s, _ = call("POST", f"/changes/change-tickets/{tid3}/verify/", admin, {"result_desc": "x"})
check("F3 回滚后不可验证 -> 400", s == 400, str(s))

# G. 列表/检索/审批单落库
s, page = call("GET", "/changes/change-tickets/?status=closed&search=" + urllib.parse.quote("回归-核心割接"), admin)
check("G1 closed 检索命中", page.get("count", 0) >= 1, str(page.get("count")))
s, page = call("GET", "/changes/change-tickets/?mine=implement", mgr)
check("G2 我的实施(含全部状态)>=2", page.get("count", 0) >= 2, str(page.get("count")))
dbp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db.sqlite3")
con = sqlite3.connect(dbp)
rows = con.execute("SELECT status, count(*) FROM automate_approval WHERE biz_type='change_ticket' "
                   "GROUP BY status").fetchall()
con.close()
stat = dict(rows)
check("G3 Approval 复用落库(approved/rejected)", stat.get("approved", 0) >= 2 and stat.get("rejected", 0) >= 1, str(rows))
con = sqlite3.connect(dbp)
n = con.execute("SELECT COUNT(*) FROM system_auditlog WHERE resource_type='ChangeTicket' "
                "AND resource_id IN (?,?,?)", (tid, tid2, tid3)).fetchone()[0]
con.close()
check("G4 审计留痕(三单合计>=12)", n >= 12, str(n))

print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
sys.exit(1 if FAIL else 0)
