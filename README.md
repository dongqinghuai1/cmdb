# nops - 企业智能运维 CMDB 平台

以 CMDB 为底座的 IT 设备管理与 AI 自动化运维平台：机房平面图 DIY、机柜 U 位拖拽、设备台账、监控告警、自动巡检。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Django 6 / DRF / Celery / PostgreSQL 16 (JSONB/EXCLUDE) |
| 前端 | Vue3 + Element Plus + Vite |
| 指标 | VictoriaMetrics（PromQL 统一查询，SNMP 与 Prometheus 双源） |
| 中间件 | Redis（队列）、MinIO（对象存储） |
| 部署 | Docker Compose（基础设施组 + 应用组分离） |

## 文档索引（交接必读）

| 文档 | 用途 |
|---|---|
| [docs/HANDOVER.md](docs/HANDOVER.md) | **智能体交接文档**：当前进度、待办、坑与教训、验证脚本 |
| [docs/DEVICE_ONBOARD.md](docs/DEVICE_ONBOARD.md) | **真实设备接入**：SNMP/Ping 在线监控 5 分钟接入指南 |
| [docs/DEPLOY.md](docs/DEPLOY.md) | **部署运维手册**：从零安装、配置、升级、备份 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | **开发规范**：模块地图、数据模型、编码纪律 |
| [PRD-智能运维CMDB平台.md](PRD-智能运维CMDB平台.md) | 产品需求 V0.5（15 项决策记录） |
| [ER设计-智能运维CMDB平台.md](ER设计-智能运维CMDB平台.md) | 数据库设计 V1.1（80 表 + 12 条关键决策） |

## 快速开始（Docker）

```bash
# 0. Docker 网络地址池若耗尽，手动建网（否则 compose 自动创建）
docker network create --subnet 172.30.0.0/24 nops-net

# 1. 基础设施组（PG/Redis/VictoriaMetrics/MinIO）
cd backend
docker compose -f docker-compose.infra.yml up -d

# 2. 应用组（api/worker/beat/web 前端）
cp .env.example .env   # 填入 DJANGO_SECRET_KEY / NOPS_CRYPTO_KEY / LLM_API_KEY
docker compose -f docker-compose.app.yml up -d --build

# 3. 初始化（仅首次）
docker compose -f docker-compose.app.yml run --rm api python manage.py migrate
Get-Content docker\constraints.sql | docker exec -i nops-postgres psql -U nops -d nops   # 数据库级约束
docker compose -f docker-compose.app.yml run --rm api python manage.py init_nops_data   # 权限/角色/admin/设备类型

# 4. 访问
# 前端:  http://localhost:8090   (admin / nops@2025，登录后立即改密)
# API:   http://localhost:8000/api/docs/  (Swagger)
```

## 目录结构

```
├── PRD-智能运维CMDB平台.md      产品需求（决策记录在第 11 章）
├── ER设计-智能运维CMDB平台.md   数据库设计（决策 D1-D12）
├── docs/                       部署/开发/交接文档
├── backend/                    Django 后端
│   ├── apps/{system,dcim,cmdb,monitor,usage,alert,inspect}   一期七大模块
│   ├── apps/{topo,ncm,ipam,automate,change,ai,report}       二期骨架
│   ├── common/                 加密字段/RBAC/审计/异常处理
│   ├── scripts/                初始化与全量自动化验证脚本
│   └── docker-compose.{infra,app}.yml
└── frontend/                   Vue3 前端（nginx 容器化）
```

## 验证脚本（每次改动后跑）

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\api_test.py         # 核心 CRUD 33 项
.\.venv\Scripts\python.exe scripts\verify_errors.py    # 错误场景 22 项
.\.venv\Scripts\python.exe scripts\seed_demo.py        # 演示数据（幂等）
```
