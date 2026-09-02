"""apps.dcim 周期任务：PDU/UPS 电源实测轮询。"""
from celery import shared_task


@shared_task(name="dcim.poll_power")
def poll_power_task():
    """电源轮询（beat 每 5 分钟）：Prometheus 主通道 → 写 dcim_powersample；
    无 Prometheus 环境跳过（SNMP 直采模板待校准，保持与 prom_poll 一致的降级语义）。"""
    from apps.dcim import power as power_svc
    res = {"prom": power_svc.poll_prom()}
    return res
