"""飞书 SSO / 组织同步服务（apps.system）。

分层：
- login_url(app, origin, state)：生成 OAuth 授权跳转（只需公开的 app_id，可离线/真实同用）；
- exchange_identity(app, code, sso_name)：code 换身份 —— mock_mode 走确定性样例（离线全链路）；
  真实分支需 app_secret 就绪且可达 open.feishu.cn，未就绪主动 raise RequiresCalibration；
- provision_or_bind(app, identity)：unionid 定位用户 → 未命中且 auto_provision 则建号绑角色；
- sync_contacts(app)：组织通讯录同步（部门树 + 用户建档，幂等）—— 同 mock/校准分层。
"""
import hashlib
import logging
import urllib.parse

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://open.feishu.cn/connect/oauth/authorize"


class RequiresCalibration(Exception):
    """真实飞书接口模板/凭据未就绪。调用方记录，不静默写假数据。"""


# ============ 公共 ============

def active_app(key=None):
    """取启用的飞书应用：key 为 pk 或 name（供公共端点按 ?app= 指定），否则默认第一启用。"""
    from apps.system.models import FeishuApp
    qs = FeishuApp.objects.filter(enabled=True).order_by("id")
    if key:
        qs = qs.filter(name=str(key)) if not str(key).isdigit() else qs.filter(pk=int(key))
    return qs.first()


def build_login_url(app, origin, state=""):
    params = {"client_id": app.app_id, "redirect_uri": origin.rstrip("/") + "/api/v1/auth/feishu/callback/",
              "response_type": "code", "state": state}
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


# ============ 身份交换 ============

def _mock_identity(app, code, sso_name=""):
    digest = hashlib.md5(f"{app.pk}:{code}".encode()).hexdigest()
    union_id = "ou_" + digest[:16]
    open_id = "on_" + digest[16:32]
    name = (sso_name or f"SSO-{code[:8]}").strip()
    return {"union_id": union_id, "open_id": open_id, "name": name,
            "email": f"{name}@feishu.mock"}


def exchange_identity(app, code, sso_name=""):
    """code → {union_id, open_id, name, email}。"""
    if app.mock_mode:
        return _mock_identity(app, code, sso_name)
    if not (app.app_secret or "").strip():
        raise RequiresCalibration("飞书应用未配置 app_secret：真实 SSO 需先配置密钥")
    # 真实 OAuth：POST /open-apis/authen/v1/oidc/access_token（授权码模式）。
    # 模板依赖 open.feishu.cn 可达性 —— 不可达/凭据错同样抛 RequiresCalibration 供调用方记录。
    try:
        import json
        import urllib.request
        body = json.dumps({"app_id": app.app_id, "app_secret": app.app_secret,
                           "code": code}).encode()
        req = urllib.request.Request("https://open.feishu.cn/open-apis/authen/v1/oidc/access_token",
                                     data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            payload = json.loads(r.read() or b"{}")
        if payload.get("code") != 0 or not payload.get("data", {}).get("access_token"):
            raise RequiresCalibration(f"飞书 token 交换失败：{payload.get('msg')}")
        tok = payload["data"]["access_token"]
        # 用户信息
        req2 = urllib.request.Request(
            "https://open.feishu.cn/open-apis/authen/v1/user_info",
            headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req2, timeout=8) as r2:
            user = json.loads(r2.read() or b"{}").get("data") or {}
        return {"union_id": user.get("union_id") or "", "open_id": user.get("open_id") or "",
                "name": user.get("name") or user.get("en_name") or "feishu-user",
                "email": user.get("email") or ""}
    except RequiresCalibration:
        raise
    except Exception as e:  # noqa: BLE001 —— 网络/JSON 异常归为未就绪
        raise RequiresCalibration(f"飞书开放接口不可达（真实 SSO 待接入环境验证）：{str(e)[:160]}") from e


def _unique_username(base, union_id):
    from django.contrib.auth.models import User
    base = base or f"feishu_{union_id[:8]}"
    cand, i = base, 2
    while User.objects.filter(username=cand).exists():
        cand = f"{base}-{i}"
        i += 1
    return cand


def provision_or_bind(app, identity):
    """按 unionid 定位用户；未命中按 auto_provision 决定建号或抛 PermissionError。"""
    from django.contrib.auth.models import User
    from apps.system.models import Role, UserProfile
    profile = UserProfile.objects.select_related("user").filter(
        feishu_unionid=identity["union_id"]).first()
    if profile:
        return profile.user, False
    if not app.auto_provision:
        raise PermissionError("未绑定飞书账号且应用未开启自动开通，请联系管理员")
    role = Role.objects.filter(pk=app.default_role_id).first()
    username = _unique_username(identity.get("name"), identity["union_id"])
    user = User.objects.create(username=username, first_name=identity.get("name", ""),
                               email=identity.get("email", ""), is_active=True)
    UserProfile.objects.create(user=user, feishu_unionid=identity["union_id"])
    if role:
        user.roles.add(role)
    return user, True


# ============ 组织通讯录同步 ============

def sync_contacts(app, sso_name_prefix=""):
    """部门树 + 通讯录用户同步（幂等：feishu_dept_id / profile.feishu_unionid 匹配）。"""
    from apps.system.models import FeishuApp, OrgDept, UserProfile
    if not app.mock_mode:
        raise RequiresCalibration(
            "真实通讯录同步（contact API）模板未校准：mock_mode 演练可离线验证；"
            "生产建议独立任务按部门分页拉取后调用本模块幂等落库")
    tag = sso_name_prefix or f"sync{app.pk}"
    # 部门：顶层 + 子部门
    top, top_c = OrgDept.objects.get_or_create(
        feishu_dept_id=f"D-{tag}", defaults={"name": f"飞书同步-{tag}", "sort": 0})
    child, child_c = OrgDept.objects.get_or_create(
        feishu_dept_id=f"D-{tag}-c", defaults={"parent": top,
                                               "name": f"研发-{tag}", "sort": 1})
    # 用户（确定性样例 2 名）
    created_u = updated_u = 0
    for i, (en, cn) in enumerate([("fsuser01", "李雷"), ("fsuser02", "韩梅梅")], start=1):
        union_id = f"ou_{hashlib.md5(f'{app.pk}:{tag}:{i}'.encode()).hexdigest()[:12]}"
        prof = UserProfile.objects.filter(feishu_unionid=union_id).first()
        if prof:
            prof.dept = child
            prof.user.first_name = f"{cn}-{tag}"
            prof.user.save(update_fields=["first_name"])
            prof.save(update_fields=["dept"])
            updated_u += 1
            continue
        from django.contrib.auth.models import User
        username = _unique_username(f"fs-{tag}-{i}", union_id)
        user = User.objects.create(username=username, first_name=f"{cn}-{tag}",
                                   is_active=True)
        UserProfile.objects.create(user=user, feishu_unionid=union_id, dept=child)
        created_u += 1
    from django.utils import timezone
    FeishuApp.objects.filter(pk=app.pk).update(last_sync_at=timezone.now())
    return {"departments_created": int(top_c) + int(child_c),
            "departments_updated": 2 - (int(top_c) + int(child_c)),
            "users_created": created_u, "users_updated": updated_u,
            "top_dept": top.id, "child_dept": child.id}
