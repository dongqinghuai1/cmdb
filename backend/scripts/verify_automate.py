"""automate 模块回归：脚本库 CRUD / 批量执行 / 高危审批闭环 / 灰度批次 / 权限护栏。

前置：本地 API 已跑（NOPS_EAGER=1 + automate.mock_execute 开 + 演示设备≥3 台）。
幂等：脚本按固定标识复用；执行记录只增不清理（历史语义）。
用法：python scripts/verify_automate.py [BASE_URL]
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/api/v1"
ADMIN_PWD, MGR_PWD, OPS_PWD = "nops@2025", "NopsTest@2025", "NopsOps@2025"

_passed = _failed = 0


def ok(cond, msg):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {msg}")
    else:
        _failed += 1
        print(f"  FAIL  {msg}")


def call(method, path, tok=None, body=None, expect=None):
    if "?" in path:  # 查询参数做百分号编码（中文搜索词等）
        base, q = path.split("?", 1)
        qs = urllib.parse.urlencode(urllib.parse.parse_qsl(q, keep_blank_values=True))
        path = f"{base}?{qs}"
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            st = r.status
            payload = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        st = e.code
        try:
            payload = json.loads(e.read() or b"{}")
        except Exception:
            payload = {}
    if expect is not None:
        ok(st == expect, f"{method} {path} -> {st} (expect {expect}) {payload if st != expect else ''}")
    return st, payload


def login(u, p):
    st, r = call("POST", "/auth/login/", body={"username": u, "password": p})
    return r.get("access") if st == 200 else None


def ensure_user(u, p):
    tok = login(u, p)
    if tok:
        return tok, True
    st, r = call("POST", "/system/users/", tok=login("admin", ADMIN_PWD),
                 body={"username": u, "password": p}, expect=201)
    return login(u, p), False


def find_script(tok, name):
    st, r = call("GET", "/automate/scripts/?page_size=100", tok)
    return next((s for s in r.get("results", []) if s["name"] == name), None)


def main():
    print("== automate 回归 ==")
    admin = login("admin", ADMIN_PWD)
    ok(bool(admin), "admin 登录")
    if not admin:
        return
    mgr, _ = ensure_user("mgr_approver", MGR_PWD)
    ops, _ = ensure_user("op_low", OPS_PWD)  # 无任何角色 -> 权限护栏用
    devs = call("GET", "/cmdb/devices/?page_size=200", admin)[1].get("results", [])
    ids = [d["id"] for d in devs]
    ok(len(ids) >= 3, f"演示设备 >= 3 台（当前 {len(ids)}）")
    d1, d2, d3 = ids[:3]

    # ---------- A. 脚本库 ----------
    print("[A] 脚本库 CRUD")
    low = find_script(admin, "reg_接口状态收集")
    if not low:
        st, low = call("POST", "/automate/scripts/", admin, {
            "name": "reg_接口状态收集", "category": "网络巡检", "script_type": "cli_command",
            "content": "show interface brief", "danger_level": "low", "enabled": True}, expect=201)
    high = find_script(admin, "reg_高危端口重启")
    if not high:
        st, high = call("POST", "/automate/scripts/", admin, {
            "name": "reg_高危端口重启", "category": "端口操作", "script_type": "cli_command",
            "content": "interface Gi0/0/1\nshutdown", "danger_level": "high", "enabled": True,
            "params_schema": [{"key": "port", "label": "端口", "required": True}]}, expect=201)
    ok(high.get("requires_approval") is True, "高危脚本 requires_approval=True")
    st, upd = call("PATCH", f"/automate/scripts/{low['id']}/", admin,
                   {"remark": "回归脚本-可改"}, expect=200)
    ok(st == 200 and upd.get("remark") == "回归脚本-可改", "脚本编辑(remark)")
    st, _ = call("GET", "/automate/scripts/?search=接口状态", admin)
    ok(st == 200, "脚本搜索")

    # 无角色用户看不到（无权限点）-> 403
    st, _ = call("GET", "/automate/scripts/", ops)
    ok(st == 403, f"无权限用户访问脚本库 403 (got {st})")

    # ---------- B. 低危批量执行（mock） ----------
    print("[B] 低危批量执行")
    st, r = call("POST", "/automate/script-runs/", admin,
                 {"script_id": low["id"], "scope": {"device_ids": [d1, d2]}}, expect=201)
    run = r.get("run", {})
    ok(r.get("need_approval") is False and run.get("status") == "pending",
       "低危创建无需审批且 pending")
    rid = run["id"]
    st, _ = call("POST", f"/automate/script-runs/{rid}/start/", admin, {}, expect=200)
    st, r2 = call("GET", f"/automate/script-runs/{rid}/", admin)
    stats = r2.get("stats", {})
    ok(r2.get("status") == "success" and stats.get("success") == 2,
       f"低危执行终态 success 2/2 (got {r2.get('status')} {stats})")
    st, det = call("GET", f"/automate/script-runs/{rid}/details/?page_size=50", admin)
    outs = det.get("results", [])
    ok(len(outs) == 2 and outs[0]["status"] == "success" and "[mock]" in (outs[0]["output"] or ""),
       "明细 2 条且含 mock 回显")
    ok(all(x.get("device_name") and x["device_name"] != "-" for x in outs), "明细带设备名")

    # 取消未启动任务
    st, r3 = call("POST", "/automate/script-runs/", admin,
                  {"script_id": low["id"], "scope": {"device_ids": [d1]}}, expect=201)
    rid2 = r3["run"]["id"]
    st, _ = call("POST", f"/automate/script-runs/{rid2}/cancel/", admin, {"reason": "改期"}, expect=200)
    st, r4 = call("GET", f"/automate/script-runs/{rid2}/", admin)
    ok(r4.get("status") == "cancelled", f"取消成功 (got {r4.get('status')})")
    st, _ = call("POST", f"/automate/script-runs/{rid2}/start/", admin, {})
    ok(st == 400, f"已取消任务不可启动 -> 400 (got {st})")

    # 删除有执行记录的脚本 -> 400
    st, _ = call("DELETE", f"/automate/scripts/{low['id']}/", admin)
    ok(st == 400, f"有执行记录的脚本禁止删除 -> 400 (got {st})")

    # ---------- C. 高危审批闭环 ----------
    print("[C] 高危审批闭环")
    mgr_id = call("GET", "/system/users/?search=mgr_approver", admin)[1]["results"][0]["id"]
    st, r = call("POST", "/automate/script-runs/", admin,
                 {"script_id": high["id"], "scope": {"device_ids": [d3]},
                  "approver_id": mgr_id, "reason": "应急重启端口"}, expect=201)
    ok(r.get("need_approval") is True and r["run"]["status"] == "approving",
       f"高危创建需审批 approving (got {r['run']['status']})")
    ap_id = r["approval_id"]
    st, _ = call("POST", f"/automate/script-runs/{r['run']['id']}/start/", admin, {})
    ok(st == 400, f"审批前不可启动 -> 400 (got {st})")

    st, al = call("GET", "/automate/approvals/?status=pending", mgr)
    mine = [a for a in al.get("results", []) if a["id"] == ap_id]
    ok(len(mine) == 1 and mine[0]["applicant_name"] == "admin" and mine[0]["run_status"] == "approving",
       f"审批人视角可见待办 (got {mine[0]['biz_title'] if mine else None})")

    # ops(非审批人、非超管) 不能处理 -> 数据级不可见 404
    st, _ = call("POST", f"/automate/approvals/{ap_id}/approve/", ops, {"comment": "越权"})
    ok(st == 404, f"非审批人处理 -> 404 (got {st})")

    st, _ = call("POST", f"/automate/approvals/{ap_id}/approve/", mgr, {"comment": "同意执行"})
    st, r2 = call("GET", f"/automate/script-runs/{r['run']['id']}/", admin)
    ok(r2.get("status") == "pending", f"审批通过后转 pending (got {r2.get('status')})")
    st, _ = call("POST", f"/automate/script-runs/{r['run']['id']}/start/", admin, {})
    st, r3 = call("GET", f"/automate/script-runs/{r['run']['id']}/", admin)
    ok(r3.get("status") == "success", f"审批后执行成功 (got {r3.get('status')})")

    # 驳回路径
    st, r4 = call("POST", "/automate/script-runs/", admin,
                  {"script_id": high["id"], "scope": {"device_ids": [d1]},
                   "approver_id": mgr_id}, expect=201)
    st, _ = call("POST", f"/automate/approvals/{r4['approval_id']}/reject/", mgr,
                 {"comment": "窗口冲突"})
    st, r5 = call("GET", f"/automate/script-runs/{r4['run']['id']}/", admin)
    ok(r5.get("status") == "cancelled" and "驳回" in r5.get("summary", ""),
       f"驳回后任务取消且留痕 (got {r5.get('status')}: {r5.get('summary')})")

    # ---------- D. 灰度批次 ----------
    print("[D] 灰度批次")
    st, r = call("POST", "/automate/script-runs/", admin,
                 {"script_id": low["id"], "scope": {"device_ids": ids[:3], "gray_first": True}},
                 expect=201)
    gr = r["run"]
    ok(gr.get("gray_remaining") == 3, f"灰度单剩余 3 (got {gr.get('gray_remaining')})")
    st, res = call("POST", f"/automate/script-runs/{gr['id']}/start/", admin, {})
    ok(res.get("dispatched") == 1 and res.get("gray_remaining") == 2,
       f"首台执行后剩 2 (got {res})")
    st, r2 = call("GET", f"/automate/script-runs/{gr['id']}/", admin)
    ok(r2.get("status") == "running" and r2.get("stats", {}).get("done") == 1,
       f"灰度中 running done=1 (got {r2.get('status')} {r2.get('stats')})")
    st, res2 = call("POST", f"/automate/script-runs/{gr['id']}/continue/", admin, {})
    ok(res2.get("dispatched") == 2 and res2.get("gray_remaining") == 0, "剩余两台继续下发")
    st, r3 = call("GET", f"/automate/script-runs/{gr['id']}/", admin)
    ok(r3.get("status") == "success" and r3.get("stats", {}).get("success") == 3,
       f"灰度全部完成 success 3/3 (got {r3.get('status')} {r3.get('stats')})")

    # 审批人对高危灰度也可先审后跑（组合路径：D 已覆盖灰度，此处不重复）
    print(f"\n结果: {_passed} PASS / {_failed} FAIL")


if __name__ == "__main__":
    main()
    sys.exit(1 if _failed else 0)
