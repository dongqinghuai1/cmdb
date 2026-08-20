"""Syslog 接收器 v2：令牌桶限流 + 去重采样 + 定期清理。"""
import os
import re
import socket
import sys
import time
from collections import defaultdict
from datetime import timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django  # noqa: E402

django.setup()

from django.utils import timezone  # noqa: E402

FACILITY_NAMES = ["kernel", "user", "mail", "daemon", "auth", "syslog", "lpr", "news",
                  "uucp", "cron", "authpriv", "ftp", "ntp", "audit", "alert", "clock",
                  "local0", "local1", "local2", "local3", "local4", "local5", "local6", "local7"]

LINE_RE = re.compile(r"^<?(\d{1,3})>?\s*(?:(\d{4}-\d\d-\d\dT[\d:.]+Z)|"
                     r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d?\d\s+\d\d:\d\d:\d\d)?\s*"
                     r"([-\w.]+)?\s*(.*)$")

RATE_LIMIT_PER_SEC = 50
BURST = 100
LOG_TTL_HOURS = 72               # 日志保留 72 小时（可按需调整）
_dedup_ttl = 5.0

_device_cache = {}
_cache_ts = 0.0
_rate_buckets = defaultdict(lambda: {"tokens": BURST, "last": time.time()})
_dedup_window = {}


def resolve_device(host_field, peer_ip):
    global _device_cache, _cache_ts
    if time.time() - _cache_ts > 60:
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("SELECT id, COALESCE(hostname,''), COALESCE(manage_ip::text,'') FROM cmdb_device WHERE deleted_at IS NULL")
            _device_cache = {}
            for did, hostname, ip in cur.fetchall():
                if hostname:
                    _device_cache[hostname.lower()] = did
                if ip:
                    _device_cache[ip] = did
        _cache_ts = time.time()
    host = (host_field or "").strip().lower()
    if host and host in _device_cache:
        return _device_cache[host]
    return _device_cache.get(peer_ip)


def check_rate(peer_ip):
    b = _rate_buckets[peer_ip]
    now = time.time()
    elapsed = now - b["last"]
    b["tokens"] = min(b["tokens"] + elapsed * RATE_LIMIT_PER_SEC, BURST)
    b["last"] = now
    if b["tokens"] >= 1:
        b["tokens"] -= 1
        return True
    return False


def check_dedup(peer_ip, msg_key):
    now = time.time()
    key = (peer_ip, msg_key)
    if key in _dedup_window and now - _dedup_window[key] < _dedup_ttl:
        return False
    _dedup_window[key] = now
    if len(_dedup_window) > 5000:
        cutoff = now - _dedup_ttl
        for k in list(_dedup_window.keys()):
            if _dedup_window[k] <= cutoff:
                del _dedup_window[k]
    return True


def parse(data, peer_ip):
    try:
        text = data.decode("utf-8", "replace").strip()
    except Exception:
        return None
    if not text:
        return None
    m = LINE_RE.match(text)
    pri = int(m.group(1)) if m and m.group(1) else 13 * 8 + 6
    facility_idx, severity = pri // 8, pri % 8
    host = m.group(4) if m else ""
    msg = (m.group(5) or text)[:8000]
    return {"device_id": resolve_device(host, peer_ip), "source": "syslog",
            "severity": severity, "facility": FACILITY_NAMES[facility_idx] if facility_idx < 24 else "unknown",
            "message": msg, "peer": peer_ip}


def main():
    from apps.monitor.models import LogRecord
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 514))
    sock.settimeout(2.0)
    print("syslog v2 (rate-limited) udp/514", flush=True)
    buf = []
    last_flush = time.time()
    last_cleanup = time.time()
    dropped = 0

    while True:
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            data = None

        if data:
            if not check_rate(addr[0]):
                dropped += 1
                if dropped % 500 == 1:
                    print(f"rate-limited {addr[0]}: {dropped} dropped", flush=True)
                data = None

        if data:
            rec = parse(data, addr[0])
            if rec and check_dedup(addr[0], rec["message"][:80]):
                buf.append(LogRecord(device_id=rec["device_id"], source=rec["source"],
                                     severity=rec["severity"], facility=rec["facility"],
                                     occurred_at=timezone.now(),
                                     message=f"[{rec['peer']}] {rec['message']}"))

        if buf and (data is None or len(buf) >= 200 or time.time() - last_flush > 2):
            try:
                LogRecord.objects.bulk_create(buf, ignore_conflicts=True)
            except Exception as e:
                print("flush error:", e, flush=True)
            buf.clear()
            last_flush = time.time()

        if time.time() - last_cleanup > 3600:
            try:
                cutoff = timezone.now() - timedelta(hours=LOG_TTL_HOURS)
                n, _ = LogRecord.objects.filter(occurred_at__lt=cutoff).delete()
                if n:
                    print(f"cleanup: {n} old logs", flush=True)
            except Exception as e:
                print("cleanup error:", e, flush=True)
            last_cleanup = time.time()


if __name__ == "__main__":
    main()
