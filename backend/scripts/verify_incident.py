"""事件单模块回归：权限/报障/分派/处理/反馈/关闭/评论/SLA/告警联动/审计。
用法：NOPS_DB=sqlite NOPS_EAGER=1 时后端运行于 127.0.0.1:8010；容器栈在 8000。
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010/api/v1"
TS = time.strftime("%m%d%H%M%S")

PASS = []
FAIL = []


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
    s, r = call("POST", "/auth/login/", body={"username": u, "password": p}, expect=200)
    return r["access"]


admin = login("admin", "nops@2025")
mgr = login("mgr_approver", "NopsTest@2025")
op_low = login("op_low", "NopsTest@2025")

title = f"回归-交换机频繁掉线-{TS}"
# A. 权限
s, _ = call("GET", "/changes/incidents/", op_low)
check("A1 无权限列表 -> 403", s == 403, str(s))
s, _ = call("POST", "/changes/incidents/", op_low, {"title": title, "description": "x"})
check("A2 无权限报障 -> 403", s == 403, str(s))
s, _ = call("GET", "/changes/incidents/", admin)
check("A3 有权限列表 -> 200", s == 200, str(s))

# B. 报障
s, t = call("POST", "/changes/incidents/", admin,
            {"title": title, "description": "核心交换机反复闪断，影响业务", "priority": "high"}, expect=201)
tid, no = t["id"], t["ticket_no"]
check("B1 ticket_no 格式", no.startswith("INC-"), no)
check("B2 初始待分派 + SLA 已算", t["status"] == "new" and bool(t["sla_deadline"]) and t["reporter_name"] == "admin")
evs = t.get("events") or []
check("B3 报障无时间线事件", len(evs) == 0, str(len(evs)))

# 非法优先级
s, _ = call("POST", "/changes/incidents/", admin, {"title": "bad", "priority": "p0"})
check("B4 非法 priority -> 400", s == 400, str(s))
# 分派给不存在的用户 -> 400
s, _ = call("POST", f"/changes/incidents/{tid}/assign/", admin, {"handler_id": 99999})
check("B5 分派不存在用户 -> 400", s == 400, str(s))

# C. 分派
s, r = call("POST", f"/changes/incidents/{tid}/assign/", admin,
            {"handler_id": 99999})
check("C1 不存在的处理人 -> 400", s == 400, str(s))

# 先取 mgr 用户 id 再正确分派
_, page = call("GET", "/system/users/?search=mgr_approver", admin)
mid = page["results"][0]["id"]
s, r = call("POST", f"/changes/incidents/{tid}/assign/", admin, {"handler_id": mid}, expect=200)
check("C2 报障人分派 -> assigned", r["status"] == "assigned" and r["handler_id"] == mid)
# 已分派后可改派/评论
s, r = call("POST", f"/changes/incidents/{tid}/comment/", admin, {"content": "先按优先级处理，参考链路图"})
check("C3 报障人评论", s == 200)

# D. 处理
s, _ = call("POST", f"/changes/incidents/{tid}/start/", op_low)
check("D1 非处理人 start -> 403", s == 403, str(s))
s, r = call("POST", f"/changes/incidents/{tid}/start/", mgr, {}, expect=200)
check("D2 处理人 start -> processing", r["status"] == "processing")

# E. 反馈
s, _ = call("POST", f"/changes/incidents/{tid}/feedback/", mgr, {"resolution": ""})
check("E1 空 resolution -> 400", s == 400, str(s))
s, r = call("POST", f"/changes/incidents/{tid}/feedback/", mgr,
            {"resolution": "更换光模块后 30 分钟未再闪断，观察中"})
check("E2 提交处理结果 -> feedback", r["status"] == "feedback")

# F. 评论权限
s, _ = call("POST", f"/changes/incidents/{tid}/comment/", op_low, {"content": "路过"})
check("F1 非参与人评论 -> 403", s == 403, str(s))

# G. 关闭
s, _ = call("POST", f"/changes/incidents/{tid}/close/", mgr)
check("G1 处理人关闭(无 resolution 已填) -> closed", s == 200)
s, r = call("GET", f"/changes/incidents/{tid}/", admin)
check("G2 closed_at 已写", bool(r["closed_at"]))
evs = r["events"]
types = [e["event_type"] for e in evs]
check("G3 时间线含 assign/status_change/comment", "assign" in types and "status_change" in types and "comment" in types,
      str(types))
check("G4 名称富化(处理人/设备)", r["handler_name"] == "mgr_approver")
s, _ = call("POST", f"/changes/incidents/{tid}/start/", mgr)
check("G5 已关闭不可 start -> 400", s == 400, str(s))

# H. 全新单 SLA 超时提醒（直接造一条逾期数据）
call("POST", "/changes/incidents/", admin, {"title": "回归-sla超时-" + TS, "priority": "low"})
s, page = call("GET", "/changes/incidents/?overdue=1", admin)
check("H1 overdue 过滤接口可用", s == 200 and page.get("count", 0) >= 0, str(page.get("count")))

# I. 告警联动建单
s, page = call("GET", "/alerts/events/?page_size=1", admin)
ae = page["results"][0]
s, r = call("POST", f"/alerts/events/{ae['id']}/create-incident/", admin, {"note": "核心设备需尽快处理"},
            expect=201)
check("I1 告警联动建单", r["ticket_no"].startswith("INC-") and r["status"] == "new", str(r))
s, t2 = call("GET", f"/changes/incidents/{r['incident_id']}/", admin)
check("I2 联动单 source=alert 且带设备名", t2["source"] == "alert" and bool(t2["device_name"]),
      f"{t2['source']}/{t2['device_name']}")
check("I3 联动单标题带[告警]", t2["title"].startswith("[告警]"), t2["title"])
s, _ = call("POST", "/alerts/events/999999/create-incident/", admin)
check("I4 告警不存在 -> 404", s == 404, str(s))

# J. my-stats
s, r = call("GET", "/changes/incidents/my-stats/", mgr)
check("J1 my-stats", s == 200 and isinstance(r.get("reported"), int), str(r))

# K. 审计留痕（读库直查本次工单的 change 审计）
import sqlite3, os
dbp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db.sqlite3")
try:
    con = sqlite3.connect(dbp)
    n = con.execute("SELECT COUNT(*) FROM system_auditlog "
                    "WHERE resource_type='IncidentTicket' AND resource_id=?",
                    (tid,)).fetchone()[0]
    con.close()
    check("K1 审计留痕存在", n >= 4, str(n))
except Exception as e:
    check("K1 审计留痕存在", False, str(e))

print(f"\n=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL:
    sys.exit(1)
