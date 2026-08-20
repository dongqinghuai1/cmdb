"""monitor tasks: celery autodiscover 入口（实现见 collector.py）。"""
from apps.monitor.collector import (collect_all, collect_batch, collect_one,  # noqa: F401
                                     collect_shard)
