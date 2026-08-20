"""API Token 认证后端（P0 #3：开放接口鉴权）。

用法: Authorization: ApiToken nops_xxxxx
"""
import hashlib
import time

from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication


class ApiTokenAuthentication(BaseAuthentication):
    keyword = "ApiToken"
    # 简易内存限流（进程内）：{token_hash: [(ts,..)]}
    _rate = {}

    def authenticate(self, request):
        auth = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth.startswith(self.keyword + " "):
            return None  # 不是 ApiToken 方案，交给下一个认证器

        plain = auth[len(self.keyword) + 1:].strip()
        if not plain:
            raise exceptions.AuthenticationFailed("API Token 为空")

        from apps.system.models import ApiToken
        token_hash = hashlib.sha256(plain.encode()).hexdigest()
        obj = ApiToken.objects.filter(token_hash=token_hash).first()
        if not obj:
            raise exceptions.AuthenticationFailed("API Token 无效")
        if obj.revoked_at:
            raise exceptions.AuthenticationFailed("API Token 已吊销")
        if obj.expires_at and obj.expires_at < timezone.now():
            raise exceptions.AuthenticationFailed("API Token 已过期")

        # 限流
        now = time.time()
        window = 60
        self._rate.setdefault(token_hash, [])
        self._rate[token_hash] = [ts for ts in self._rate[token_hash] if now - ts < window]
        if len(self._rate[token_hash]) >= obj.rate_limit_per_min:
            raise exceptions.Throttled(detail=f"超过限流 {obj.rate_limit_per_min}/min")
        self._rate[token_hash].append(now)

        # 记录 last_used_at
        ApiToken.objects.filter(pk=obj.pk).update(last_used_at=timezone.now())

        # 关联到 Django user（token 创建者），但标记只读
        user = obj.created_by
        if not user or not user.is_active:
            raise exceptions.AuthenticationFailed("Token 创建者已禁用")
        user._api_token = obj  # 供权限检查用
        return (user, obj)

    def authenticate_header(self, request):
        return self.keyword
