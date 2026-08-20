"""独立 Syslog 接收器（UDP 514）。

容器内独立进程运行：docker compose app 组的 syslog 服务。
解析 RFC3164/RFC5424 风格报文 -> LogRecord 批量入库；来源 IP/主机名映射设备。"""
import os
import re
import socket
import sys
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_SECRET_KEY", "dev-insecure-key")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django  # noqa: E402

django.setup()

from apps.monitor.models import LogRecord  # noqa: E402

FACILITY_NAMES = ["kernel", "user", "mail", "daemon", "auth", "syslog", "lpr", "news",
                  "uucp", "cron", "authpriv", "ftp", "ntp", "audit", "alert", "clock",
                  "local0", "local1", "local2", "local3", "local4", "local5", "local6", "local7"]

LINE_RE = re.compile(r"^<?(\d{1,3})>?\s*(?:(\d{4}-\d\d-\d\dT[\d:.]+Z)|"
                     r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d?\d\s+\d\d:\d\d:\d\d)?\s*"
                     r"([-\w.]+)?\s*(.*)$")

_device_cache = {}
_cache_ts = 0.0


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
            _device_cache[peer_ip] = _device_cache.get(peer_ip)  # peer 也缓存（None 亦缓存防穿透）
        _cache_ts = time.time()
    host = (host_field or "").strip().lower()
    if host and host in _device_cache and _device_cache[host]:
        return _device_cache[host]
    return _device_cache.get(peer_ip)


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
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 514))
    sock.settimeout(2.0)
    print("syslog receiver listening on udp/514", flush=True)
    buf = []
    last_flush = time.time()
    while True:
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            data = None
        if data:
            rec = parse(data, addr[0])
            if rec:
                from django.utils import timezone
                buf.append(LogRecord(device_id=rec["device_id"], source=rec["source"],
                                     severity=rec["severity"], facility=rec["facility"],
                                     occurred_at=timezone.now(),
                                     message="[%s] %s" % (rec["peer"], rec["message"])))
        if buf and (data is None or len(buf) >= 200 or time.time() - last_flush > 2):
            try:
                LogRecord.objects.bulk_create(buf, ignore_conflicts=True)
            except Exception as e:
                print("flush error:", e, flush=True)
            buf.clear()
            last_flush = time.time()


if __name__ == "__main__":
    main()
