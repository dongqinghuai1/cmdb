"""链路质量采样（服务层，供 celery 周期任务与按需接口共用）。

对 DeviceInterfaceStat（最近一次实时统计）做周期性取样落 LinkQualitySample；
同轮删除超过 keep_days 的旧样本，控制表增长。注意函数内惰性导入模型
（celery autodiscover 阶段 django 未 ready）。
"""
from datetime import timedelta

from django.utils import timezone


def sample_link_quality(keep_days=7):
    from apps.cmdb.models import DeviceInterfaceStat, LinkQualitySample
    now = timezone.now()
    rows = []
    for st in DeviceInterfaceStat.objects.select_related("interface").all():
        iface = st.interface
        rows.append(LinkQualitySample(
            device_id=iface.device_id, interface_id=iface.id, iface_name=iface.name,
            sampled_at=now, in_bps=st.in_bps or 0, out_bps=st.out_bps or 0,
            in_pps=st.in_pps or 0, out_pps=st.out_pps or 0,
            in_errors_rate=st.in_errors_rate or 0, out_errors_rate=st.out_errors_rate or 0,
            optical_tx_dbm=float(st.optical_tx_dbm) if st.optical_tx_dbm is not None else None,
            optical_rx_dbm=float(st.optical_rx_dbm) if st.optical_rx_dbm is not None else None))
    if rows:
        LinkQualitySample.objects.bulk_create(rows, batch_size=500)
    cut = now - timedelta(days=int(keep_days))
    deleted = LinkQualitySample.objects.filter(sampled_at__lt=cut).count()
    if deleted:
        LinkQualitySample.objects.filter(sampled_at__lt=cut).delete()
    return {"sampled": len(rows), "deleted": deleted, "keep_days": int(keep_days)}
