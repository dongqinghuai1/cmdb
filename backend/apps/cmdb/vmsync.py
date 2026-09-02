"""vCenter 虚机同步服务：拉取（cmdb.vcenter）→ cmdb.Device upsert / 收敛软删。

虚机标识：vm_source = "vcenter:<source_pk>" + vm_uuid = md5(f"{pk}:{vm_name}")（幂等）。
收敛：不在本次清单内的同源虚机软删除（软删不物理清，防误删可恢复）。
"""
import hashlib
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def _source_marker(pk):
    return f"vcenter:{pk}"


def _uuid_for(source_pk, vm_name):
    return hashlib.md5(f"{source_pk}:{vm_name}".encode()).hexdigest()


def _default_loc():
    from apps.cmdb.models import CiModel
    from apps.dcim.models import Region, Site
    model = CiModel.objects.filter(code="vm").first() or CiModel.objects.first()
    site = Site.objects.order_by("id").first()
    region = Region.objects.order_by("id").first()
    return model, site, region


def run_sync(source, mock=True):
    """执行一轮同步，返回 {created, updated, unchanged, removed, items}。

    mock=False 时拉取层可能 raise RequiresCalibration（依赖/模板未就绪）——调用方记录。
    虚机标识：vm_source = "vcenter:<source_pk>" + vm_uuid = md5(f"{pk}:{vm_name}")。
    收敛：不在本次清单的同源"存活"虚机软删；软删者重新出现时复活（deleted_at 置空）。
    """
    from apps.cmdb.models import Device, VmwareSource
    from apps.cmdb import vcenter as vc
    marker = _source_marker(source.pk)
    vms = vc.pull(host=source.host, username=source.username, secret=source.secret,
                  mock=mock, names=(source.mock_vms or None), label=source.name)
    model, site, region = _default_loc()
    site_id = source.site_id or (site.id if site else None)
    region_id = source.region_id or (region.id if region else None)
    alive = {d.name: d for d in Device.objects.filter(
        vm_source=marker, deleted_at__isnull=True)}
    archived = {d.name: d for d in Device.all_objects.filter(vm_source=marker)
                if d.deleted_at is not None}
    fetched = {}
    created = updated = unchanged = resurrected = 0
    for vm in vms:
        vm_name = vm["name"]
        fetched[vm_name] = True
        uuid_ = _uuid_for(source.pk, vm_name)
        attrs = {"cpus": vm.get("cpus"), "mem_mb": vm.get("mem_mb"),
                 "guest_os": vm.get("guest_os"), "power_state": vm.get("power_state"),
                 "host": vm.get("host"), "cluster": vm.get("cluster"),
                 "datacenter": vm.get("datacenter")}
        online = "online" if vm.get("power_state") == "poweredOn" else "offline"
        dev = alive.get(vm_name)
        if dev is None and vm_name in archived:
            # 复活软删记录，避免重复建档
            dev = archived[vm_name]
            dev.deleted_at = None
            dev.attrs, dev.online_status, dev.vm_uuid, dev.hostname = attrs, online, uuid_, vm_name
            dev.save(update_fields=["deleted_at", "attrs", "online_status",
                                    "vm_uuid", "hostname", "updated_at"])
            alive[vm_name] = dev
            resurrected += 1
            continue
        if dev is None:
            dev = Device.objects.create(
                name=vm_name, vendor="VMware", model=model,
                site_id=site_id, region_id=region_id,
                is_virtual=True, vm_source=marker, vm_uuid=uuid_,
                hw_model=vm.get("cluster") or "", hostname=vm_name,
                attrs=attrs, online_status=online, remark="vCenter 同步",
                driver_type="", rack=None)
            created += 1
            continue
        # 存活 → 有实质差异才更新
        dirty = dev.attrs != attrs or dev.online_status != online \
            or dev.vm_uuid != uuid_ or dev.hostname != vm_name
        if dirty:
            dev.attrs, dev.online_status = attrs, online
            dev.vm_uuid, dev.hostname = uuid_, vm_name
            dev.save(update_fields=["attrs", "online_status", "vm_uuid", "hostname",
                                    "updated_at"])
            updated += 1
        else:
            unchanged += 1
    # 收敛：不在本次清单的存活同源虚机软删
    removed = 0
    for name, dev in alive.items():
        if name not in fetched:
            dev.delete()   # SoftDelete：deleted_at 置位，可恢复
            removed += 1
    now = timezone.now()
    result = {"created": created, "updated": updated, "unchanged": unchanged,
              "resurrected": resurrected, "removed": removed, "mock": mock,
              "run_at": now.isoformat()}
    VmwareSource.objects.filter(pk=source.pk).update(last_sync_at=now,
                                                     last_result=result)
    return result
