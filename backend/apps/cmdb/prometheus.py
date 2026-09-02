"""Prometheus 接入（apps.cmdb）。

定位：采集层在 Prometheus/snmp_exporter（生产已有），nops 只做**只读消费**——
周期拉 PromQL 结果写回现有 DeviceInterfaceStat（复用 360°/链路质量/Network 展示），
不做重复轮询。SNMP 直采（snmp.py）降级为探针/校准工具（beat 默认关闭）。

配置（部署环境变量）：
  NOPS_PROM_URL       http://prometheus:9090（缺省=任务跳过）
  NOPS_PROM_TOKEN     只读 API token（可选）
  NOPS_PROM_QUERIES   JSON 覆盖查询表（见 DEFAULT_QUERIES 结构），缺省用内置模板
  指标查询约定：value 即"该语义每秒速率/数值"，bps 类请自行 rate(...)*8。
"""
import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# 语义 → DeviceInterfaceStat 字段（安全白名单）
SEMANTIC_FIELDS = {"in_bps": "in_bps", "out_bps": "out_bps"}

# 内置查询模板：device_label 取值 instance(ip) 或 device(名称)，用于关联 CMDB。
# 字段: semantic / promql / device_label / device_field(manage_ip|name)
DEFAULT_QUERIES = [
    {"semantic": "in_bps", "device_label": "instance", "device_field": "manage_ip",
     "promql": 'sum by (instance) (rate(node_network_receive_bytes_total[5m])) * 8'},
    {"semantic": "out_bps", "device_label": "instance", "device_field": "manage_ip",
     "promql": 'sum by (instance) (rate(node_network_transmit_bytes_total[5m])) * 8'},
]


def _http_json(url, token=None, timeout=8):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise ValueError(f"Prometheus HTTP {e.code}: {url}") from e
    except OSError as e:
        raise ValueError(f"Prometheus 不可达 {url}: {e}") from e


def load_queries():
    raw = (os.getenv("NOPS_PROM_QUERIES") or "").strip()
    if not raw:
        return list(DEFAULT_QUERIES)
    try:
        qs = json.loads(raw)
        return qs if isinstance(qs, list) else list(DEFAULT_QUERIES)
    except Exception:  # noqa: BLE001
        logger.exception("NOPS_PROM_QUERIES 解析失败，使用内置模板")
        return list(DEFAULT_QUERIES)


def query_once(base_url, token=None, query=None, timeout=8):
    """执行一次 PromQL /api/v1/query。返回 [(labels, float_value)]。"""
    import urllib.parse
    url = base_url.rstrip("/") + "/api/v1/query?query=" + urllib.parse.quote(query)
    data = _http_json(url, token, timeout)
    if data.get("status") != "success":
        raise ValueError(f"PromQL 查询失败: {data.get('error') or data.get('status')}")
    out = []
    for row in (data.get("data") or {}).get("result") or []:
        val = ((row.get("value") or [None, None])[1])
        try:
            out.append((row.get("metric") or {}, float(val)))
        except (TypeError, ValueError):
            continue
    return out


def _resolve_device_key(labels, cfg, ip_map, name_map):
    """instance 去端口→manage_ip；device→name。返回 device pk 或 None。"""
    src = labels.get(cfg["device_label"])
    if not src:
        return None
    if cfg.get("device_field") == "manage_ip":
        ip = str(src).split(":")[0]
        return ip_map.get(ip)
    return name_map.get(str(src))


def poll_once(base_url, token=None, queries=None):
    """遍历查询 → 关联 CMDB 设备 → 写 DeviceInterfaceStat。返回统计。"""
    from apps.cmdb.models import Device
    qs = queries if queries is not None else load_queries()
    devices = list(Device.objects.filter(deleted_at__isnull=True)
                   .exclude(manage_ip="").exclude(manage_ip__isnull=True)
                   .values("id", "manage_ip", "name"))
    ip_map = {d["manage_ip"].strip(): d["id"] for d in devices}
    name_map = {d["name"].strip(): d["id"] for d in devices}
    stats = {"queries": len(qs), "matched": 0, "unmatched": 0, "applied": []}
    for cfg in qs:
        semantic = cfg.get("semantic")
        field = SEMANTIC_FIELDS.get(semantic)
        if not field:
            continue
        for labels, val in query_once(base_url, token, cfg.get("promql")):
            pid = _resolve_device_key(labels, cfg, ip_map, name_map)
            if not pid:
                stats["unmatched"] += 1
                continue
            _apply_stat(pid, {field: val})
            stats["matched"] += 1
            stats["applied"].append({"device_id": pid,
                                     "semantic": semantic, "value": int(val)})
    return stats


def _apply_stat(device_id, sample):
    """sample: {stat_field: 数值}，仅更新 >=0 的值。"""
    from apps.cmdb.models import DeviceInterfaceStat
    from apps.cmdb.models import DeviceInterface
    iface = DeviceInterface.objects.filter(device_id=device_id).order_by("if_index").first()
    if not iface:
        return False
    stat, _ = DeviceInterfaceStat.objects.get_or_create(interface=iface)
    patch = {k: int(v) for k, v in sample.items()
             if k in SEMANTIC_FIELDS.values() and v is not None and v >= 0}
    if patch:
        DeviceInterfaceStat.objects.filter(pk=stat.pk).update(**patch)
    return True


# ---------- mock（回归/演示：无 Prometheus 环境验证全链路） ----------
MOCK_ROWS = {"in_bps": 1234000, "out_bps": 567000}


def collect_mock(device):
    """mock 拉取写入：直接对单设备写内置样例并返回落库结果。"""
    ok = _apply_stat(device.pk, dict(MOCK_ROWS))
    return {"mock": True, "applied": ok, "samples": MOCK_ROWS,
            "device_id": device.pk, "name": device.name}
