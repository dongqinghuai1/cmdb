"""apps.topo -- LLDP neighbor + topology (ER 4.8)."""
from django.db import models

from common.models import TimeStampedModel


class LldpNeighbor(TimeStampedModel):
    """LLDP/CDP discovered neighbor (raw data, compared with cable ledger)."""
    local_interface_id = models.BigIntegerField(db_index=True)  # cmdb.DeviceInterface bare FK
    source = models.CharField(max_length=8, default="lldp")     # lldp / cdp
    remote_chassis_id = models.CharField(max_length=128, blank=True)
    remote_hostname = models.CharField(max_length=128, blank=True)
    remote_port_desc = models.CharField(max_length=128, blank=True)
    remote_port_id = models.CharField(max_length=128, blank=True)
    remote_device_id = models.BigIntegerField(null=True, blank=True, db_index=True)  # matched managed device
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("local_interface_id", "remote_chassis_id", "remote_port_id")
        ordering = ["local_interface_id"]


class Topology(TimeStampedModel):
    class TopoType(models.TextChoices):
        PHYSICAL_L2 = "physical_l2"; L3 = "l3"; WIRELESS = "wireless"; CUSTOM = "custom"

    name = models.CharField(max_length=64, unique=True)
    topo_type = models.CharField(max_length=16, choices=TopoType.choices, default=TopoType.PHYSICAL_L2)
    remark = models.CharField(max_length=255, blank=True)


class TopologyNode(TimeStampedModel):
    topology = models.ForeignKey(Topology, on_delete=models.CASCADE, related_name="nodes")
    device_id = models.BigIntegerField(db_index=True)
    x = models.FloatField(default=0)
    y = models.FloatField(default=0)
    label = models.CharField(max_length=64, blank=True)

    class Meta:
        unique_together = ("topology", "device_id")


class TopologyEdge(TimeStampedModel):
    """Manual/custom edge; auto edges (LLDP) computed live, never stored."""
    topology = models.ForeignKey(Topology, on_delete=models.CASCADE, related_name="edges")
    a_device_id = models.BigIntegerField(db_index=True)
    b_device_id = models.BigIntegerField(db_index=True)
    label = models.CharField(max_length=64, blank=True)
    style = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("topology", "a_device_id", "b_device_id")
