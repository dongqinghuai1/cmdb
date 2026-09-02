"""apps.cmdb -- dynamic model / device inventory / interfaces (ER 4.2)."""
from django.contrib.auth.models import User
from django.db import models

from common.crypto import EncryptedTextField
from common.models import SoftDeleteModel, TimeStampedModel


class CiModel(TimeStampedModel):
    class Category(models.TextChoices):
        NETWORK = "network"; SECURITY = "security"; SERVER = "server"
        FACILITY = "facility"; WIRELESS = "wireless"; OTHER = "other"

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=64)
    category = models.CharField(max_length=32, choices=Category.choices, default=Category.OTHER)
    default_u_height = models.PositiveSmallIntegerField(default=1)
    sn_required = models.BooleanField(default=True)
    manageable = models.BooleanField(default=False)
    icon = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["code"]


class CiModelAttr(TimeStampedModel):
    class AttrType(models.TextChoices):
        TEXT = "text"; INT = "int"; FLOAT = "float"; BOOL = "bool"
        ENUM = "enum"; DATE = "date"; IP = "ip"; JSON = "json"

    model = models.ForeignKey(CiModel, on_delete=models.CASCADE, related_name="attrs_def")
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=64)
    attr_type = models.CharField(max_length=16, choices=AttrType.choices, default=AttrType.TEXT)
    enum_options = models.JSONField(default=list, blank=True)
    is_required = models.BooleanField(default=False)
    default_value = models.CharField(max_length=255, blank=True)
    is_auto_collected = models.BooleanField(default=False)
    is_manual_locked = models.BooleanField(default=False)
    sort = models.IntegerField(default=0)

    class Meta:
        unique_together = ("model", "code")
        ordering = ["sort", "id"]


class Device(SoftDeleteModel):
    class Lifecycle(models.TextChoices):
        PLANNING = "planning"; PURCHASING = "purchasing"; IN_STOCK = "in_stock"
        DEPLOYED = "deployed"; REPAIRING = "repairing"; SPARE = "spare"; RETIRED = "retired"

    class UsageStatus(models.TextChoices):
        IDLE = "idle"; OCCUPIED = "occupied"; RESERVED = "reserved"; MAINTENANCE_LOCK = "maintenance_lock"

    class UsageTag(models.TextChoices):
        PROD = "prod"; TEST = "test"; DEV = "dev"; SHARED = "shared"

    class OnlineStatus(models.TextChoices):
        ONLINE = "online"; OFFLINE = "offline"; COLLECT_ERROR = "collect_error"

    sn = models.CharField(max_length=64, null=True, blank=True)
    asset_no = models.CharField(max_length=64, null=True, blank=True)
    name = models.CharField(max_length=128)
    hostname = models.CharField(max_length=128, blank=True)
    model = models.ForeignKey(CiModel, on_delete=models.PROTECT, related_name="devices")
    vendor = models.CharField(max_length=64, blank=True)
    hw_model = models.CharField(max_length=128, blank=True)
    sw_version = models.CharField(max_length=64, blank=True)
    manage_ip = models.GenericIPAddressField(null=True, blank=True)
    region = models.ForeignKey("dcim.Region", on_delete=models.PROTECT, related_name="devices")
    site = models.ForeignKey("dcim.Site", on_delete=models.PROTECT, related_name="devices")
    rack = models.ForeignKey("dcim.Rack", null=True, blank=True, on_delete=models.SET_NULL, related_name="devices")
    rack_start_u = models.PositiveSmallIntegerField(null=True, blank=True)
    rack_units = models.PositiveSmallIntegerField(default=1)
    parent_device = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="vms")
    is_virtual = models.BooleanField(default=False)
    vm_source = models.CharField(max_length=32, null=True, blank=True)
    vm_uuid = models.CharField(max_length=128, null=True, blank=True)
    usage_tag = models.CharField(max_length=16, choices=UsageTag.choices, default=UsageTag.PROD)
    shareable = models.BooleanField(default=False)
    lifecycle_status = models.CharField(max_length=16, choices=Lifecycle.choices, default=Lifecycle.DEPLOYED)
    usage_status = models.CharField(max_length=16, choices=UsageStatus.choices, default=UsageStatus.IDLE)
    online_status = models.CharField(max_length=16, choices=OnlineStatus.choices, default=OnlineStatus.OFFLINE)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    driver_type = models.CharField(max_length=64, null=True, blank=True)
    credential_id = models.BigIntegerField(null=True, blank=True)
    collector_id = models.BigIntegerField(null=True, blank=True)
    collect_enabled = models.BooleanField(default=True)
    collect_interval_s = models.IntegerField(default=300)
    rated_power_w = models.IntegerField(null=True, blank=True)
    owner = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    dept_id = models.BigIntegerField(null=True, blank=True)
    purchase_date = models.DateField(null=True, blank=True)
    warranty_until = models.DateField(null=True, blank=True)
    supplier = models.CharField(max_length=128, blank=True)
    attrs = models.JSONField(default=dict, blank=True)
    locked_fields = models.JSONField(default=list, blank=True)
    remark = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        if self.rack_id:
            from apps.dcim.models import Site
            self.region_id = Site.objects.values_list("region_id", flat=True).get(pk=self.site_id)
        if not self.rack_id:
            self.rack_start_u = None
        super().save(*args, **kwargs)


class DeviceGroup(TimeStampedModel):
    name = models.CharField(max_length=64, unique=True)
    group_type = models.CharField(max_length=8, choices=[("static", "static"), ("dynamic", "dynamic")], default="static")
    filter = models.JSONField(default=dict, blank=True)
    devices = models.ManyToManyField(Device, blank=True, related_name="groups")

    def member_ids(self):
        if self.group_type == "static":
            return list(self.devices.values_list("id", flat=True))
        qs = Device.objects.filter(deleted_at__isnull=True)
        f = self.filter or {}
        if f.get("model"):
            qs = qs.filter(model__code=f["model"])
        if f.get("region_id"):
            qs = qs.filter(region_id=f["region_id"])
        if f.get("vendor"):
            qs = qs.filter(vendor=f["vendor"])
        return list(qs.values_list("id", flat=True))


class DeviceInterface(TimeStampedModel):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="interfaces")
    name = models.CharField(max_length=64)
    if_index = models.IntegerField(null=True, blank=True)
    if_alias = models.CharField(max_length=255, blank=True)
    media_type = models.CharField(max_length=32, blank=True)
    admin_status = models.CharField(max_length=8, blank=True)
    oper_status = models.CharField(max_length=8, blank=True)
    speed_bps = models.BigIntegerField(null=True, blank=True)
    duplex = models.CharField(max_length=8, blank=True)
    vlan_ids = models.JSONField(default=list, blank=True)
    native_vlan = models.IntegerField(null=True, blank=True)
    mac = models.CharField(max_length=32, blank=True)
    is_uplink = models.BooleanField(default=False)
    flap_count = models.IntegerField(default=0)
    last_flap_at = models.DateTimeField(null=True, blank=True)
    attrs = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("device", "name")
        ordering = ["device_id", "if_index", "name"]


class DeviceInterfaceStat(models.Model):
    interface = models.OneToOneField(DeviceInterface, on_delete=models.CASCADE, related_name="stat")
    in_bps = models.BigIntegerField(default=0)
    out_bps = models.BigIntegerField(default=0)
    in_pps = models.BigIntegerField(default=0)
    out_pps = models.BigIntegerField(default=0)
    in_errors_total = models.BigIntegerField(default=0)
    out_errors_total = models.BigIntegerField(default=0)
    in_errors_rate = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    out_errors_rate = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    in_drops_total = models.BigIntegerField(default=0)
    broadcast_pps = models.BigIntegerField(default=0)
    optical_tx_dbm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    optical_rx_dbm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    poe_watt = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class DeviceAttachment(TimeStampedModel):
    class FileType(models.TextChoices):
        PHOTO = "photo"; CONTRACT = "contract"; MANUAL = "manual"; WARRANTY = "warranty"; OTHER = "other"

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="attachments")
    file_name = models.CharField(max_length=255)
    file_url = models.CharField(max_length=512)
    file_type = models.CharField(max_length=16, choices=FileType.choices, default=FileType.OTHER)
    size = models.IntegerField(default=0)
    uploaded_by_id = models.BigIntegerField(null=True, blank=True)


class DeviceAssetEvent(TimeStampedModel):
    class EventType(models.TextChoices):
        PURCHASE = "purchase"; IN_STOCK = "in_stock"; DEPLOY = "deploy"; REPAIR = "repair"
        BORROW = "borrow"; RETURN = "return"; SPARE = "spare"; RETIRE = "retire"

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="asset_events")
    event_type = models.CharField(max_length=16, choices=EventType.choices)
    occurred_at = models.DateTimeField()
    operator_id = models.BigIntegerField(null=True, blank=True)
    counterparty = models.CharField(max_length=64, blank=True)
    detail = models.JSONField(default=dict, blank=True)


class License(TimeStampedModel):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="licenses")
    license_type = models.CharField(max_length=64)
    key = EncryptedTextField(blank=True)
    seats = models.IntegerField(null=True, blank=True)
    expire_at = models.DateField(null=True, blank=True)
    supplier = models.CharField(max_length=128, blank=True)
    contract_no = models.CharField(max_length=64, blank=True)
    remark = models.CharField(max_length=255, blank=True)


class WirelessApInfo(TimeStampedModel):
    device = models.OneToOneField(Device, on_delete=models.CASCADE, related_name="ap_info")
    wlc_device_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    ap_name = models.CharField(max_length=64, blank=True)
    ap_ip = models.GenericIPAddressField(null=True, blank=True)
    ap_model = models.CharField(max_length=64, blank=True)
    channel_2g = models.CharField(max_length=8, blank=True)
    channel_5g = models.CharField(max_length=8, blank=True)
    tx_power = models.PositiveSmallIntegerField(null=True, blank=True)
    client_count = models.IntegerField(default=0)
    uplink_switch_id = models.BigIntegerField(null=True, blank=True)
    uplink_interface = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, default="online")
    synced_at = models.DateTimeField(null=True, blank=True)


class RouteTableSnapshot(models.Model):
    device_id = models.BigIntegerField(db_index=True)
    snapshot_at = models.DateTimeField(auto_now_add=True)
    routes = models.JSONField(default=list)
    route_hash = models.CharField(max_length=64, db_index=True)


class TechSnapshot(TimeStampedModel):
    """扩展技术概览通用快照（R3 建模）：ACL/IPSec 等尚无专用采集表的品类。

    采集驱动(fortigate/asa 等)解析设备输出后调用 save_tech_snapshot 落库；
    360 技术概览按 device_id + kind 取最新一条透出，取代 extensions 里的“未支持”占位。
    kind 与 extensions 键对齐：acl / ipsec / 未来可加其他品类。
    """
    class Kind(models.TextChoices):
        ACL = "acl", "acl"
        NAT = "nat", "nat"
        IPSEC = "ipsec", "ipsec"

    device_id = models.BigIntegerField(db_index=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    payload = models.JSONField(default=dict, blank=True)  # 采集结果原文（结构化字段见采集驱动）

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["device_id", "kind"], name="cmdb_techs_dev_kind")]


class RoutingNeighbor(TimeStampedModel):
    device_id = models.BigIntegerField(db_index=True)
    protocol = models.CharField(max_length=8, choices=[("ospf", "ospf"), ("bgp", "bgp")])
    vrf = models.CharField(max_length=32, blank=True)
    neighbor_addr = models.GenericIPAddressField()
    state = models.CharField(max_length=16, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("device_id", "protocol", "neighbor_addr")


class Business(TimeStampedModel):
    name = models.CharField(max_length=64)
    code = models.CharField(max_length=64, unique=True)
    owner_id = models.BigIntegerField(null=True, blank=True)
    importance = models.CharField(max_length=16, default="normal")
    remark = models.CharField(max_length=255, blank=True)


class DeviceBusiness(TimeStampedModel):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="device_links")
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="business_links")
    role = models.CharField(max_length=16, default="member")

    class Meta:
        unique_together = ("business", "device")
