"""apps.ipam 周期任务：ARP 轮询 → IP 台账登记/冲突/interface 回填。"""
from celery import shared_task


@shared_task(name="ipam.arp_poll")
def arp_poll_task():
    """ARP 周期采集（beat 每 10 分钟，与 cmdb.snmp_collect 同节奏）：遍历持 snmp_v2c
    凭据设备走查 ipNetToMediaTable（复用 apps.cmdb.snmp 单采集栈）→ ingest。"""
    from apps.ipam.services import arp_poll
    return arp_poll(mock=False)
