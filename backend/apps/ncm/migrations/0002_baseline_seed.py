"""安全基线规则库预置（幂等 seed，防手工逐条录入）。

覆盖常见网络设备加固检查（按行正则，跨 H3C/思科等厂商常用命令形态）。
"""
from django.db import migrations

SEED_RULES = [
    ("禁止明文 Telnet 服务", "must_absent",
     r"telnet server enable|transport input telnet", "major",
     "明文 telnet 存在嗅探风险，应以 SSH 替代"),
    ("禁止默认 SNMP 团体字符串", "must_absent",
     r"snmp-agent community (read|write) (public|private)|snmp-server community \S+ (RO|RW)|community (read|write) (public|private)", "major",
     "public/private 为默认团体，暴露读写风险"),
    ("启用会话空闲超时", "must_present",
     r"exec-timeout|idle-timeout", "warning",
     "长期空闲会话易被劫持，应配置超时断开"),
    ("禁止明文 HTTP 管理面", "must_absent",
     r"ip http server|local-server http", "major",
     "HTTP 管理面明文传输，应关闭或仅 HTTPS"),
    ("口令加密存储", "must_present",
     r"password (cipher|hash|encrypted)|service password-encryption", "warning",
     "本地口令应以密文存储，禁止明文"),
]


def seed(apps, schema_editor):
    BaselineRule = apps.get_model("ncm", "BaselineRule")
    for name, rule_type, pattern, severity, remark in SEED_RULES:
        BaselineRule.objects.get_or_create(
            name=name,
            defaults={"rule_type": rule_type, "pattern": pattern,
                      "severity": severity, "remark": remark, "scope": {}})


def unseed(apps, schema_editor):
    BaselineRule = apps.get_model("ncm", "BaselineRule")
    BaselineRule.objects.filter(name__in=[r[0] for r in SEED_RULES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ncm", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
