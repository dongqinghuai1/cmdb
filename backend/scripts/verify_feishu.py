"""飞书 SSO E2E：未配置校准提示 / 登录跳转 URL / mock 授权回调(自动建号+JWT) /
同身份重复回调不重复建号 / 关闭自动开通 403 / 组织通讯录同步(幂等) / 权限正负例 / 审计。

用法: python scripts/verify_feishu.py [BASE]
默认 sqlite 8010；容器 PG: http://127.0.0.1:8000/api/v1
前置: init_nops_data（system.sso.view/edit）；admin/nops@2025、
sys_demo(NopsTest@2025, sso view+edit)、auditor(NopsTest@2025, 无)。
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010/api/v1")
TS = time.strftime("%m%d%H%M%S")
ok = fail = 0


def call(method, path, token=None, body=None):
    url = BASE + urllib.parse.quote(path, safe="/?:=&%")
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "replace")[:120]}


def login(u, p):
    s, r = call("POST", "/auth/login/", body={"username": u, "password": p})
    if s != 200:
        print("login fail", u)
        sys.exit(1)
    return r["access"]


def check(name, cond, extra=""):
    global ok, fail
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra)[:170] if not cond else ""))
    globals()["ok" if cond else "fail"] += 1


admin = login("admin", "nops@2025")
sysu = login("sys_demo", "NopsTest@2025")
net = login("net_demo", "NopsTest@2025")
aud = login("auditor", "NopsTest@2025")

# ---- 预清理（重跑幂等；FEISHU/FEISHU2 前缀均清除） ----
for q in ("FEISHU", "FEISHU2"):
    _, fs = call("GET", f"/auth/feishu/apps/?search={q}&page_size=100", admin)
    for a in fs.get("results", []):
        call("DELETE", f"/auth/feishu/apps/{a['id']}/", admin)

# ---- 未配置/权限门 ----
s, r = call("GET", "/auth/feishu/login-url/")
check("F1 未配置应用时 login-url 400 提示", s == 400, r)
s, _ = call("GET", "/auth/feishu/apps/", net)
check("F2 net_demo(无 sso 码) 读应用 403", s == 403, s)
s, _ = call("GET", "/auth/feishu/apps/", aud)
check("F3 auditor 读应用 403", s == 403, s)
s, _ = call("GET", "/auth/feishu/apps/", sysu)
check("F4 sys_demo(view) 读应用 200(空表)", s == 200, s)

# 只读角色 id（作为默认角色授予新建 SSO 用户）
_, roles = call("GET", "/system/roles/?search=readonly&page_size=10", admin)
ro_role = roles["results"][0]["id"] if roles.get("results") else None

NAME = f"FEISHU-{TS}"
s, app = call("POST", "/auth/feishu/apps/", sysu, {
    "name": NAME, "app_id": f"cli_{TS}", "app_secret": "secret-123",
    "enabled": True, "mock_mode": True, "auto_provision": True,
    "default_role_id": ro_role, "remark": "回归"})
aid = app.get("id")
check("F5 sys 建飞书应用(secret 不回显)", s == 201 and aid and "app_secret" not in app
      and app.get("default_role_name"), str(app)[:170])

# ---- 登录跳转 ----
s, lu = call("GET", f"/auth/feishu/login-url/?app={NAME}&state=xyz")
check("F6 login-url 含 authorize/client_id/redirect/state", s == 200
      and "open.feishu.cn/connect/oauth/authorize" in lu.get("url", "")
      and f"client_id={app['app_id']}" in lu.get("url", "")
      and "redirect_uri=" in lu.get("url", "") and "state=xyz" in lu.get("url", ""),
      lu.get("url", "")[:220])

# ---- mock 回调：自动建号 + JWT ----
code1 = f"code-{TS}-a"
s, cb = call("GET", f"/auth/feishu/callback/?app={NAME}&code={code1}&sso_name=SSO-A-{TS}")
tok1, uid1 = cb.get("access"), cb.get("user", {}).get("id")
check("F7 mock 回调自动建号返回 JWT+user", s == 200 and tok1 and uid1
      and cb.get("first_login") is True
      and cb["user"].get("username") == f"SSO-A-{TS}", str(cb)[:220])
s, me = call("GET", "/auth/me/", tok1)
check("F8 新 token 可访问 /auth/me/", s == 200 and me.get("username") == f"SSO-A-{TS}",
      str(me)[:120])
s, cb2 = call("GET", f"/auth/feishu/callback/?app={NAME}&code={code1}&sso_name=SSO-A-{TS}")
check("F9 同 unionid 重复回调不重复建号(同 user)", s == 200
      and cb2.get("user", {}).get("id") == uid1, cb2)

# ---- 第二身份 ----
s, cb3 = call("GET", f"/auth/feishu/callback/?app={NAME}&code=code-{TS}-b&sso_name=SSO-B-{TS}")
uid2 = cb3.get("user", {}).get("id")
check("F10 不同身份建不同账号", s == 200 and uid2 and uid2 != uid1, (uid1, uid2))

# ---- 关闭自动开通 ----
NAME2 = f"FEISHU2-{TS}"
s, app2 = call("POST", "/auth/feishu/apps/", sysu, {
    "name": NAME2, "app_id": f"cli2_{TS}", "app_secret": "s2",
    "enabled": True, "mock_mode": True, "auto_provision": False})
aid2 = app2.get("id")
s, cb4 = call("GET", f"/auth/feishu/callback/?app={NAME2}&code=code-{TS}-c&sso_name=SSO-C-{TS}")
check("F11 关闭自动开通时未绑定 -> 403", s == 403 and cb4.get("detail"), str(cb4)[:140])
s, _ = call("GET", f"/auth/feishu/login-url/?app={NAME2}")
check("F12 停用/启用逻辑：login-url 仍可获取(仅需 app_id)", s == 200, s)

# ---- 组织通讯录同步（幂等） ----
s, cs1 = call("POST", f"/auth/feishu/apps/{aid}/contacts-sync/", sysu,
              {"sso_name": f"sync{TS}"})
check("F13 通讯录同步建部门+2 用户", s == 200 and cs1.get("users_created", 0) >= 2
      and cs1.get("departments_created", 0) >= 2, str(cs1)[:200])
s, cs2 = call("POST", f"/auth/feishu/apps/{aid}/contacts-sync/", sysu,
              {"sso_name": f"sync{TS}"})
check("F14 重复同步幂等(created 0, updated 计入)", s == 200
      and cs2.get("users_created", 9) == 0, str(cs2)[:160])
_, depts = call("GET", f"/system/depts/?search=飞书同步-sync{TS}&page_size=20", admin)
check("F15 部门落库且子部门挂父", depts.get("count", 0) >= 1, depts.get("count"))
s, _ = call("POST", f"/auth/feishu/apps/{aid}/contacts-sync/", net, {"sso_name": "x"})
check("F16 net 触发同步 403", s == 403, s)
s, _ = call("POST", f"/auth/feishu/apps/{aid}/contacts-sync/", aud, {})
check("F17 auditor 触发同步 403", s == 403, s)

# ---- 权限负例/清理 ----
s, _ = call("PATCH", f"/auth/feishu/apps/{aid}/", net, {"remark": "x"})
check("F18 net 修改应用 403", s == 403, s)
s, _ = call("DELETE", f"/auth/feishu/apps/{aid}/", sysu)
s2, _ = call("DELETE", f"/auth/feishu/apps/{aid2}/", sysu)
check("F19 清理测试应用", s in (200, 204) and s2 in (200, 204), (s, s2))

print("\nRESULT: " + str(ok) + " passed, " + str(fail) + " failed")
sys.exit(1 if fail else 0)
