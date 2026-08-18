"""DRF 统一异常响应：把字段级校验错误拍平成可读文本（settings.EXCEPTION_HANDLER）。"""
from django.core.exceptions import PermissionDenied
from rest_framework import exceptions
from rest_framework.views import exception_handler


def _flat(value) -> str:
    if isinstance(value, list):
        return "; ".join(_flat(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_flat(v)}" for k, v in value.items())
    return str(value)


def api_exception_handler(exc, context):
    if isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied(detail=str(exc))
    response = exception_handler(exc, context)
    if response is not None:
        data = response.data
        if isinstance(data, dict):
            if "detail" in data and len(data) == 1:
                detail = _flat(data["detail"])
            else:  # 字段级错误 {"code":["该字段必须唯一。"]}
                detail = _flat(data)
        else:
            detail = _flat(data)
        response.data = {"code": response.status_code, "detail": detail}
    return response
