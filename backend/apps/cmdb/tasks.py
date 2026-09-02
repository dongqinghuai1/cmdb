"""cmdb 周期任务：TechSnapshot 保留 + 链路质量取样。"""
from celery import shared_task

from apps.cmdb.retention import cleanup_techsnapshots


@shared_task(name="cmdb.cleanup_techsnapshots")
def cleanup_techsnapshots_task(keep=5):
    """清理过旧技术快照；每天 04:30 由 beat 触发（keep 可调）。"""
    return cleanup_techsnapshots(keep)


@shared_task(name="cmdb.sample_link_quality")
def sample_link_quality_task(keep_days=7):
    """链路质量取样（每 5 分钟）：DeviceInterfaceStat → LinkQualitySample + 老样本清理。"""
    from apps.cmdb.linkquality import sample_link_quality
    return sample_link_quality(keep_days)
