import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_SECRET_KEY", "x")
sys.path.insert(0, "/app")

import django

django.setup()

from apps.cmdb.models import Device, DeviceInterface
from apps.topo.models import LldpNeighbor

def dev(name):
    return Device.objects.filter(name=name).first()


core = dev("SW-CORE-01")
acc2 = dev("SW-ACC-02")
acc3 = dev("SW-ACC-03")
fw = dev("FW-EXIT-01")


def ifc(dev, name):
    return DeviceInterface.objects.get_or_create(
        device=dev, name=name,
        defaults={"if_index": 1, "admin_status": "up", "oper_status": "up"})[0]


pairs = [
    (core, "GE1/0/24", acc2, "GE1/0/1"),
    (core, "GE1/0/24", acc3, "GE1/0/1"),
    (acc2, "GE1/0/2", fw, "GE1/0/23"),
]
for ld, ln, rd, rn in pairs:
    if not ld or not rd:
        continue
    LldpNeighbor.objects.get_or_create(
        local_interface_id=ifc(ld, ln).id,
        remote_chassis_id="mac-" + rd.name, remote_port_id=rn,
        defaults={"remote_hostname": rd.name, "remote_port_desc": rn,
                  "remote_device_id": rd.id})
print("topo seeded:", LldpNeighbor.objects.count(), "neighbors,",
      DeviceInterface.objects.count(), "interfaces")
