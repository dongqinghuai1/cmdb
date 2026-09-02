"""topo 周期任务：LLDP 拓扑自动发现。"""
from celery import shared_task


@shared_task(name="topo.lldp_discover")
def lldp_discover_task():
    """LLDP 自动发现（beat 每 10 分钟）：遍历绑 snmp_v2c 凭据设备 → 只读走查
    LLDP-MIB → topo_lldpneighbor（拓扑边/线缆比对数据源）。无凭据设备则跳过。"""
    from apps.topo.services import discover_lldp
    return discover_lldp(mock=False)
