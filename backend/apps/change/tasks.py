"""apps.change tasks -- 事件单周期任务。"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="change.check_sla")
def check_sla():
    """周期检查 SLA：超时未关闭工单写 sla_warning 时间线（每单一次，幂等）。"""
    from apps.change.services import check_sla_now
    return check_sla_now()
