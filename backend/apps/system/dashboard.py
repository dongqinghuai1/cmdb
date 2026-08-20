"""Dashboard 聚合 API（一次请求返回全部驾驶舱数据）。"""
from django.db import connection
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import RbacPermission


def _q(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


class DashboardSummaryView(APIView):
    permission_classes = [RbacPermission]

    def get(self, request):
        # 设备概览（按类型 × 在线状态）
        devices = _q("""
            SELECT m.code AS model_code, m.name AS model_name,
                   d.online_status, COUNT(*) AS cnt
            FROM cmdb_device d JOIN cmdb_cimodel m ON m.id=d.model_id
            WHERE d.deleted_at IS NULL
            GROUP BY m.code, m.name, d.online_status""")

        # 按地区/机房统计
        sites = _q("""
            SELECT r.name AS region, s.name AS site,
                   COUNT(d.id) AS total,
                   SUM(CASE WHEN d.online_status='online' THEN 1 ELSE 0 END) AS online,
                   SUM(CASE WHEN d.online_status='offline' THEN 1 ELSE 0 END) AS offline
            FROM dcim_region r
            JOIN dcim_site s ON s.region_id=r.id
            LEFT JOIN cmdb_device d ON d.site_id=s.id AND d.deleted_at IS NULL
            GROUP BY r.name, s.name ORDER BY r.name, s.name""")

        # 告警摘要
        alerts = _q("""
            SELECT severity, COUNT(*) AS cnt,
                   SUM(CASE WHEN acked_at IS NULL THEN 1 ELSE 0 END) AS unacked
            FROM alert_alertevent
            WHERE status IN ('firing','acknowledged','processing')
            GROUP BY severity""")

        # 最近巡检
        inspections = _q("""
            SELECT id, trigger_type, status, total_devices, abnormal_devices,
                   health_score_avg, finished_at::text
            FROM inspect_inspectrun ORDER BY id DESC LIMIT 5""")

        # 机柜容量 TOP（剩余U最少的）
        capacity = _q("""
            SELECT k.name AS rack, s.name AS site, k.u_total,
                   COUNT(d.id) AS used_u
            FROM dcim_rack k
            JOIN dcim_site s ON s.id=k.site_id
            LEFT JOIN cmdb_device d ON d.rack_id=k.id AND d.deleted_at IS NULL
            GROUP BY k.name, s.name, k.u_total, k.id
            ORDER BY CAST(COUNT(d.id) AS FLOAT)/k.u_total DESC LIMIT 8""")

        # 最近配置变更
        config_changes = _q("""
            SELECT e.device_id, e.changed_lines, e.detected_at::text, d.name AS device_name
            FROM ncm_configchangeevent e
            LEFT JOIN cmdb_device d ON d.id=e.device_id
            ORDER BY e.detected_at DESC LIMIT 5""")

        # 日志统计（近24h）
        logs = _q("""
            SELECT severity, COUNT(*) AS cnt
            FROM monitor_logrecord
            WHERE occurred_at > NOW() - INTERVAL '24 hours'
            GROUP BY severity ORDER BY severity""")

        # 汇总数字
        totals = _q("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN online_status='online' THEN 1 ELSE 0 END) AS online,
                   SUM(CASE WHEN online_status='offline' THEN 1 ELSE 0 END) AS offline
            FROM cmdb_device WHERE deleted_at IS NULL""")[0] if _q("SELECT 1 FROM cmdb_device LIMIT 1") else {"total": 0, "online": 0, "offline": 0}

        alert_total = sum(a["cnt"] for a in alerts) if alerts else 0

        return Response({
            "devices": devices,
            "sites": sites,
            "alerts": alerts, "alert_total": alert_total,
            "inspections": inspections,
            "capacity": capacity,
            "config_changes": config_changes,
            "logs_24h": logs,
            "totals": totals,
        })
