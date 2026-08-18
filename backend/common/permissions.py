"""权限体系：功能权限（菜单+按钮级 code）+ 数据权限（all/region/site/model/device_group）。
实现方式（ER D8）：RBAC 自建轻量表；数据权限在 queryset 注入。
"""
from django.db.models import Q
from rest_framework.permissions import BasePermission


def user_perm_codes(user) -> set[str]:
    """缓存取用户全部权限 code（user.roles -> permissions.code）。"""
    if getattr(user, "_perm_codes_cache", None) is None:
        from apps.system.models import Role
        codes = set(
            Role.objects.filter(users=user)
            .values_list("permissions__code", flat=True)
        )
        if user.is_superuser:
            codes.add("*")
        user._perm_codes_cache = codes
    return user._perm_codes_cache


def has_perm(user, code: str) -> bool:
    codes = user_perm_codes(user)
    return "*" in codes or code in codes


def scoped_queryset(user, model_cls, queryset=None):
    """数据权限行级过滤（PRD 5.2.2）。scope 命中任一维度即可见（OR 语义）。
    无任何 scope 记录的角色视为全量（管理员兜底），有 scope 记录则严格过滤。
    """
    from apps.system.models import RoleDataScope
    qs = queryset if queryset is not None else model_cls.objects.all()
    if user.is_superuser:
        return qs
    scopes = RoleDataScope.objects.filter(role__users=user)
    if not scopes.exists():
        return qs
    filters = Q()
    for sc in scopes:
        ref = sc.scope_ref_id
        if sc.scope_type == RoleDataScope.ScopeType.ALL:
            return qs
        if model_cls.__name__ == "Device":
            if sc.scope_type == "region":
                filters |= Q(region_id=ref)
            elif sc.scope_type == "site":
                filters |= Q(site_id=ref)
            elif sc.scope_type == "model":
                filters |= Q(model_id=ref)
            elif sc.scope_type == "device_group":
                filters |= Q(group_members__group_id=ref)
        elif sc.scope_type == "region" and hasattr(model_cls, "region_id"):
            filters |= Q(region_id=ref)
    return qs.filter(filters).distinct() if filters else qs.none()


class RbacPermission(BasePermission):
    """DRF 权限类：视图需声明 required_perm = 'cmdb.device.view'。"""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False  # 未认证 -> 401（DRF JWT 认证器生成）
        code = getattr(view, "required_perm", None)
        if not code:  # 未声明则仅要求登录
            return True
        return has_perm(request.user, code)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
