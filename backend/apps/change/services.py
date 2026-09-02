"""apps.change services -- 事件单生命周期：报障/分派/处理/反馈/关闭 + SLA + 告警联动。

纪律：跨 App 只走裸表 SQL 或对方 services；models 不互相 import。
状态机（status）：new -> assigned -> processing -> feedback -> closed（处理中/待反馈阶段可关闭）。
任意非 closed 状态可 assign（改派）；comment 不限状态。
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

ALLOWED_START = {"new", "assigned"}
CLOSEABLE = {"processing", "feedback"}


# ---------- 基础查询 ----------

def fetch_names(table: str, id_field: str, ids, label_col: str = "name") -> dict:
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    from django.db import connection
    ph = ",".join(["%s"] * len(ids))
    with connection.cursor() as cur:
        cur.execute(f"SELECT {id_field}, {label_col} AS name FROM {table} WHERE {id_field} IN ({ph})", ids)
        return {r[0]: r[1] for r in cur.fetchall()}


def fetch_users(ids) -> dict:
    return fetch_names("auth_user", "id", ids, label_col="username")


def fetch_device_names(ids) -> dict:
    return fetch_names("cmdb_device", "id", ids)


def fetch_alert_events(ids) -> dict:
    """返回 {alert_event_id: {title, severity, device_id}}。"""
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    from django.db import connection
    ph = ",".join(["%s"] * len(ids))
    with connection.cursor() as cur:
        cur.execute(f"SELECT id, title, severity, device_id FROM alert_alertevent WHERE id IN ({ph})", ids)
        return {r[0]: {"title": r[1], "severity": r[2], "device_id": r[3]} for r in cur.fetchall()}


def _gen_ticket_no() -> str:
    from apps.change.models import IncidentTicket
    today = timezone.localdate().strftime("%Y%m%d")
    prefix = f"INC-{today}-"
    last = (IncidentTicket.objects.filter(ticket_no__startswith=prefix)
            .order_by("-ticket_no").values_list("ticket_no", flat=True).first())
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:03d}"


def _add_event(ticket, event_type, actor_id, content: str = "") -> None:
    from apps.change.models import IncidentEvent
    IncidentEvent.objects.create(ticket=ticket, event_type=event_type,
                                 actor_id=actor_id, content=content)


def _sla_deadline(priority) -> object:
    from apps.change.models import IncidentTicket
    hours = IncidentTicket.SLA_HOURS.get(priority, IncidentTicket.SLA_HOURS[IncidentTicket.Priority.MID])
    return timezone.now() + timedelta(hours=hours)


def _audit(user, action, ticket, after=None, source_ip: str = ""):
    from common.audit import write_audit
    write_audit(user, action, "IncidentTicket", ticket.pk,
                after={**(after or {}), "ticket_no": ticket.ticket_no}, source_ip=source_ip)


# ---------- 权限 ----------

def _can(user, ticket, action: str) -> bool:
    """参与者（报障人/处理人）或具备 incident.edit 权限者可操作；管理员兜底。"""
    from common.permissions import has_perm
    if user.is_superuser or has_perm(user, "change.incident.edit"):
        return True
    if action == "comment":
        return user.id in (ticket.reporter_id, ticket.handler_id)
    if action == "assign":
        return user.id == ticket.reporter_id
    if action in ("start", "feedback"):
        return user.id == ticket.handler_id or user.id == ticket.reporter_id
    if action == "close":  # 处理人提交处理结果后，报障人/处理人关闭
        return user.id in (ticket.reporter_id, ticket.handler_id)
    return False


# ---------- 生命周期 ----------

def create_ticket(user, data: dict, source_ip: str = "") -> dict:
    """人工/巡检报障（source 由调用方指定；alert 联动走 create_from_alert）。"""
    from apps.change.models import IncidentTicket, IncidentEvent

    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("工单标题必填")
    priority = data.get("priority") or IncidentTicket.Priority.MID
    if priority not in IncidentTicket.Priority.values:
        raise ValueError("priority 不合法")
    source = data.get("source") or IncidentTicket.Source.MANUAL
    if source not in IncidentTicket.Source.values:
        raise ValueError("source 不合法")
    alert_id = data.get("related_alert_event_id")
    device_id = data.get("device_id")
    if alert_id:
        ev = fetch_alert_events([alert_id]).get(int(alert_id))
        if not ev:
            raise ValueError(f"关联告警不存在: {alert_id}")
        if not device_id:
            device_id = ev["device_id"]
    ticket = IncidentTicket.objects.create(
        ticket_no=_gen_ticket_no(), title=title, source=source,
        reporter_id=user.id, priority=priority,
        related_alert_event_id=alert_id, device_id=device_id or None,
        sla_deadline=_sla_deadline(priority),
        description=(data.get("description") or "").strip(),
    )
    content = []
    if source != IncidentTicket.Source.MANUAL:
        content.append(f"来源：{IncidentTicket(source=source).get_source_display()}")
    if alert_id:
        content.append(f"关联告警 #{alert_id}")
    if content:
        _add_event(ticket, IncidentEvent.EventType.STATUS_CHANGE, user.id, "；".join(content))
    _audit(user, "create", ticket, after={"title": title, "priority": priority}, source_ip=source_ip)
    return {"id": ticket.pk, "ticket_no": ticket.ticket_no, "status": ticket.status,
            "sla_deadline": ticket.sla_deadline.isoformat()}


def assign_ticket(user, ticket, data: dict, source_ip: str = "") -> dict:
    from apps.change.models import IncidentEvent, IncidentTicket
    if not _can(user, ticket, "assign"):
        raise PermissionError("仅报障人或具备事件单处理权限者可分派")
    if ticket.status == IncidentTicket.Status.CLOSED:
        raise ValueError("已关闭工单不可分派")
    handler_id = int(data.get("handler_id") or 0)
    if handler_id <= 0 or handler_id not in fetch_users([handler_id]):
        raise ValueError("请指定有效的处理人")
    old = ticket.get_status_display()
    ticket.handler_id = handler_id
    if ticket.status in (IncidentTicket.Status.NEW,):
        ticket.status = IncidentTicket.Status.ASSIGNED
    ticket.save(update_fields=["handler_id", "status", "updated_at"])
    _add_event(ticket, IncidentEvent.EventType.ASSIGN, user.id,
               f"分派给用户#{handler_id}：{(data.get('comment') or '').strip()}")
    if ticket.status != "assigned":
        _add_event(ticket, IncidentEvent.EventType.STATUS_CHANGE, user.id,
                   f"{old} -> {ticket.get_status_display()}")
    _audit(user, "update", ticket, after={"assign_to": handler_id}, source_ip=source_ip)
    return {"status": ticket.status, "handler_id": handler_id}


def start_ticket(user, ticket, data: dict, source_ip: str = "") -> dict:
    from apps.change.models import IncidentEvent, IncidentTicket
    if not _can(user, ticket, "start"):
        raise PermissionError("仅处理人/报障人可开始处理")
    if ticket.status not in ALLOWED_START:
        raise ValueError(f"当前状态 {ticket.get_status_display()} 不可开始处理")
    old = ticket.get_status_display()
    ticket.status = IncidentTicket.Status.PROCESSING
    if ticket.handler_id is None:
        ticket.handler_id = user.id
    ticket.save(update_fields=["status", "handler_id", "updated_at"])
    note = (data.get("comment") or "").strip()
    _add_event(ticket, IncidentEvent.EventType.STATUS_CHANGE, user.id,
               f"{old} -> {ticket.get_status_display()}" + (f"：{note}" if note else ""))
    _audit(user, "execute", ticket, after={"to": ticket.status}, source_ip=source_ip)
    return {"status": ticket.status}


def feedback_ticket(user, ticket, data: dict, source_ip: str = "") -> dict:
    from apps.change.models import IncidentEvent, IncidentTicket
    if not _can(user, ticket, "feedback"):
        raise PermissionError("仅处理人/报障人可提交处理结果")
    if ticket.status != IncidentTicket.Status.PROCESSING:
        raise ValueError("仅处理中工单可提交处理结果")
    resolution = (data.get("resolution") or "").strip()
    if not resolution:
        raise ValueError("请填写处理结果/解决方案")
    ticket.resolution = resolution
    ticket.status = IncidentTicket.Status.FEEDBACK
    ticket.save(update_fields=["resolution", "status", "updated_at"])
    _add_event(ticket, IncidentEvent.EventType.STATUS_CHANGE, user.id,
               f"提交处理结果 -> {ticket.get_status_display()}：{resolution}")
    _audit(user, "execute", ticket, after={"to": ticket.status}, source_ip=source_ip)
    return {"status": ticket.status}


def close_ticket(user, ticket, data: dict, source_ip: str = "") -> dict:
    from apps.change.models import IncidentEvent, IncidentTicket
    if not _can(user, ticket, "close"):
        raise PermissionError("仅报障人/处理人可关闭工单")
    if ticket.status not in CLOSEABLE:
        raise ValueError("工单需先进入处理中/待反馈阶段才能关闭")
    note = (data.get("comment") or "").strip()
    if not ticket.resolution and not note:
        raise ValueError("关闭前请填写处理结果或关闭说明")
    ticket.status = IncidentTicket.Status.CLOSED
    ticket.closed_at = timezone.now()
    if note and not ticket.resolution:
        ticket.resolution = note
    ticket.save(update_fields=["status", "closed_at", "resolution", "updated_at"])
    _add_event(ticket, IncidentEvent.EventType.STATUS_CHANGE, user.id,
               f"关闭工单" + (f"：{note}" if note else ""))
    _audit(user, "execute", ticket, after={"to": ticket.status}, source_ip=source_ip)
    return {"status": ticket.status}


def comment_ticket(user, ticket, data: dict, source_ip: str = "") -> dict:
    if not _can(user, ticket, "comment"):
        raise PermissionError("仅报障人/处理人可评论")
    content = (data.get("content") or "").strip()
    if not content:
        raise ValueError("评论内容必填")
    _add_event(ticket, "comment", user.id, content)
    _audit(user, "comment", ticket, source_ip=source_ip)
    return {"event": "comment", "content": content}


def create_from_alert(user, alert_id, source_ip: str = "", note: str = "") -> dict:
    """告警联动建单：/alerts/events/{id}/create-incident/ 转发入口。"""
    from apps.change.models import IncidentEvent
    ev = fetch_alert_events([alert_id]).get(int(alert_id))
    if not ev:
        raise ValueError(f"告警不存在: {alert_id}")
    return create_ticket(user, {
        "title": f"[告警] {ev['title']}",
        "source": "alert",
        "related_alert_event_id": alert_id,
        "device_id": ev.get("device_id"),
        "priority": "high" if ev.get("severity") == "critical" else "mid",
        "description": (note or "由告警自动联动创建的事件单"),
    }, source_ip=source_ip)


# ---------- SLA 检查（周期任务） ----------

def check_sla_now() -> dict:
    """超时未关闭且未提醒过的工单 -> 打 sla_warning 时间线事件（幂等，每单一次）。"""
    from apps.change.models import IncidentEvent, IncidentTicket
    overdue = (IncidentTicket.objects
               .exclude(status=IncidentTicket.Status.CLOSED)
               .filter(sla_deadline__lt=timezone.now()))
    warned = {e.ticket_id for e in
              IncidentEvent.objects.filter(event_type=IncidentEvent.EventType.SLA_WARNING)}
    n = 0
    for t in overdue:
        if t.pk in warned:
            continue
        _add_event(t, IncidentEvent.EventType.SLA_WARNING, None,
                   f"SLA 超时提醒：应于 {t.sla_deadline:%m-%d %H:%M} 前处理完毕")
        n += 1
    return {"overdue": overdue.count(), "new_warnings": n}
