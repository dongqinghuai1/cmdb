"""alert 服务层：跨 app 联动静默（ER D4：占用/维护窗口自动静默）。

占用(借出)自动静默：cmdb usage-claim borrow/return 经本层创建/结束 occupation 静默，
使借出的设备在占用期间不进告警（scope.device_ids 对 evaluate 生效）。
"""
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def occupation_begin(device_id, usage_event_id, user_id, counterparty=""):
    """借出占用 → 建 occupation 静默（幂等：同设备已有未结束占用静默则不重复建）。"""
    from apps.alert.models import AlertSilence
    device_id = int(device_id)
    existing = AlertSilence.objects.filter(
        silence_type="occupation", ended_at__isnull=True).order_by("-id")
    for s in existing:
        if device_id in (s.scope or {}).get("device_ids", []):
            return s.pk  # 已静默（重复借出已被 usage-claim 拦截，兜底幂等）
    reason = "设备借出占用自动静默"
    if counterparty:
        reason += f"（{counterparty}）"
    s = AlertSilence.objects.create(
        scope={"device_ids": [device_id]}, silence_type="occupation",
        device_usage_id=usage_event_id, reason=reason[:255],
        started_at=timezone.now(), created_by_id=user_id)
    return s.pk


def occupation_end(device_id, user_id=None):
    """归还 → 结束该设备全部未结束的 occupation 静默（幂等，可反复执行）。"""
    from apps.alert.models import AlertSilence
    device_id = int(device_id)
    ended = 0
    for s in AlertSilence.objects.filter(
            silence_type="occupation", ended_at__isnull=True).order_by("-id"):
        if device_id in (s.scope or {}).get("device_ids", []):
            s.ended_at = timezone.now()
            s.save(update_fields=["ended_at", "updated_at"])
            ended += 1
    return ended


# ============ 变更窗口自动静默（change 实施/收尾联动） ============

def change_window_maintenance(device_ids, ticket_id, started_at=None,
                              ended_at=None, reason="变更窗口自动静默"):
    """变更单进入实施 → 对受影响设备建 maintenance 静默（窗口=实际开始..计划结束）。

    跨 app 联动：change.services.start_change_impl 调本函数（best-effort）。
    幂等：同 ticket_id 已存在未结束 maintenance 则不重复建。
    """
    from apps.alert.models import AlertSilence
    ids = [int(i) for i in (device_ids or []) if i]
    if not ids or not ticket_id:
        return None
    existing = AlertSilence.objects.filter(
        silence_type="maintenance", device_usage_id=int(ticket_id),
        ended_at__isnull=True).first()
    if existing:
        return existing.pk
    s = AlertSilence.objects.create(
        scope={"device_ids": ids}, silence_type="maintenance",
        device_usage_id=int(ticket_id),
        reason=(reason or "变更窗口自动静默")[:255],
        started_at=started_at or timezone.now(),
        ended_at=ended_at)
    return s.pk


def end_ticket_maintenance(ticket_id):
    """变更收尾（关闭/回滚）→ 提前结束该单未结束的 maintenance 静默。"""
    from apps.alert.models import AlertSilence
    if not ticket_id:
        return 0
    ended = 0
    for s in AlertSilence.objects.filter(
            silence_type="maintenance", device_usage_id=int(ticket_id)).order_by("-id"):
        if not s.ended_at or s.ended_at > timezone.now():
            s.ended_at = timezone.now()
            s.save(update_fields=["ended_at", "updated_at"])
            ended += 1
    return ended


# ============ 根因抑制 v1（拓扑邻接 × 告警级别） ============
# 语义：设备 D 的活跃事件 e，若存在与 D **拓扑直连（LLDP 邻接）** 的邻居设备 P，
# 且 P 上有未被抑制的更高级别活跃事件 p（severity 严格更高），则 e 视为
# "父宕机引发的下游噪音" → suppressed_by_id=p.id。P 自身同/更低级别事件不受抑制
# （同级双 offline 互为邻居时互不抑制，避免误吞根因）；更细的上下行方向识别
# （接入/汇聚角色、父设备在线态差补）留待后续里程碑。
SEV_RANK = {"critical": 6, "major": 5, "minor": 4, "warning": 3, "notice": 2, "info": 1}


def _lldp_adjacency():
    """{device_id: {邻接设备 id}}：topo_lldpneighbor(remote_device_id) × cmdb_deviceinterface 关联。"""
    from django.db import connection
    adj = {}
    with connection.cursor() as cur:
        cur.execute("""SELECT n.remote_device_id, ifc.device_id
                       FROM topo_lldpneighbor n
                       JOIN cmdb_deviceinterface ifc ON ifc.id = n.local_interface_id
                       WHERE n.remote_device_id IS NOT NULL AND ifc.device_id IS NOT NULL""")
        for remote, local in cur.fetchall():
            adj.setdefault(int(local), set()).add(int(remote))
            adj.setdefault(int(remote), set()).add(int(local))
    return adj


def _sev_rank(s):
    return SEV_RANK.get(s or "", 0)


def sync_root_suppression():
    """抑制同步（幂等，可周期跑）：按上述语义标记/清除 suppressed_by_id。"""
    from apps.alert.models import AlertEvent
    active_status = ("firing", "acknowledged", "processing")
    events = list(AlertEvent.objects.filter(status__in=active_status))
    if not events:
        return {"suppressed": 0, "cleared": 0, "events": 0}
    adj = _lldp_adjacency()
    by_dev = {}
    for ev in events:
        by_dev.setdefault(ev.device_id, []).append(ev)
    suppressed = cleared = 0
    for ev in events:
        cand, cand_rank = None, 0
        for nb in adj.get(ev.device_id, ()):
            for pev in by_dev.get(nb, ()):
                if pev.pk == ev.pk or pev.suppressed_by_id:
                    continue  # 根因本身不再被抑制（防传递吞根）
                r = _sev_rank(pev.severity)
                if r > _sev_rank(ev.severity) and r > cand_rank:
                    cand, cand_rank = pev, r
        want = cand.pk if cand else None
        if want != ev.suppressed_by_id:
            if want:
                suppressed += 1
            else:
                cleared += 1
            ev.suppressed_by_id = want
            ev.save(update_fields=["suppressed_by_id", "updated_at"])
    return {"suppressed": suppressed, "cleared": cleared, "events": len(events)}
