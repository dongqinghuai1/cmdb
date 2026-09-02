"""apps.automate tasks -- 逐台 SSH 执行与灰度批次调度。

- 路由到 ssh 队列（config/celery.py task_routes: automate.* -> ssh），避免阻塞 nops 常规任务。
- 单设备失败不中断批次；每批结束 finalize_run 汇总一次。
- 系统开关 automate.mock_execute.enabled=true 时走模拟执行（演示/CI 无真实设备场景）。
"""
import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

OUTPUT_MAX = 60_000  # 回显入库上限（防单台回显撑爆 PG）

# 与 ncm.services.DRIVER_MAP 同源；未知网络驱动默认 cisco_ios（对齐 NCM fetch 行为）
DRIVER_MAP = {
    "h3c_comware": "hp_comware",
    "cisco_asa": "cisco_asa",
    "cisco_wlc_3504": "cisco_wlc",
    "cisco_wlc_9800": "cisco_wlc",
    "fortigate": "fortinet",
}


def _credential(cred_id):
    from apps.system.models import Credential
    return Credential.objects.filter(pk=cred_id).first()


def _execute_via_ssh(device, script_type, content):
    """真实 SSH 执行。返回 (output, error)；任一异常 -> error。"""
    if not device.get("manage_ip") or not device.get("credential_id"):
        return None, "设备无管理 IP/凭据（可先在系统管理配置凭据）"
    from netmiko import ConnectHandler
    cred = _credential(device["credential_id"])
    if not cred:
        return None, "凭据不存在"
    if script_type in ("python", "shell"):
        device_type = DRIVER_MAP.get(device.get("driver_type") or "", "linux")
    else:  # cli_command
        device_type = DRIVER_MAP.get(device.get("driver_type") or "", "cisco_ios")
    conn = {
        "device_type": device_type,
        "host": str(device["manage_ip"]),
        "username": cred.username or "admin",
        "password": cred.secret,
        "timeout": 15, "banner_timeout": 15, "read_timeout": 45, "fast_cli": False,
    }
    try:
        if script_type == "python":
            cmd = f"python3 - <<'NOPS_EOF'\n{content}\nNOPS_EOF"
        elif script_type == "shell":
            cmd = content
        else:
            cmd = content
        with ConnectHandler(**conn) as net:
            out = net.send_command(cmd, read_timeout=45)
        return (out or "").strip(), None
    except Exception as e:  # noqa: BLE001
        logger.warning("automate ssh failed dev=%s type=%s err=%s", device["id"], script_type, e)
        return None, f"SSH 执行失败: {e}"[:500]


def _mock_execute(device, script_type, content):
    """模拟执行：回显设备与内容预览，便于演示/回归（无真实设备时）。"""
    lines = []
    lines.append(f"[mock] device={device['name']} ip={device.get('manage_ip')} type={script_type}")
    lines.append(f"[mock] >>> {content[:300]}")
    return "\n".join(lines), None


def _run_one(run, detail, mock: bool):
    from apps.automate.services import fetch_device_row
    device = fetch_device_row(detail.device_id)
    if not device:
        detail.status = "failed"
        detail.error = "设备不存在或已删除"
        detail.save(update_fields=["status", "error"])
        return
    content = run.content_snapshot or ""
    detail.status = "running"
    detail.executed_at = timezone.now()
    detail.save(update_fields=["status", "executed_at"])
    try:
        if mock:
            output, err = _mock_execute(device, run.script_type_snapshot, content)
        else:
            output, err = _execute_via_ssh(device, run.script_type_snapshot, content)
        if err:
            detail.status, detail.error = "failed", err
        else:
            detail.status = "success"
            detail.output = (output or "")[:OUTPUT_MAX]
    except Exception as e:  # noqa: BLE001
        detail.status, detail.error = "failed", str(e)[:500]
    detail.save(update_fields=["status", "output", "error"])


@shared_task(name="automate.execute_run", acks_late=False)
def execute_run(run_id, device_ids):
    """按批执行：device_ids 为本次下发的设备子集（灰度时逐批调用）。"""
    from apps.automate.models import ScriptRun, ScriptRunDetail
    from apps.automate.services import finalize_run, mock_execute_enabled

    run = ScriptRun.objects.filter(pk=run_id).first()
    if not run or run.status != ScriptRun.Status.RUNNING:
        return {"run": run_id, "skipped": True}
    mock = mock_execute_enabled()
    executed = skipped = 0
    for dev_id in device_ids:
        if run.status == ScriptRun.Status.CANCELLED:  # 中途被取消则停止下发剩余
            break
        detail = ScriptRunDetail.objects.filter(run=run, device_id=dev_id).first()
        if not detail or detail.status in ("success", "failed"):
            skipped += 1
            continue
        _run_one(run, detail, mock)
        executed += 1
    res = finalize_run(run_id)
    return {"run": run_id, "executed": executed, "skipped": skipped, **res}
