"""修复 0002 预置规则的 pattern（0002 首版把跨行字符串拼接误写入换行导致正则不匹配；
本迁移对既有库幂等覆盖为单行正则）。"""
from django.db import migrations

FIX = {
    "禁止明文 Telnet 服务":
        r"telnet server enable|transport input telnet",
    "禁止默认 SNMP 团体字符串":
        r"snmp-agent community (read|write) (public|private)|snmp-server community \S+ (RO|RW)|community (read|write) (public|private)",
    "启用会话空闲超时": r"exec-timeout|idle-timeout",
    "禁止明文 HTTP 管理面": r"ip http server|local-server http",
    "口令加密存储": r"password (cipher|hash|encrypted)|service password-encryption",
}


def fix_patterns(apps, schema_editor):
    BaselineRule = apps.get_model("ncm", "BaselineRule")
    for name, pattern in FIX.items():
        BaselineRule.objects.filter(name=name).update(pattern=pattern)


class Migration(migrations.Migration):

    dependencies = [
        ("ncm", "0002_baseline_seed"),
    ]

    operations = [
        migrations.RunPython(fix_patterns, migrations.RunPython.noop),
    ]
