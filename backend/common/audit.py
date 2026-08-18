"""通用分页 / 异常处理 / 审计写入。"""
import logging

from django.core.exceptions import PermissionDenied
from django.db import models
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler

from common.pagination import StandardPagination  # noqa: F401  (被 settings 引用)

log = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    if isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied(detail=str(exc))
    response = exception_handler(exc, context)
    if response is not None:
        response.data = {"code": response.status_code, "detail": response.data.get("detail", "")}
    return response


def _map_action(action: str) -> str:
    a = action.lower()
    from apps.system.models import AuditLog
    for c in AuditLog.ActionChoices.values:
        if c in a:
            return c
    return AuditLog.ActionChoices.EXECUTE


def write_audit(user, action: str, resource_type: str, resource_id,
                before: dict | None = None, after: dict | None = None,
                source_ip: str = ""):
    """审计写入（ER 4.14 audit_log）：敏感字段脱敏后再入参。尽力而为，不阻塞业务。"""
    try:
        from apps.system.models import AuditLog
        AuditLog.objects.create(
            user=user if user and user.is_authenticated else None,
            action=_map_action(action),
            resource_type=resource_type, resource_id=str(resource_id),
            before=_mask(before), after=_mask(after), source_ip=source_ip or None,
        )
    except Exception:
        log.exception("audit write failed")


SENSITIVE_KEYS = {"password", "secret", "community", "token", "key", "mfa_secret"}


def _mask(data):
    if not data:
        return data
    out = {}
    for k, v in data.items():
        v = "****" if any(s in k.lower() for s in SENSITIVE_KEYS) else v
        if hasattr(v, "pk"):  # 模型实例 -> 主键（审计可序列化）
            v = {"pk": v.pk, "str": str(v)[:80]}
        out[k] = v
    return out
