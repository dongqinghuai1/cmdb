"""AES-256-GCM 加密字段（ER 4.3 / D12）：密文格式 base64(nonce+ct+tag)，密钥仅来自环境。"""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.db import models


class Crypto:
    def __init__(self, key: str | None = None):
        raw = (key or settings.CRYPTO_KEY).encode("utf-8")
        self.aes = AESGCM(raw.ljust(32, b"\0")[:32])

    def encrypt(self, plaintext: str) -> str:
        if plaintext is None:
            return ""
        nonce = os.urandom(12)
        ct = self.aes.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        raw = base64.b64decode(ciphertext)
        return self.aes.decrypt(raw[:12], raw[12:], None).decode("utf-8")


_crypto: Crypto | None = None


def get_crypto() -> Crypto:
    global _crypto
    if _crypto is None:
        _crypto = Crypto()
    return _crypto


class EncryptedTextField(models.TextField):
    """存密文；注意：只支持等值过滤的场景在应用层做（密文不可 LIKE）。"""

    description = "AES-256-GCM encrypted text"

    def get_prep_value(self, value):
        if value is None or value == "":
            return value
        return get_crypto().encrypt(str(value))

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        try:
            return get_crypto().decrypt(value)
        except Exception:
            return value  # 密钥更换等场景降级返回原文，避免整表崩溃
