"""apps.ipam -- VLAN / subnet / IP ledger (ER 4.10)."""
import ipaddress

from django.core.exceptions import ValidationError
from django.db import models

from common.models import TimeStampedModel


class Vlan(TimeStampedModel):
    vid = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=64)
    site_id = models.BigIntegerField(null=True, blank=True, db_index=True)  # dcim.Site bare FK; null=全局
    purpose = models.CharField(max_length=128, blank=True)
    owner_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["vid"]
        constraints = [models.UniqueConstraint(fields=["vid", "site_id"],
                                               name="uq_vlan_vid_site")]


class Subnet(TimeStampedModel):
    cidr = models.CharField(max_length=18, unique=True)  # 10.1.10.0/24
    vlan_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    gateway = models.GenericIPAddressField(null=True, blank=True)
    purpose = models.CharField(max_length=128, blank=True)
    owner_id = models.BigIntegerField(null=True, blank=True)
    site_id = models.BigIntegerField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["cidr"]

    def clean(self):
        try:
            ipaddress.ip_network(self.cidr, strict=False)
        except ValueError as e:
            raise ValidationError(f"非法网段: {e}")

    @property
    def network(self):
        return ipaddress.ip_network(self.cidr, strict=False)

    @property
    def usable_size(self):
        n = self.network.num_addresses
        return max(n - 2, 1) if n > 2 else n


class IpAddress(TimeStampedModel):
    class Status(models.TextChoices):
        FREE = "free"; USED = "used"; RESERVED = "reserved"; CONFLICT = "conflict"

    class Source(models.TextChoices):
        MANUAL = "manual"; ARP = "arp_discover"; DHCP = "dhcp"

    subnet = models.ForeignKey(Subnet, on_delete=models.CASCADE, related_name="ips")
    address = models.GenericIPAddressField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.USED)
    device_id = models.BigIntegerField(null=True, blank=True, db_index=True)  # cmdb.Device bare FK
    interface_id = models.BigIntegerField(null=True, blank=True)
    mac = models.CharField(max_length=32, blank=True)
    assignee = models.CharField(max_length=64, blank=True)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["address"]
        constraints = [models.UniqueConstraint(fields=["subnet", "address"],
                                               name="uq_ip_subnet_addr")]
