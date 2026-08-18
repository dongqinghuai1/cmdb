"""初始化数据：预置角色/权限/设备类型模型/管理员/默认渠道。
用法：python manage.py init_nops_data
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from apps.system.models import NotifyChannel, Permission, Role


class Command(BaseCommand):
    help = "初始化 nops 预置数据"

    def handle(self, *args, **opts):
        # 1. 权限点（一期）
        perms = [
            ("system.user.view", "用户查看", "系统管理", "view"),
            ("system.role.view", "角色查看", "系统管理", "view"),
            ("system.credential.view", "凭据查看", "系统管理", "view"),
            ("system.channel.view", "通知渠道", "系统管理", "view"),
            ("system.audit.view", "审计查看", "系统管理", "view"),
            ("system.config.view", "参数配置", "系统管理", "view"),
            ("system.token.view", "API Token", "系统管理", "view"),
            ("dcim.region.view", "机房查看", "机房管理", "view"),
            ("dcim.rack.view", "机柜查看", "机房管理", "view"),
            ("dcim.rack.edit", "机柜编辑", "机房管理", "edit"),
            ("cmdb.model.view", "模型查看", "设备管理", "view"),
            ("cmdb.model.edit", "模型编辑", "设备管理", "edit"),
            ("cmdb.device.view", "设备查看", "设备管理", "view"),
            ("cmdb.device.edit", "设备编辑", "设备管理", "edit"),
            ("cmdb.device.execute", "导入导出", "设备管理", "execute"),
            ("monitor.collector.view", "采集器查看", "监控中心", "view"),
            ("monitor.log.view", "日志查看", "监控中心", "view"),
            ("alert.rule.view", "告警规则", "告警中心", "view"),
            ("alert.rule.edit", "告警规则编辑", "告警中心", "edit"),
            ("alert.event.view", "告警查看", "告警中心", "view"),
            ("alert.event.execute", "告警处理", "告警中心", "execute"),
            ("inspect.template.view", "巡检模板", "巡检中心", "view"),
            ("inspect.template.edit", "巡检模板编辑", "巡检中心", "edit"),
            ("inspect.run.view", "巡检记录", "巡检中心", "view"),
            ("inspect.run.execute", "执行巡检", "巡检中心", "execute"),
        ]
        for code, name, menu, action in perms:
            Permission.objects.get_or_create(code=code, defaults={"name": name, "menu": menu, "action": action})

        # 2. 角色
        admin_role, _ = Role.objects.get_or_create(code="admin", defaults={"name": "系统管理员", "builtin": True})
        admin_role.permissions.set(Permission.objects.all())
        netops, _ = Role.objects.get_or_create(code="net_ops", defaults={"name": "网络运维", "builtin": True})
        netops.permissions.set(Permission.objects.filter(code__regex=r"^(dcim|cmdb|monitor|alert|inspect)\."))
        readonly, _ = Role.objects.get_or_create(code="readonly", defaults={"name": "只读", "builtin": True})
        readonly.permissions.set(Permission.objects.filter(action="view"))

        # 3. 管理员
        admin, created = User.objects.get_or_create(username="admin", is_superuser=True, is_staff=True)
        if created:
            admin.set_password("nops@2025")
            admin.save()
            admin.roles.add(admin_role)
            self.stdout.write("admin 创建成功，初始密码 nops@2025（务必修改）")

        # 4. 默认飞书渠道（占位，webhook 待填）
        NotifyChannel.objects.get_or_create(
            name="默认飞书", channel_type="feishu",
            defaults={"config": {"webhook_url": ""}, "enabled": False},
        )

        # 5. 设备类型模型（cmdbCiModel 由 cmdb agent 实现；此处延迟导入避免依赖顺序问题）
        from apps.cmdb.models import CiModel
        for code, name, cat, u, sn_req, mg in [
            ("firewall", "防火墙", "security", 1, True, True),
            ("switch", "交换机", "network", 1, True, True),
            ("router", "路由器", "network", 1, True, True),
            ("wlc", "无线AC", "wireless", 1, True, True),
            ("ap", "无线AP", "wireless", 1, True, False),
            ("sangfor_ac", "上网行为管理", "security", 1, True, True),
            ("server", "服务器(宿主机)", "server", 2, True, True),
            ("vm", "虚拟机/云主机", "server", 1, False, False),
            ("ont", "光猫", "facility", 1, True, False),
            ("odf", "ODF", "facility", 1, False, False),
            ("pdu", "PDU", "facility", 1, False, False),
            ("ups", "UPS", "facility", 2, False, False),
        ]:
            CiModel.objects.get_or_create(code=code, defaults={
                "name": name, "category": cat, "default_u_height": u,
                "sn_required": sn_req, "manageable": mg})

        self.stdout.write(self.style.SUCCESS("nops 初始数据完成"))
