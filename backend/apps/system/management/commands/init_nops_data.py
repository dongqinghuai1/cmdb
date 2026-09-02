"""初始化数据：预置角色/权限/设备类型模型/管理员/默认渠道。
用法：python manage.py init_nops_data
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db.models import Q

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
            ("system.duty.view", "值班排班查看", "系统管理", "view"),
            ("system.duty.edit", "值班排班编辑", "系统管理", "edit"),
            ("system.sso.view", "飞书 SSO 查看", "系统管理", "view"),
            ("system.sso.edit", "飞书 SSO 配置/同步", "系统管理", "edit"),
            ("dcim.region.view", "机房查看", "机房管理", "view"),
            ("dcim.rack.view", "机柜查看", "机房管理", "view"),
            ("dcim.rack.edit", "机柜编辑", "机房管理", "edit"),
            ("dcim.power.view", "机房电源查看", "机房电源", "view"),
            ("dcim.power.edit", "电源采集/录入", "机房电源", "edit"),
            ("cmdb.model.view", "模型查看", "设备管理", "view"),
            ("cmdb.model.edit", "模型编辑", "设备管理", "edit"),
            ("cmdb.device.view", "设备查看", "设备管理", "view"),
            ("cmdb.device.edit", "设备编辑", "设备管理", "edit"),
            ("cmdb.device.execute", "导入导出", "设备管理", "execute"),
            ("cmdb.vmware.view", "vCenter 虚机查看", "设备管理", "view"),
            ("cmdb.vmware.edit", "vCenter 同步源管理", "设备管理", "edit"),
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
            ("automate.script.view", "脚本查看", "自动化运维", "view"),
            ("automate.script.edit", "脚本编辑", "自动化运维", "edit"),
            ("automate.run.view", "执行记录查看", "自动化运维", "view"),
            ("automate.run.execute", "批量执行", "自动化运维", "execute"),
            ("automate.approve", "审批处理", "自动化运维", "execute"),
            ("change.incident.view", "事件单查看", "事件处理", "view"),
            ("change.incident.edit", "事件单报障/处理", "事件处理", "edit"),
            ("change.ticket.view", "变更单查看", "变更管理", "view"),
            ("change.ticket.edit", "变更申请/提交", "变更管理", "edit"),
            ("change.ticket.execute", "变更实施/验证/关闭", "变更管理", "execute"),
            ("change.ticket.approve", "变更审批", "变更管理", "approve"),
            ("report.snapshot.view", "报表快照查看", "报表中心", "view"),
            ("report.snapshot.edit", "报表生成/订阅编辑", "报表中心", "edit"),
            # 导航权限点（menu.*）：供 RBAC 动态菜单按角色过滤，非功能门禁（后端仍按功能码拦截）
            ("menu.home", "工作台导航", "工作台", "view"),
            ("menu.monitor", "监控告警导航", "监控与告警", "view"),
            ("menu.net", "网络导航", "网络", "view"),
            ("menu.asset", "设备台账导航", "资产与机房", "view"),
            ("menu.dcim", "机房导航", "资产与机房", "view"),
            ("menu.workflow", "流程自动化导航", "流程与自动化", "view"),
            ("menu.security", "安全合规导航", "安全与合规", "view"),
            ("menu.log", "日志导航", "日志中心", "view"),
            ("menu.sysadmin", "系统管理导航", "系统管理", "view"),
        ]
        for code, name, menu, action in perms:
            Permission.objects.get_or_create(code=code, defaults={"name": name, "menu": menu, "action": action})

        # 2. 角色
        admin_role, _ = Role.objects.get_or_create(code="admin", defaults={"name": "系统管理员", "builtin": True})
        admin_role.permissions.set(Permission.objects.all())
        netops, _ = Role.objects.get_or_create(code="net_ops", defaults={"name": "网络运维", "builtin": True})
        netops.permissions.set(Permission.objects.filter(
            Q(code__regex=r"^(dcim|cmdb|monitor|alert|inspect|automate|change|report)\.") |
            Q(code__startswith="menu.")))
        readonly, _ = Role.objects.get_or_create(code="readonly", defaults={"name": "只读", "builtin": True})
        readonly.permissions.set(Permission.objects.filter(action="view"))

        # 2b. 角色化演示角色（导航码决定"看到哪些菜单"，功能码决定"点进去能否用"）
        def _persona(role_code, name, func_codes, nav_codes):
            role, _ = Role.objects.get_or_create(code=role_code,
                                                 defaults={"name": name, "builtin": True})
            role.permissions.set(Permission.objects.filter(code__in=func_codes + nav_codes))
            return role

        _persona("net_admin", "网络管理员", [
            "cmdb.device.view", "cmdb.vmware.view", "dcim.region.view", "dcim.rack.view", "dcim.power.view",
            "alert.event.view", "change.ticket.view", "report.snapshot.view",
        ], ["menu.home", "menu.monitor", "menu.net", "menu.asset", "menu.dcim", "menu.workflow"])
        _persona("sys_admin", "系统运维", [
            "cmdb.device.view", "cmdb.model.view", "cmdb.vmware.view", "cmdb.vmware.edit",
            "monitor.collector.view", "monitor.log.view",
            "alert.event.view", "alert.rule.view", "inspect.template.view", "inspect.run.view",
            "automate.script.view", "automate.run.view", "change.incident.view",
            "system.duty.view", "system.duty.edit", "system.sso.view", "system.sso.edit",
            "report.snapshot.view", "report.snapshot.edit",
        ], ["menu.home", "menu.monitor", "menu.asset", "menu.dcim", "menu.workflow", "menu.log"])
        _persona("dcim_admin", "机房运维", [
            "cmdb.device.view", "cmdb.device.edit", "cmdb.device.execute",
            "dcim.region.view", "dcim.rack.view", "dcim.rack.edit",
            "dcim.power.view", "dcim.power.edit",
        ], ["menu.home", "menu.asset", "menu.dcim"])
        auditor_role = _persona("auditor", "审计员", ["system.audit.view"],
                                ["menu.home", "menu.security"])

        # 3. 管理员
        admin, created = User.objects.get_or_create(username="admin", is_superuser=True, is_staff=True)
        if created:
            admin.set_password("nops@2025")
            admin.save()
            admin.roles.add(admin_role)
            self.stdout.write("admin 创建成功，初始密码 nops@2025（务必修改）")

        # 3b. 角色化演示账号（密码 NopsTest@2025；每次运行重置密码与角色，幂等）
        for uname, role in [
            ("net_demo", Role.objects.get(code="net_admin")),
            ("sys_demo", Role.objects.get(code="sys_admin")),
            ("dcim_demo", Role.objects.get(code="dcim_admin")),
            ("auditor", auditor_role),
        ]:
            u, _ = User.objects.get_or_create(username=uname)
            u.set_password("NopsTest@2025")
            u.is_active = True
            u.is_staff = False
            u.is_superuser = False
            u.save()
            u.roles.set([role])
            self.stdout.write(f"{uname} 角色 {role.name} 就绪")

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
