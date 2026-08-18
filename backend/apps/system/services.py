"""apps.system.services -- 对外服务接口（跨 App 唯一访问通道，7.2.1 边界纪律）。
"""
import logging

import requests

log = logging.getLogger(__name__)


def send_notification(channel, text: str, card: dict | None = None) -> bool:
    """统一通知出口（一期：飞书 webhook + 邮件占位）。"""
    if not channel.enabled:
        return False
    try:
        if channel.channel_type == "feishu":
            payload = {"msg_type": "text", "content": {"text": text}}
            if card:
                payload = {"msg_type": "interactive", "card": card}
            r = requests.post(channel.config.get("webhook_url", ""), json=payload, timeout=10)
            return r.status_code == 200 and r.json().get("code", 0) == 0
        if channel.channel_type == "webhook":
            r = requests.post(channel.url if hasattr(channel, "url") else channel.config.get("url", ""),
                              json={"text": text}, timeout=10)
            return r.status_code == 200
        # email/sms 渠道二期接入
        return False
    except Exception:
        log.exception("notify failed channel=%s", channel.id)
        return False


def resolve_credential(device) -> int | None:
    """凭据解析顺序（ER 4.3 / V1.1 #2）：单台 > 设备组 > 厂商/型号 > 全局默认。"""
    from apps.system.models import Credential
    if getattr(device, "credential_id", None):
        return device.credential_id
    cid = device.attrs.get("_group_cred") if isinstance(device.attrs, dict) else None
    if cid:
        return cid
    cands = Credential.objects.filter(deleted_at__isnull=True)
    for c in sorted(cands, key=lambda x: 0 if x.scope.get("default") else 1):
        scope = c.scope or {}
        vendors = scope.get("vendors") or []
        models = scope.get("models") or []
        if (not vendors and not models) or device.vendor in vendors or device.model.code in models:
            return c.id
    return None
