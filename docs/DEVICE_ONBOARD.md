# 真实设备接入指南（在线/离线监控）

## 采集原理

平台通过两条路径判定设备在线状态（每 5 分钟自动执行，也可手动触发）：

```
collect_all (beat 每5分钟)
  └─ collect_batch (每批20台并发)
       └─ 每台设备:
            ① SNMP GET sysName → 成功 = online（顺带写 hostname + 指标到 VM）
            ② SNMP 失败 → ICMP ping → 通 = online（标记 snmp_up=0）
            ③ 都失败 = offline
```

**即使设备不开 SNMP，只要能 ping 通就会显示在线。** 开了 SNMP 则能采集指标（CPU/接口流量等，后续版本）并回填 hostname。

## 接入步骤（5 分钟）

### 第 1 步：在设备上开启 SNMP（可选，推荐）

| 设备 | 配置命令 |
|---|---|
| **H3C 交换机** | `snmp-agent`<br>`snmp-agent community read nopspublic`<br>`snmp-agent sys-info version v2c` |
| **Cisco IOS** | `snmp-server community nopspublic RO` |
| **FortiGate** | `config system snmp community`<br>`edit 1`<br>`set name nopspublic`<br>`set status enable`<br>`end` |
| **深信服 AC** | Web 界面 -> 系统配置 -> SNMP -> 添加只读团体字 |

### 第 2 步：在平台添加 SNMP 凭据

系统管理 -> 凭据管理 -> 新增：
- 名称：`H3C-SNMP`
- 类型：`snmp_v2c`
- 密钥：`nopspublic`（你在设备上配的 community）

### 第 3 步：设备台账录入设备（或编辑已有设备）

- **管理 IP**：设备可达 IP（必填，没有它不采集）
- **采集驱动**：按品牌选（H3C交换机 / Cisco / 飞塔 / 深信服 / 留空=通用）
- **SNMP 凭据**：选第 2 步建的（不选默认 community=public）
- **启用采集**：开

### 第 4 步：立即采集

设备台账 -> 顶部「**立即采集**」按钮 -> 等约 10 秒 -> 刷新列表看「状态」列变绿（online）或灰（offline）。

## 验证采集是否到达设备

```powershell
# 从容器内测试连通性（把 IP 换成你设备的）
docker exec nops-api python -c "import ping3; print(ping3.ping('192.168.1.1', timeout=2))"
# 从容器内测试 SNMP（community 换成你的）
docker exec nops-api python -c "from apps.monitor.collector import _snmp_get; print(_snmp_get('192.168.1.1','nopspublic','1.3.6.1.2.1.1.5.0'))"
```

## 常见问题

| 症状 | 原因 |
|---|---|
| 显示 offline 但设备明明在线 | 容器到设备网络不通（跨网段/VLAN），检查路由或加静态路由 |
| ping 通但 SNMP 不通 | community 不对 / ACL 限制了 SNMP 源 IP / 防火墙拦了 UDP 161 |
| 全部设备 offline | 检查 worker 容器日志：`docker logs nops-worker --tail 50` |
| 采集频率调整 | `config/celery.py` 中 `monitor-collect-all` 的 `schedule` 秒数 |
