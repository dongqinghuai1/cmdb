"""vCenter 只读拉取适配（apps.cmdb）。

分层纪律同 snmp.py：
- mock：内置样例（回归/演示，不触网）——按命名稳定生成两台虚机；
- real：pyVmomi 拉取骨架——依赖未安装或连接失败时主动 raise RequiresCalibration
  （不写假数据；模板/凭据就绪后可在此实现真实 pull）。
落库（Device upsert/软删）在 cmdb.vmsync.run_sync，本模块只做数据面。
"""


class RequiresCalibration(Exception):
    """真实采集模板/依赖未就绪。调用方记录并跳过，不静默写假数据。"""


def pull(host=None, username=None, secret=None, mock=False, names=None, label=None):
    """拉取虚机清单 → [{name, host, cpus, mem_mb, guest_os, power_state,
    cluster, datacenter}]。mock 时虚机以 label 为名前缀；names 非空时仅返回名单内
    虚机（收敛演练）。"""
    if mock:
        return _mock_vms(label or "vc-demo", names)
    try:
        import pyVmomi  # noqa: F401
    except ModuleNotFoundError as e:  # noqa: F401
        raise RequiresCalibration(
            "pyVmomi 未安装/未校准：vCenter 真实拉取待接入（生产建议独立执行器）"
            "；mock=1 演练请先验证全链路") from e
    raise RequiresCalibration(
        "vCenter 真实拉取模板未校准：连接参数/证书校验流程待接入，当前请用 mock=1 演练")


def _mock_vms(base, names=None):
    """内置样例：web-01 / db-01 两台（名字可收窄到名单内）。"""
    pairs = [
        {"suffix": "web-01", "host": f"esxi-{base}-01", "cpus": 4, "mem_mb": 8192,
         "guest": "CentOS 7", "power": "poweredOn", "cluster": "MOCK-CLUSTER", "dc": "MOCK-DC"},
        {"suffix": "db-01", "host": f"esxi-{base}-01", "cpus": 8, "mem_mb": 16384,
         "guest": "Rocky 9", "power": "poweredOff", "cluster": "MOCK-CLUSTER", "dc": "MOCK-DC"},
    ]
    out = []
    for p in pairs:
        vm_name = f"{base}-{p['suffix']}"
        if names and vm_name not in names:
            continue
        out.append({"name": vm_name, "host": p["host"], "cpus": p["cpus"],
                    "mem_mb": p["mem_mb"], "guest_os": p["guest"],
                    "power_state": p["power"], "cluster": p["cluster"],
                    "datacenter": p["dc"]})
    return out
