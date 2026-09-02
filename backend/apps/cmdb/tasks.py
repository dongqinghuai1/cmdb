"""cmdb 周期任务：TechSnapshot 按 (设备,品类) 保留最近 N 条。"""
from celery import shared_task

from apps.cmdb.retention import cleanup_techsnapshots


@shared_task(name="cmdb.cleanup_techsnapshots")
def cleanup_techsnapshots_task(keep=5):
    """清理过旧技术快照；每天 04:30 由 beat 触发（keep 可调）。"""
    return cleanup_techsnapshots(keep)
