"""apps.dcim -- 地区/机房/机柜/线缆（ER 4.1）。
EXCLUDE/CHECK 约束在 docker/constraints.sql（迁移后执行）。"""
from django.db import models

from common.models import SoftDeleteModel, TimeStampedModel


class Region(TimeStampedModel):
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    name = models.CharField(max_length=64)
    code = models.CharField(max_length=32, unique=True)
    manager_id = models.BigIntegerField(null=True, blank=True, db_index=True)  # FK user（跨域裸外键）
    remark = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]


class Site(TimeStampedModel):
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="sites")
    name = models.CharField(max_length=64)
    code = models.CharField(max_length=32, unique=True)
    address = models.CharField(max_length=255, blank=True)
    manager_id = models.BigIntegerField(null=True, blank=True)
    contact = models.CharField(max_length=64, blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    bandwidth_mbps = models.IntegerField(null=True, blank=True)
    isp = models.CharField(max_length=64, blank=True)
    floor_len_m = models.FloatField(null=True, blank=True, help_text="机房长(米)")
    floor_w_m = models.FloatField(null=True, blank=True, help_text="机房宽(米)")
    remark = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]


class SiteObject(TimeStampedModel):
    """机房平面图元素（DIY 拖放布局）：机柜/UPS/AP/电箱/消防/门等。"""

    class ObjType(models.TextChoices):
        RACK = "rack"; UPS = "ups"; AP = "ap"; POWER = "power"
        FIRE = "fire"; DOOR = "door"; OTHER = "other"

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="floor_objects")
    obj_type = models.CharField(max_length=16, choices=ObjType.choices, default=ObjType.OTHER)
    name = models.CharField(max_length=64, blank=True)
    rack_id = models.BigIntegerField(null=True, blank=True)  # obj_type=rack 时关联 dcim.Rack
    x = models.FloatField(default=0, help_text="左上角X(米)")
    y = models.FloatField(default=0, help_text="左上角Y(米)")
    w = models.FloatField(default=0.6, help_text="宽(米)")
    h = models.FloatField(default=1.2, help_text="深/高(米)")
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["id"]


class Rack(TimeStampedModel):
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="racks")
    name = models.CharField(max_length=64)
    row_no = models.CharField(max_length=8, blank=True)
    col_no = models.CharField(max_length=8, blank=True)
    u_total = models.PositiveSmallIntegerField(default=42)
    rated_power_w = models.IntegerField(null=True, blank=True)
    rated_weight_kg = models.IntegerField(null=True, blank=True)
    remark = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ("site", "name")
        ordering = ["site_id", "name"]


class RackReservation(TimeStampedModel):
    rack = models.ForeignKey(Rack, on_delete=models.CASCADE, related_name="reservations")
    start_u = models.PositiveSmallIntegerField()
    units = models.PositiveSmallIntegerField(default=1)
    reason = models.CharField(max_length=255, blank=True)
    created_by_id = models.BigIntegerField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["rack_id", "start_u"]


class Cable(SoftDeleteModel):
    class CableType(models.TextChoices):
        CAT5E = "cat5e"; CAT6 = "cat6"; MM_FIBER = "mm_fiber"; SM_FIBER = "sm_fiber"; JUMPER = "jumper"

    class Source(models.TextChoices):
        MANUAL = "manual"; LLDP = "lldp"; CDP = "cdp"

    class Status(models.TextChoices):
        ACTIVE = "active"; MISMATCH = "mismatch"; PLANNED = "planned"; REMOVED = "removed"

    a_interface_id = models.BigIntegerField(db_index=True)   # 跨 app 裸外键（cmdb.device_interface）
    b_interface_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    cable_type = models.CharField(max_length=16, choices=CableType.choices, default=CableType.CAT6)
    length_m = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    path_desc = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    remark = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ("a_interface_id", "b_interface_id")


class DcimTicket(TimeStampedModel):
    """机房作业工单：上架/下架/迁移/维修/布线（IA 机房运维域；U 位目标为计划值，
    设备实际位置变更仍走设备编辑/生命周期，避免双写冲突）。"""

    class Kind(models.TextChoices):
        RACK_IN = "rack_in", "设备上架"
        RACK_OUT = "rack_out", "设备下架"
        MOVE = "move", "设备迁移"
        REPAIR = "repair", "检修维修"
        CABLE = "cable", "布线调整"

    class Status(models.TextChoices):
        PLANNED = "planned", "待处理"
        DOING = "doing", "进行中"
        DONE = "done", "已完成"
        CANCELLED = "cancelled", "已取消"

    title = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    rack = models.ForeignKey(Rack, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="op_tickets")
    device_id = models.BigIntegerField(null=True, blank=True, db_index=True)  # cmdb 设备
    device_name = models.CharField(max_length=120, blank=True)
    u_from = models.PositiveSmallIntegerField(null=True, blank=True)
    u_to = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PLANNED)
    assignee = models.CharField(max_length=64, blank=True)
    planned_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)
    result = models.CharField(max_length=500, blank=True)
    operator_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]


class PowerSample(TimeStampedModel):
    """PDU/UPS 电源实测样本（设备=cmdb 中 model.code in (pdu,ups) 的 facility 设备）。

    采集完全复用既有架构：Prometheus 只读消费（apps/cmdb.prometheus.query_once）为主、
    SNMP 直采（apps/cmdb.snmp.collect_pdu，厂商模板待校准前走 mock 演练）；
    额定功率取 Device.rated_power_w（新建样本时快照，历史不回算）。
    设备删除（cmdb purge）时按 device_id 清理。
    """

    class Source(models.TextChoices):
        PROM = "prom", "Prometheus"
        SNMP = "snmp", "SNMP"
        MANUAL = "manual", "手工录入"

    device_id = models.BigIntegerField(db_index=True)  # cmdb.Device 裸外键
    outlet = models.CharField(max_length=32, blank=True, default="", help_text="输出口（'' 为总路）")
    watts = models.FloatField(null=True, blank=True)
    current_a = models.FloatField(null=True, blank=True)
    voltage_v = models.FloatField(null=True, blank=True)
    utilization_pct = models.FloatField(null=True, blank=True)  # watts / rated 快照
    rated_watts = models.FloatField(null=True, blank=True)      # 采样时刻额定快照
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.PROM)
    sampled_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-sampled_at"]
        verbose_name = "电源实测样本"

    def __str__(self):
        return f"power dev#{self.device_id} {self.outlet or 'total'} {self.watts}W"
