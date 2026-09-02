"""Celery 应用与调度：独立队列 + 硬超时 + 自动恢复/升级/自监控/日志清理。"""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from celery import Celery  # noqa: E402
from celery.schedules import crontab  # noqa: E402

app = Celery("nops")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# 本地开发/CI：NOPS_EAGER=1 时任务同步内联执行，无需 broker/worker
if os.environ.get("NOPS_EAGER") == "1":
    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = False

# ---- 队列：ssh 长任务独立，防 SSH 黑洞卡死全部 worker ----
app.conf.task_routes = {
    "ncm.*": {"queue": "ssh"},
    "automate.*": {"queue": "ssh"},
    "monitor.collect_*": {"queue": "nops"},
    "alert.*": {"queue": "nops"},
    "inspect.*": {"queue": "nops"},
    "change.*": {"queue": "nops"},
}

# ---- 超时与可靠性 ----
app.conf.task_soft_time_limit = 120
app.conf.task_time_limit = 180
app.conf.task_acks_late = True
app.conf.worker_prefetch_multiplier = 1
app.conf.task_default_retry_delay = 10
app.conf.task_max_retries = 3

app.conf.beat_schedule = {
    "monitor-collect-all": {"task": "monitor.collect_all", "schedule": 300.0},
    "alert-evaluate-rules": {"task": "alert.evaluate_rules", "schedule": 60.0},
    "ncm-backup-all": {"task": "ncm.backup_all", "schedule": crontab(hour=2, minute=30)},
    # 告警闭环：自动恢复 + 升级检查
    "alert-auto-resolve": {"task": "alert.auto_resolve", "schedule": 120.0},
    "alert-check-escalation": {"task": "alert.check_escalation", "schedule": 120.0},
    # 根因抑制同步（拓扑邻接 × 告警级别 → suppressed_by_id 标记/清除）
    "alert-root-suppression": {"task": "alert.sync_root_suppression", "schedule": 120.0},
    # 平台自监控 + 日志清理
    "platform-self-check": {"task": "monitor.self_check", "schedule": 300.0},
    "log-cleanup": {"task": "monitor.log_cleanup", "schedule": crontab(hour=4, minute=0)},
    # 事件单 SLA 超时检查
    "change-sla-check": {"task": "change.check_sla", "schedule": 600.0},
    # 报表中心：每日订阅快照生成 + 推送
    "report-daily-snapshot": {"task": "report.daily_snapshot", "schedule": crontab(hour=6, minute=45)},
    # CMDB 技术快照保留（按 设备×品类 只留最近 N 条）
    "cmdb-techsnapshot-retention": {"task": "cmdb.cleanup_techsnapshots",
                                    "schedule": crontab(hour=4, minute=30)},
    # 链路质量取样（5 分钟一次 → LinkQualitySample）
    "cmdb-link-quality-sample": {"task": "cmdb.sample_link_quality", "schedule": 300.0},
    # vCenter 虚机同步（每小时 25 分；真实拉取模板未校准源自动跳过记录）
    "cmdb-vcenter-sync": {"task": "cmdb.sync_vcenter", "schedule": crontab(minute=25)},
    # PDU/UPS 电源实测（5 分钟一次 → dcim_powersample；无 Prometheus 环境跳过）
    "dcim-power-poll": {"task": "dcim.poll_power", "schedule": 300.0},
    # SNMP 采集（10 分钟一次 → 接口状态/错误；无线 9800 适配待校准）
    "cmdb-snmp-collect": {"task": "cmdb.snmp_collect", "schedule": 600.0},
    # Prometheus 只读消费（5 分钟一次 → 写 DeviceInterfaceStat；NOPS_PROM_URL 缺省跳过）
    "cmdb-prom-poll": {"task": "cmdb.prom_poll", "schedule": 300.0},
    # LLDP 拓扑自动发现（10 分钟一次 → topo_lldpneighbor；无 snmp_v2c 凭据设备则跳过）
    "topo-lldp-discover": {"task": "topo.lldp_discover", "schedule": 600.0},
    # 安全基线每日核查（最新备份 × 规则 → 结果+不合规告警）
    "ncm-baseline-check": {"task": "ncm.baseline_check", "schedule": crontab(hour=6, minute=30)},
}
