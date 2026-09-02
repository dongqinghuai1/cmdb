"""设备附件存储：本地卷（api 容器挂载 nops-media），MinIO 迁移预留。

- 存相对文件名（uuid），下载/删除一律按附件行 id 走本模块，杜绝路径穿越；
- 容器 compose 给 api 挂载命名卷 nops-media:/app/media，重建不丢；
- 后续接 MinIO 时替换 save_blob/read_blob 内部实现即可（file_url 语义不变）。
"""
import mimetypes
import os
import uuid


def _media_dir() -> str:
    from django.conf import settings
    base = getattr(settings, "ATTACH_DIR", None) or os.path.join(settings.BASE_DIR, "media")
    os.makedirs(base, exist_ok=True)
    return base


def _safe_path(name: str) -> str:
    base = os.path.realpath(_media_dir())
    full = os.path.realpath(os.path.join(base, os.path.basename(name)))
    if os.path.commonpath([base, full]) != base:
        raise ValueError("invalid file path")
    return full


def save_blob(data: bytes, filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()[:10]
    name = uuid.uuid4().hex + ext
    with open(_safe_path(name), "wb") as f:
        f.write(data)
    return name


def read_blob(name: str) -> bytes:
    with open(_safe_path(name), "rb") as f:
        return f.read()


def remove_blob(name: str) -> None:
    try:
        os.remove(_safe_path(name))
    except FileNotFoundError:
        pass


def content_type_for(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"
