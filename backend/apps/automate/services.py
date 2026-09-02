"""apps.automate services -- 创建/审批/灰度/状态机与设备解析（views 与 tasks 共用）。

纪律：不 import 其它 app 的模型到模块顶层；系统共享表（SystemConfig）仅函数内延迟导入。
"""
import logging
import re

from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_DEVICES_PER_RUN = 500  # 单次执行目标上限（顺序执行，防止任务超时黑洞）
PARAM_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


# ---------- 通用小工具 ----------

def fetch_names(table: str, id_field: str, ids, label_col: str = "name") -> dict:
    """按主键批量取 (id -> 名字)。table: 'auth_user'/'cmdb_device'，均跨 App 裸表读取。"""
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    from django.db import connection
    ph = ",".join(["%s"] * len(ids))  # PG 与 sqlite 均支持（sqlite 由 Django 自动转 '?'）
    with connection.cursor() as cur:
        cur.execute(f"SELECT {id_field}, {label_col} AS name FROM {table} WHERE {id_field} IN ({ph})", ids)
        return {r[0]: r[1] for r in cur.fetchall()}


def fetch_users(ids) -> dict:
    return fetch_names("auth_user", "id", ids, label_col="username")


def fetch_devices_brief(ids) -> dict:
    """返回 {device_id: {name, manage_ip}}。"""
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    from django.db import connection
    ph = ",".join(["%s"] * len(ids))
    with connection.cursor() as cur:
        cur.execute(f"""SELECT id, name, manage_ip FROM cmdb_device
                       WHERE id IN ({ph}) AND deleted_at IS NULL""", ids)
        return {r[0]: {"name": r[1], "manage_ip": r[2]} for r in cur.fetchall()}


def fetch_device_row(device_id: int):
    """cmdb_device 单台连接信息（IP/驱动/凭据/在线态）。"""
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute("""SELECT id, name, manage_ip, driver_type, credential_id, online_status
                       FROM cmdb_device WHERE id=%s AND deleted_at IS NULL""", [device_id])
        row = cur.fetchone()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "manage_ip": row[2], "driver_type": row[3],
            "credential_id": row[4], "online_status": row[5]}


def mock_execute_enabled() -> bool:
    """系统开关 automate.mock_execute=true 时进入模拟执行（演示/CI 无真实设备时用）。"""
    try:
        from apps.system.models import SystemConfig
        row = SystemConfig.objects.filter(key="automate.mock_execute").first()
        return bool(row and row.value and row.value.get("enabled"))
    except Exception:
        return False


def render_content(content: str, params: dict | None) -> str:
    """把内容中 {{key}} 替换为参数值（未传参的占位符原样保留，避免静默丢命令）。"""
    params = params or {}
    if not params:
        return content or ""

    def _sub(m):
        key = m.group(1)
        return str(params[key]) if key in params else m.group(0)
    return PARAM_RE.sub(_sub, content or "")


def resolve_device_ids(scope: dict) -> list[int]:
    """解析执行目标。当前支持显式 device_ids（UI 从设备台账筛选勾选）；其余字段预留。"""
    raw = (scope or {}).get("device_ids") or []
    try:
        ids = [int(x) for x in raw]
    except (TypeError, ValueError):
        raise ValueError("scope.device_ids 必须为设备 ID 列表")
    ids = list(dict.fromkeys(ids))  # 去重保序
    if not ids:
        raise ValueError("至少选择一台目标设备")
    if len(ids) > MAX_DEVICES_PER_RUN:
        raise ValueError(f"单次执行最多 {MAX_DEVICES_PER_RUN} 台设备")
    alive = fetch_devices_brief(ids)
    missing = [i for i in ids if i not in alive]
    if missing:
        raise ValueError(f"设备不存在或已删除: {missing[:10]}")
    return ids


# ---------- 执行流 ----------

def create_run(user, data: dict, source_ip: str = ""):
    """创建执行单。高危脚本 -> approving + 生成审批单；否则 pending。
    返回 (run, need_approval: bool, approval: Approval|None)。"""
    from apps.automate.models import Approval, Script, ScriptRun
    from common.audit import write_audit

    script = Script.objects.filter(pk=int(data.get("script_id")), enabled=True).first()
    if not script:
        raise ValueError("脚本不存在或已停用")
    if script.script_type == Script.ScriptType.ANSIBLE:
        raise ValueError("Ansible 执行器尚未接入，请先使用 CLI/Shell/Python 类型脚本")

    scope = data.get("scope") or {}
    device_ids = resolve_device_ids(scope)
    scope = {**scope, "device_ids": device_ids}
    if scope.get("gray_first") not in (None, True, False):
        raise ValueError("gray_first 必须为布尔值")
    params = data.get("params") or {}
    content = render_content(script.content, params)
    if not content.strip():
        raise ValueError("脚本内容为空")

    approver_id = None
    if script.requires_approval:
        approver_id = int(data.get("approver_id") or 0)
        if approver_id <= 0:
            raise ValueError("高危脚本必须指定审批人")

    run = ScriptRun.objects.create(
        script_id=script.id,
        script_name_snapshot=script.name,
        script_type_snapshot=script.script_type,
        danger_snapshot=script.danger_level,
        content_snapshot=content,
        params=params,
        executed_by_id=user.id,
        scope=scope,
        gray_batch={"enabled": bool(scope.get("gray_first")), "total": len(device_ids),
                    "dispatched": 0},
        status=ScriptRun.Status.APPROVING if script.requires_approval else ScriptRun.Status.PENDING,
        summary=data.get("reason") or "",
    )
    approval = None
    if script.requires_approval:
        approval = Approval.objects.create(
            biz_type=Approval.BizType.SCRIPT_RUN, biz_id=run.id,
            applicant_id=user.id, approver_id=approver_id)
        run.approval_id = approval.id
        run.save(update_fields=["approval_id"])
    write_audit(user, "execute", "ScriptRun", run.id,
                after={"script": script.name, "devices": len(device_ids),
                       "danger": script.danger_level, "need_approval": bool(approval)},
                source_ip=source_ip)
    return run, bool(approval), approval


def _touch_details(run, device_ids) -> None:
    """为 run 预建逐台明细（幂等：已存在的跳过）。"""
    from apps.automate.models import ScriptRunDetail
    existing = set(ScriptRunDetail.objects.filter(run=run, device_id__in=device_ids)
                   .values_list("device_id", flat=True))
    ScriptRunDetail.objects.bulk_create(
        [ScriptRunDetail(run=run, device_id=d) for d in device_ids if d not in existing])


def _can_operate(user, run) -> bool:
    from common.permissions import has_perm
    return user.is_superuser or run.executed_by_id == user.id or has_perm(user, "automate.run.execute")


def start_run(user, run, source_ip: str = "", gray_first: bool | None = None) -> dict:
    """开始执行：pending -> running。灰度单仅下发首批（第 1 台），其余等 continue。"""
    from apps.automate.models import ScriptRun
    from apps.automate.tasks import execute_run
    from common.audit import write_audit

    if not _can_operate(user, run):
        raise PermissionError("仅执行人/管理员可启动该任务")
    if run.status not in (ScriptRun.Status.PENDING, ScriptRun.Status.APPROVING):
        raise ValueError(f"当前状态 {run.status} 不可启动")
    if run.status == ScriptRun.Status.APPROVING:
        raise ValueError("该脚本为高危，需审批通过后方可执行")

    ids = resolve_device_ids(run.scope)  # 再次校验目标仍有效
    run.scope["device_ids"] = ids
    use_gray = run.scope.get("gray_first") if gray_first is None else bool(gray_first)
    run.gray_batch = {"enabled": use_gray, "total": len(ids), "remaining": len(ids)}
    run.status = ScriptRun.Status.RUNNING
    run.started_at = timezone.now()
    run.save(update_fields=["scope", "gray_batch", "status", "started_at", "updated_at"])
    _touch_details(run, ids)

    first = ids[:1] if use_gray else ids
    run.gray_batch["dispatched"] = len(first)
    run.save(update_fields=["gray_batch", "updated_at"])
    execute_run.delay(run.id, first)
    write_audit(user, "execute", "ScriptRun", run.id,
                after={"action": "start", "batch": len(first), "gray": use_gray},
                source_ip=source_ip)
    run.refresh_from_db()  # eager 模式下任务已同步完成，返回真实状态
    gb = run.gray_batch or {}
    return {"status": run.status, "dispatched": len(first),
            "gray_remaining": max(int(gb.get("total", 0)) - int(gb.get("dispatched", 0)), 0)}


def continue_run(user, run, source_ip: str = "") -> dict:
    """灰度确认后执行剩余设备。"""
    from apps.automate.models import ScriptRun, ScriptRunDetail
    from apps.automate.tasks import execute_run
    from common.audit import write_audit

    if not _can_operate(user, run):
        raise PermissionError("仅执行人/管理员可继续该灰度任务")
    if run.status != ScriptRun.Status.RUNNING or not (run.gray_batch or {}).get("enabled"):
        raise ValueError("仅灰度中的任务可继续")
    rest = list(ScriptRunDetail.objects.filter(run=run, status=ScriptRunDetail.Status.PENDING)
                .values_list("device_id", flat=True))
    if not rest:
        raise ValueError("没有待执行的剩余设备")
    run.gray_batch["dispatched"] = run.gray_batch.get("dispatched", 0) + len(rest)
    run.save(update_fields=["gray_batch", "updated_at"])
    execute_run.delay(run.id, rest)
    write_audit(user, "execute", "ScriptRun", run.id,
                after={"action": "continue", "batch": len(rest)}, source_ip=source_ip)
    run.refresh_from_db()
    gb = run.gray_batch or {}
    return {"dispatched": len(rest),
            "gray_remaining": max(int(gb.get("total", 0)) - int(gb.get("dispatched", 0)), 0)}


def cancel_run(user, run, source_ip: str = "", reason: str = "") -> dict:
    """取消：仅 pending/approving 允许（running 中已有回显的灰度批次不强行打断）。"""
    from apps.automate.models import Approval, ScriptRun, ScriptRunDetail
    from common.audit import write_audit

    if not _can_operate(user, run):
        raise PermissionError("仅执行人/管理员可取消该任务")
    if run.status not in (ScriptRun.Status.PENDING, ScriptRun.Status.APPROVING):
        raise ValueError("仅待执行/待审批状态可取消（执行中任务请等待批次完成）")
    if run.approval_id and run.status == ScriptRun.Status.APPROVING:
        ap = Approval.objects.filter(pk=run.approval_id).first()
        if ap and ap.status == Approval.Status.PENDING:
            ap.status = Approval.Status.REJECTED
            ap.comment = f"申请人取消：{reason}".strip() or "申请人取消"
            ap.decided_at = timezone.now()
            ap.save(update_fields=["status", "comment", "decided_at", "updated_at"])
    ScriptRunDetail.objects.filter(run=run).update(status=ScriptRunDetail.Status.FAILED,
                                                   error="任务已取消")
    run.status = ScriptRun.Status.CANCELLED
    run.finished_at = timezone.now()
    run.summary = f"已取消：{reason}".strip() or "已取消"
    run.save(update_fields=["status", "finished_at", "summary", "updated_at"])
    write_audit(user, "execute", "ScriptRun", run.id,
                after={"action": "cancel", "reason": reason}, source_ip=source_ip)
    return {"status": run.status}


def decide_approval(user, approval, approved: bool, comment: str = "", source_ip: str = "") -> dict:
    """审批通过/驳回。通过 -> 关联 run 转 pending（待执行人启动）；驳回 -> run 取消。"""
    from apps.automate.models import Approval, ScriptRun
    from common.audit import write_audit
    from common.permissions import has_perm

    if approval.status != Approval.Status.PENDING:
        raise ValueError("该审批单已处理")
    if not (user.id == approval.approver_id or user.is_superuser or has_perm(user, "automate.approve")):
        raise PermissionError("仅指定审批人可处理")
    approval.status = Approval.Status.APPROVED if approved else Approval.Status.REJECTED
    approval.comment = comment or approval.comment
    approval.decided_at = timezone.now()
    approval.save(update_fields=["status", "comment", "decided_at", "updated_at"])

    run = ScriptRun.objects.filter(pk=approval.biz_id).first()
    if run:
        if approved and run.status == ScriptRun.Status.APPROVING:
            run.status = ScriptRun.Status.PENDING
            run.save(update_fields=["status", "updated_at"])
        elif not approved and run.status == ScriptRun.Status.APPROVING:
            run.status = ScriptRun.Status.CANCELLED
            run.finished_at = timezone.now()
            run.summary = f"审批驳回：{comment}".strip() or "审批驳回"
            run.save(update_fields=["status", "finished_at", "summary", "updated_at"])
    write_audit(user, "approve", "Approval", approval.id,
                after={"decision": approval.status, "comment": comment}, source_ip=source_ip)
    return {"status": approval.status, "run_status": run.status if run else None}


def finalize_run(run_id: int) -> dict:
    """单批执行完成后汇总：无排队/执行中设备 -> 终态（success/failed/partial_success）。"""
    from apps.automate.models import ScriptRun, ScriptRunDetail
    run = ScriptRun.objects.filter(pk=run_id).first()
    if not run or run.status == ScriptRun.Status.CANCELLED:
        return {"status": run.status if run else None}
    counts = {s: ScriptRunDetail.objects.filter(run=run, status=s).count()
              for s in ScriptRunDetail.Status.values}
    active = counts.get("pending", 0) + counts.get("running", 0)
    ok, bad = counts.get("success", 0), counts.get("failed", 0)
    run.summary = f"成功 {ok} / 失败 {bad}"
    if active == 0:
        run.status = (ScriptRun.Status.SUCCESS if bad == 0
                      else ScriptRun.Status.PARTIAL_SUCCESS if ok > 0
                      else ScriptRun.Status.FAILED)
        run.finished_at = timezone.now()
        run.gray_batch["dispatched"] = run.gray_batch.get("total", 0)
    run.save(update_fields=["status", "summary", "finished_at", "gray_batch", "updated_at"])
    return {"status": run.status, "ok": ok, "failed": bad}


# ============ 固件升级（FirmwarePackage / FirmwareUpgradePlan） ============

FW_DRIVER_MAP = {  # 真实预检 netmiko device_type（h3c/cisco/fortigate 常用子集）
    "h3c_comware": "hp_comware",
    "cisco_ios": "cisco_ios",
    "cisco_asa": "cisco_asa",
    "cisco_wlc_3504": "cisco_wlc",
    "cisco_wlc_9800": "cisco_wlc",
    "fortigate": "fortinet",
}


def create_firmware_plan(user, data, source_ip: str = ""):
    """建固件升级计划（单设备）。校验设备存在、包存在、无进行中的同设备计划。"""
    from common.audit import write_audit
    from apps.automate.models import FirmwarePackage, FirmwareUpgradePlan
    dev_id = int(data.get("device_id") or 0)
    pkg_id = int(data.get("package_id") or 0)
    if not dev_id or not pkg_id:
        raise ValueError("device_id / package_id 必填")
    dev = fetch_device_row(dev_id)
    if not dev:
        raise ValueError("设备不存在或已删除")
    pkg = FirmwarePackage.objects.filter(pk=pkg_id).first()
    if not pkg:
        raise ValueError("固件包不存在")
    active = FirmwareUpgradePlan.objects.filter(
        device_id=dev_id,
        status__in=(FirmwareUpgradePlan.Status.PENDING,
                    FirmwareUpgradePlan.Status.READY,
                    FirmwareUpgradePlan.Status.RUNNING)).exists()
    if active:
        raise ValueError("该设备已有进行中的升级计划（待执行/待窗口/执行中），先处理再建")
    plan = FirmwareUpgradePlan.objects.create(
        device_id=dev_id, package_id=pkg_id,
        package_name_snapshot=pkg.name, package_version_snapshot=pkg.version,
        current_version=(data.get("current_version") or "").strip(),
        scheduled_at=data.get("scheduled_at") or None,
        created_by_id=user.id)
    write_audit(user, "create", "FirmwareUpgradePlan", plan.pk,
                after={"device_id": dev_id, "package": pkg.name,
                       "version": pkg.version}, source_ip=source_ip)
    return plan


def execute_firmware_engine(plan_id: int, mock: bool):
    """升级作业引擎（celery worker 或 EAGER 内联执行）：
    - mock=True：全流程演练（预检/版本比对/步骤编排），不触网不刷机；
    - mock=False：真实只读预检(show version)+步骤编排 → ready（**v1 不自动下发刷写**，
      待模板校准/人工窗口后放开 force；防生产误刷）。
    """
    from apps.automate.models import FirmwareUpgradePlan
    plan = FirmwareUpgradePlan.objects.filter(pk=plan_id).first()
    if not plan:
        return {"status": "missing"}
    now = timezone.now()
    if plan.status != FirmwareUpgradePlan.Status.RUNNING:
        plan.status = FirmwareUpgradePlan.Status.RUNNING
    plan.save(update_fields=["status", "updated_at"])
    dev = fetch_device_row(plan.device_id)
    lines = []
    err = ""
    if not dev:
        err = "设备不存在或已删除"
        plan.status = FirmwareUpgradePlan.Status.FAILED
        plan.error, plan.executed_at = err, now
        plan.save(update_fields=["status", "error", "executed_at", "updated_at"])
        return {"id": plan.id, "status": plan.status, "error": err}
    target = plan.package_version_snapshot or "-"
    lines.append(f"[{('mock' if mock else 'precheck')}] device={dev['name']}({dev['manage_ip'] or '-'})"
                 f" driver={dev['driver_type'] or '-'}")
    if mock:
        cur = plan.current_version or "7.1.070, Release R6628"
        lines.append(f"[mock] 当前版本 {cur}，目标版本 {target}")
        if cur == target:
            lines.append("[mock] 已在目标版本，无需升级")
            plan.status = FirmwareUpgradePlan.Status.SUCCESS
        else:
            lines.append("[mock] 步骤编排（演练）：1) 上传镜像 2) 指定启动项 3) 窗口内重启生效")
            lines.append("[mock] 演练完成 → 标记成功（真实刷写不在此态执行）")
            plan.status = FirmwareUpgradePlan.Status.SUCCESS
    else:
        if not dev["manage_ip"] or not dev["credential_id"]:
            err = "设备缺少管理 IP/凭据，无法真实预检（可先 mock=1 演练）"
            plan.status = FirmwareUpgradePlan.Status.FAILED
        else:
            try:
                from apps.system.models import Credential
                import netmiko
                cred = Credential.objects.filter(pk=dev["credential_id"]).first()
                conn = {"device_type": FW_DRIVER_MAP.get(dev["driver_type"], "cisco_ios"),
                        "host": dev["manage_ip"], "username": cred.username or "admin",
                        "password": cred.secret, "timeout": 12}
                show = ("display version" if conn["device_type"] == "hp_comware"
                        else "show version")
                with netmiko.ConnectHandler(**conn) as n:
                    out = n.send_command(show)
                head = next((l for l in out.splitlines() if l.strip()), "")
                lines.append(f"[precheck] {head[:160]}")
                plan.current_version = head[:64]
                if head and target and target in out:
                    lines.append("已在目标版本，无需升级")
                    plan.status = FirmwareUpgradePlan.Status.SUCCESS
                else:
                    lines.append("预检通过，刷写步骤已编排（未自动下发，待窗口人工执行/后续 force 模板校准）")
                    plan.status = FirmwareUpgradePlan.Status.READY
            except Exception as e:
                err = f"预检失败：{e}"
                plan.status = FirmwareUpgradePlan.Status.FAILED
        if err:
            plan.error = err[:1000]
    plan.result_log = "\n".join(lines)
    plan.executed_at = now
    plan.save(update_fields=["status", "result_log", "error", "current_version",
                             "executed_at", "updated_at"])
    return {"id": plan.id, "status": plan.status,
            "log": plan.result_log, "error": plan.error}


def cancel_firmware_plan(user, plan, reason: str = "", source_ip: str = ""):
    """取消计划：仅 pending/ready/failed 可取消（成功态为演练终态，保留历史）。"""
    from common.audit import write_audit
    from apps.automate.models import FirmwareUpgradePlan
    if plan.status not in (FirmwareUpgradePlan.Status.PENDING,
                           FirmwareUpgradePlan.Status.READY,
                           FirmwareUpgradePlan.Status.FAILED):
        raise ValueError(f"当前状态 {plan.status} 不可取消（仅 pending/ready/failed）")
    plan.status = FirmwareUpgradePlan.Status.CANCELLED
    plan.result_log = (plan.result_log or "") + f"\n[cancel] {reason or '手动取消'}"
    plan.save(update_fields=["status", "result_log", "updated_at"])
    write_audit(user, "execute", "FirmwareUpgradePlan", plan.pk,
                after={"status": plan.status, "reason": reason}, source_ip=source_ip)
    return {"id": plan.id, "status": plan.status}
