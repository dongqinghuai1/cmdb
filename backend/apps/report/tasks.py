"""apps.report 周期任务：每日报表快照 + 推送。"""
from celery import shared_task

from apps.report.services import daily_snapshot_task


@shared_task(name="report.daily_snapshot")
def daily_snapshot():
    """每日生成全部启用订阅的报表快照（services 内 best-effort，单订阅失败不中断）。"""
    return daily_snapshot_task()
