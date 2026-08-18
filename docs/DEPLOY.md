# 部署运维手册

## 1. 架构与端口

```
[浏览器] → nops-web (nginx :8090)
              ├─ 静态 / → Vue3 SPA
              └─ /api/ → nops-api (gunicorn×4 :8000)
                           ├─ nops-postgres (:5432, 健康检查)
                           ├─ nops-redis (celery broker)
                           ├─ nops-vm (VictoriaMetrics :8428)
                           └─ nops-minio (:9000)
nops-worker (celery) / nops-beat (定时) ← 同 Redis
```

两组 compose（`backend/` 目录）：
- `docker-compose.infra.yml`：postgres16 + redis + victoriametrics + minio（数据卷 pg_data/vm_data/minio_data）
- `docker-compose.app.yml`：api + worker + beat + web（前端 nginx）

网络：外部网络 `nops-net`（172.30.0.0/24）。**宿主机 Docker 地址池耗尽时需手动创建**：
`docker network create --subnet 172.30.0.0/24 nops-net`

## 2. 从零部署（Windows/任意有 Docker 的机器）

```powershell
cd backend

# 0. 网络（已存在则跳过）
docker network create --subnet 172.30.0.0/24 nops-net

# 1. 配置
copy .env.example .env
#   必改: DJANGO_SECRET_KEY、NOPS_CRYPTO_KEY（≥32字符，决定凭据加密，改后旧密文不可解）
#   待填: LLM_API_KEY（公司 newapi 的 key；LLM_BASE_URL 已指向 http://api.memblaze.com/v1）
#   可选: POSTGRES_PASSWORD / MINIO 密码

# 2. 基础设施
docker compose -f docker-compose.infra.yml up -d

# 3. 应用（首次会构建两个镜像：backend Python3.12、frontend node20+nginx）
docker compose -f docker-compose.app.yml up -d --build

# 4. 数据库迁移 + 约束 + 初始数据（仅首次）
docker compose -f docker-compose.app.yml run --rm api python manage.py migrate
Get-Content docker\constraints.sql | docker exec -i nops-postgres psql -U nops -d nops
docker compose -f docker-compose.app.yml run --rm api python manage.py init_nops_data

# 5. 演示数据（可选，幂等；宿主机需 backend/.venv）
.\.venv\Scripts\python.exe scripts\seed_demo.py
.\.venv\Scripts\python.exe scripts\seed_floorplan.py
```

初始账号 `admin / nops@2025`（**首次登录立即在系统管理中改密**）。

## 3. 日常运维

```powershell
# 升级代码后重建
git pull
docker compose -f docker-compose.app.yml up -d --build

# 只改了后端
docker compose -f docker-compose.app.yml build api worker beat; docker compose -f docker-compose.app.yml up -d

# 只改了前端
docker compose -f docker-compose.app.yml build web; docker compose -f docker-compose.app.yml up -d web

# 生成/应用新迁移（模型改动后）
docker compose -f docker-compose.app.yml run --rm api python manage.py makemigrations <app>
docker compose -f docker-compose.app.yml run --rm api python manage.py migrate

# 看日志
docker logs -f nops-api --tail 100
docker logs -f nops-worker --tail 50
```

## 4. 备份与恢复（RPO≤24h，PRD 第 6 章）

```powershell
# 备份（PG 全量 + 配置）
docker exec nops-postgres pg_dump -U nops nops > backup_$(Get-Date -Format yyyyMMdd).sql
copy backend\.env backup_env_$(Get-Date -Format yyyyMMdd)

# 恢复
Get-Content backup_xxx.sql | docker exec -i nops-postgres psql -U nops -d nops
# 恢复后重跑约束（幂等）：constraints.sql 中 EXCLUDE 需先 DROP 再建（见文件内注释）
```

MinIO 数据（配置备份文件等）在卷 minio_data；VictoriaMetrics 数据在卷 vm_data（丢失=丢历史指标，不影响台账）。

## 5. 网络代理（访问 GitHub）

直连 github.com 超时，仓库已配置 `git config http.proxy http://127.0.0.1:7897`（本机 Clash 类代理端口）。代理端口变更：`git config --unset http.proxy` 后重设。

## 6. 常见故障

| 症状 | 处置 |
|---|---|
| web 8090 打不开 | `docker ps` 看 nops-web；`docker logs nops-web`；多为 build 失败 |
| 登录 500 | `docker logs nops-api` 查 traceback；常见为 .env 缺 DJANGO_SECRET_KEY |
| 前端改了没生效 | 浏览器 Ctrl+F5（index.html 已 no-cache，旧标签页仍是旧 JS） |
| 建机房/地区 400 空 detail | 已修复（异常处理器会带字段名）；若复现查 common/exception_handler.py 是否被改 |
| 删除位置节点提示“存在引用” | 正常保护：先删/移走其下设备与机柜 |
| PG 连接池耗尽 | api 副本数×worker 并发过大，调 gunicorn -w 或 celery -c |
| 容器时间不对影响告警时间 | 平台内部全 UTC 存储，检查 `docker exec nops-api date` |
