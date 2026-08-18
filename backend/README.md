# nops - 智能运维 CMDB 平台（后端）

配套文档：`../PRD-智能运维CMDB平台.md`（V0.5）、`../ER设计-智能运维CMDB平台.md`（V1.1）。

## 技术栈
Django 5 + DRF + Celery | PostgreSQL 16(JSONB/EXCLUDE) | VictoriaMetrics(指标) | Redis | MinIO | pysnmp/netmiko(采集)

## 快速开始（Docker）
```bash
cd backend
cp .env.example .env   # 修改密钥
docker compose up -d
docker compose exec api python manage.py migrate
docker compose exec api python manage.py init_nops_data
# API: http://localhost:8000/api/docs/  账号: admin / nops@2025
```

## 本地开发（无 PG 时仅语法级检查）
```powershell
.\.venv\Scripts\activate
$env:NOPS_DB='sqlite'; python manage.py check
```

## 结构（PRD 7.2.1 模块化）
- `apps/system` 用户/RBAC/凭据/通知/审计 | `apps/dcim` 地区/机房/机柜/线缆
- `apps/cmdb` 动态模型/设备台账/接口 | `apps/monitor` 采集引擎/日志
- `apps/alert` 告警引擎 | `apps/inspect` 巡检引擎 | `apps/usage` 占用/登录审计
- 其余 app 为二期骨架（topo/ncm/ipam/automate/change/ai/report）
- 纪律：跨 App 只走 services 层；模型互不 import（裸外键）；EXCLUDE/分区约束在迁移 RunSQL 中创建（见 ER D2/D12）

## 周期任务（Celery Beat）
采集分片 collect_shard / 告警评估 evaluate_alert_rules / 巡检 run_inspect —— 由各 app tasks.py 注册。
