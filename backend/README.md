# nops 后端

完整文档见仓库根：`../README.md`、`../docs/DEPLOY.md`（部署）、`../docs/DEVELOPMENT.md`（开发规范）、`../docs/HANDOVER.md`（交接）。

## 常用命令

```powershell
# 本机语法检查（无 PG 时用 SQLite；本机 Python 3.14 装不了 psycopg/pysnmp，属正常）
$env:NOPS_DB='sqlite'; .\.venv\Scripts\python.exe manage.py check

# 容器操作（两组 compose：infra=PG/Redis/VM/MinIO，app=api/worker/beat/web）
docker compose -f docker-compose.infra.yml up -d
docker compose -f docker-compose.app.yml up -d --build
docker compose -f docker-compose.app.yml run --rm api python manage.py migrate

# 迁移后必跑（EXCLUDE/partial unique/trgm）
Get-Content docker\constraints.sql | docker exec -i nops-postgres psql -U nops -d nops

# 初始数据（权限/角色/admin/设备类型/飞书渠道占位）
docker compose -f docker-compose.app.yml run --rm api python manage.py init_nops_data

# 验证（保持全绿：33/22/4/7/10）
.\.venv\Scripts\python.exe scripts\api_test.py
.\.venv\Scripts\python.exe scripts\verify_errors.py
```

## 关键文件

| 文件 | 职责 |
|---|---|
| config/settings.py | 全环境变量化；LLM_BASE_URL/LLM_API_KEY（newapi） |
| common/crypto.py | AES-256-GCM 加密字段（凭据/License/API key） |
| common/permissions.py | RbacPermission（需继承 BasePermission）+ 数据权限注入 |
| apps/system/views.py | BaseModelViewSet（审计/异常基类，各 app 复用） |
| apps/dcim/services.py | 机柜 elevation / U 位跨表冲突校验 / 容量 |
| apps/cmdb/services.py | attrs 校验 / 上架 place / Excel 导入导出 |
| apps/monitor/collector.py | SNMP 引擎 + VictoriaMetrics 统一 label 写入 |
| apps/alert/engine.py | 告警评估 + dedup_key 去重 + 飞书通知 |
| apps/inspect/tasks.py | 巡检执行（异常项转告警） |
| docker/constraints.sql | 数据库级约束（migrate 后执行） |
| scripts/ | 初始化种子 + 全量自动化验证脚本 |
