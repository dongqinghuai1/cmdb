# 交接文档（面向下一个开发智能体）

> 最后更新：2026-09-02（automate 三期首模块上线）。
> 一期+二期已完成并实测通过；三期「自动化运维」首模块（脚本库/批量执行/灰度/审批）已上线，见文末里程碑 M2026-09-02。
> 读完本文 + DEPLOY.md + DEVELOPMENT.md 即可接手。

## 1. 当前状态总览

**一期已完成并实测通过**（对应 PRD 第 9 章路线图）：

| 模块 | 状态 | 说明 |
|---|---|---|
| system | ✅ 完成 | RBAC+数据权限、凭据保险箱(AES-GCM)、通知渠道(飞书webhook)、审计、ApiToken |
| dcim | ✅ 完成 | 地区->机房->机柜树、机柜 U 位可视化(elevation API)、线缆表、**机房平面图 DIY 编辑器** |
| cmdb | ✅ 完成 | 动态模型(attrs JSONB)、设备台账、Excel 导入导出、360° 视图、拖拽上架/换位/下架 |
| monitor | ✅ 骨架 | 采集器注册、SNMP 采集引擎(pysnmp, IF-MIB)、VM 统一 label 写入、分片任务 collect_shard |
| usage | ✅ 完成 | 占用/预约(时间窗排他)、LoginEvent 表 |
| alert | ✅ 骨架 | 规则引擎(metric/state)、dedup_key 去重、飞书通知、ack/resolve 闭环 |
| inspect | ✅ 骨架 | 模板/检查项、执行任务、异常转告警(共用事件表) |
| automate | ✅ 三期首模块 | 脚本库 / 高危审批 / 批量执行(灰度批次) / 逐台明细（ER 4.12；Ansible/任务编排/固件升级 P2 待落地） |
| 其余 | ⬜ 骨架 | change / ai / report：空壳 models + 空路由，模型定义见 ER 4.13/4.15/4.16 |

**前端**：登录/工作台/机房管理(树+平面图+U位)/设备台账+360/告警/巡检/系统管理，全部可用。

**部署**：docker compose 双组（infra/app），7 容器运行中，GitHub 仓库 dongqinghuai1/cmdb。

## 2. 关键决策（不要推翻，都有原因）

1. **指标全进 VictoriaMetrics**（PG 只存快照）：`device_id/if_name/driver_type` 统一 label（ER D10）
2. **动态属性 = attrs JSONB + ci_model_attr 定义**，查询约定见 ER D1（等值 `@>`、范围走 VM 两段式）
3. **U 位/占用/告警去重的约束在 `docker/constraints.sql`**（EXCLUDE/partial unique），migrate 后需手动执行一次
4. **跨 App 禁 import 模型**：裸 BigIntegerField + db_constraint=False，访问走对方 services.py
5. **软删除行会占外键/唯一索引**：位置节点删除时自动物理清除幽灵设备（dcim views `_purge_soft_devices`）；设备超管硬删 `DELETE ?hard=1`，查含软删行 `GET ?all=1`
6. **前端 nginx 对 index.html 强制 no-cache**（SPA 缓存旧 JS 的坑）
7. LLM 走公司自建 newapi（OpenAI 兼容），配置在 `backend/.env` 的 `LLM_BASE_URL/LLM_API_KEY`（**key 仍是占位符，未填**）

## 3. 待办清单（按 PRD 路线图）

**二期**：syslog 接收+日志检索、NCM 配置备份/diff、拓扑(LLDP 自动发现+G6 画布)、AP 台账同步、告警收敛/静默、IPAM、飞书 SSO、Prometheus remote_write、路由快照采集
**三期**：自动化运维(脚本库/批量执行/审批)、安全基线、资产生命周期、报表中心、轻量事件单、虚机 vCenter 同步
**四期**：AI（LLM 网关已留 settings.LLM_*、NL2Query、根因分析、ChatOps 飞书机器人、RAG）
**技术债**：7 个骨架 app 的 models 补全；巡检只实现了 2 种检查类型（online 状态/接口错包阈值）；collect_shard 需要真实 SNMP 设备联调；audit_log/log_record/login_event 分区表转换（ER D12）

## 4. 踩过的坑（血泪教训，务必避开）

| 坑 | 规则 |
|---|---|
| PowerShell 5 语义下 `Set-Content`/`Get-Content` 往返会按 GBK 毁掉 UTF-8 中文 | **源码文件一律用 write/edit 工具，不要用 pwsh 写代码** |
| 我生成的 JS 模板串 `${...}` 曾被静默替换成坏字面量 | 写完含模板串的代码后 grep 一遍 `$glm` 确认 |
| CSS 优先级：`.obj.rack{position:relative}` 压过 `.obj{position:absolute}` 导致机柜元素按文档流堆叠（查了 5 轮） | 改定位类样式时检查所有同名选择器优先级 |
| DRF 自定义 Permission 必须继承 BasePermission（否则 detail 接口 has_object_permission 500） | 新权限类一律继承 |
| Vue 组件复用（props 变化不重挂载）导致跨机房数据残留 | 切换实体的组件要 watch props id 重载 |
| Django 迁移删过字段后 makemigrations 需在容器内跑（本机无 psycopg） | `docker compose -f docker-compose.app.yml run --rm api python manage.py makemigrations` |
| 子 agent 委派两次零产出 | 复杂任务优先自己做；委派要给文件级规格 |
| GitHub 直连超时 | 仓库已配 `http.proxy=127.0.0.1:7897`（本机代理端口变了要改） |

## 5. 验证脚本清单（backend/scripts/）

| 脚本 | 用途 | 基线 |
|---|---|---|
| api_test.py | 核心 CRUD 全链路（幂等，自动清理） | 33 PASS（PG+constraints.sql 环境） |
| verify_errors.py | 错误场景/引用删除/增改删往返 | 22 PASS |
| verify_ghost.py | 软删除幽灵设备不阻塞位置删除 | 4 PASS |
| verify_edit.py | 设备位置编辑（换柜/冲突/下架） | 7 PASS |
| verify_collect.py | 真实采集链路(SNMP/ICMP) | 6 PASS |
| verify_ipam.py | IPAM 地址/VLAN 闭环 | PASS |
| verify_ncm.py | NCM 备份/基线 | 8 PASS |
| verify_syslog.py | Syslog 收流/检索/限流 | PASS |
| verify_silence_ap.py | 告警静默 + AP 台账同步 | 7 PASS |
| **verify_automate.py** | **自动化运维：脚本 CRUD / 高危审批闭环 / 灰度批次 / 取消 / 权限护栏** | **33 PASS** |
| smoke_test.py | 端口级冒烟（登录->建柜->上架->冲突） | 10 PASS |
| seed_demo.py | 演示数据：2 地区/2 机房/3 机柜/10 设备 | 幂等 |
| seed_floorplan.py | 上海机房平面图示例布局 | 幂等 |
| rebind_racks.py | 平面图机柜元素与实体机柜重绑（修 rack_id 丢失） | 按需 |
| init_nops_data（manage.py 命令） | 权限/角色/admin/设备类型/飞书渠道占位 | 仅首次 |

前端 E2E：`frontend/` 下曾用 playwright 写过拖拽/切换/下架验证（已删，按需重写；`npm i -D playwright && npx playwright install chromium`）。FloorPlan 工具栏有 BUILD 标记可用于确认前端版本。

## 6. 环境事实

- 本机 Windows，Python 3.14（**装不上 psycopg/pysnmp**，本机仅 SQLite 语法检查 `NOPS_DB=sqlite manage.py check`；容器内 Python 3.12 完整依赖）
- venv：`backend/.venv`；前端依赖：`frontend/node_modules`
- Docker 网络 `nops-net`（172.30.0.0/24，手动创建，宿主机地址池曾耗尽）
- 容器：nops-web(8090)/nops-api(8000)/nops-worker/nops-beat/nops-postgres(healthy)/nops-redis/nops-vm/nops-minio
- 数据库默认账号 nops/nops（.env 可改），平台 admin 初始密码 nops@2025

## 7. 快速定位（改哪里）

| 需求 | 文件 |
|---|---|
| 加设备类型 | 无需改码：POST /api/v1/cmdb/models/（或 init_nops_data 里加） |
| 加自定义属性 | 模型详情 attrs 接口；校验逻辑 apps/cmdb/services.py DeviceService |
| 加告警规则类型 | apps/alert/engine.py evaluate_alert_rules + models.AlertRule.RuleType |
| 加巡检检查项类型 | apps/inspect/tasks.py run_inspect 的 check_type 分支 |
| 平面图新元素类型 | frontend FloorPlan.vue 的 TYPES 数组 + .obj.<type> 样式 |
| 加菜单/页面 | frontend router.js + layout.vue + pages/ |
| 加周期任务 | 对应 app tasks.py 用 shared_task + config/celery.py register_beat |
| 加脚本库/执行规则 | apps/automate/{models,services,tasks,views}.py（ER 4.12） |

---

## 8. 里程碑 M2026-09-02：三期 automate 首模块上线

**范围（PRD 5.12 子集）**：命令/脚本库、批量执行（含**灰度：先 1 台→人工确认→继续剩余**）、高危脚本强制**审批流**（通用 Approval 表，预留 change_ticket 复用）、逐台执行明细与回显、操作全程审计。

**后端** `backend/apps/automate/`（迁移 0001 四张表）：
- `Script`（content AES-GCM 加密存 `EncryptedTextField`，`danger_level=high → requires_approval`）
- `Approval`（通用：biz_type script_run/change_ticket）
- `ScriptRun`（快照执行内容加密 + scope + gray_batch{enabled,total,dispatched}，状态机见 models docstring）
- `ScriptRunDetail`（output 先内联加密存 PG，偏差同 NCM 思路，MinIO 接入后迁 output_url）
- 状态机：`pending→running→success|failed|partial_success`；`approving→(批)pending/(驳)cancelled`；pending/approving 可取消
- **执行器**：`tasks.execute_run` 走 SSH 队列（config/celery.py `automate.*→ssh`），netmiko 直连（CLI/shell/python；Ansible 未接入，创建即拦截提示）
- **模拟开关**：系统配置 `automate.mock_execute={enabled:true}` 时执行走 mock（无真实设备演示/CI）；本地回归 `NOPS_EAGER=1` 让 celery 同步内联执行免 broker/worker
- **权限点**（init_nops_data 幂等）：`automate.script.view/edit`、`automate.run.view/execute`、`automate.approve`；net_ops 角色已授 automate.*
- **API**：`/api/v1/automate/scripts|script-runs|approvals`（script-runs 含 start/continue/cancel/details 动作；approvals 含 approve/reject；审批单对 approver/applicant 身份可见，细粒度在 decide_approval）

**前端** `frontend/src/pages/Automate.vue`：四个页签——脚本库（CRUD/启用/危险级标识）、发起执行（脚本+设备多选+灰度+高危选审批人）、执行历史（进度/摘要/灰度继续/取消/明细抽屉）、我的审批（通过/驳回）。路由 `/automate` + 侧栏"自动化运维"。

**验证**：`scripts/verify_automate.py` 33 PASS（幂等；含无权限 403/越权 404、审批人视角、驳回留痕、灰度 3 台分批）。本地命令：`NOPS_DB=sqlite NOPS_EAGER=1 manage.py runserver` + 预置 `mgr_approver/NopsTest@2025` 审批账号与 mock 开关。

**待办/坑**：① Ansible 执行器未接入；② Job 任务编排、固件升级作业计划（ER P2）未建表；③ api_test.py 在**sqlite**（无 constraints.sql EXCLUDE）下会遗留 T-DUP 幽灵设备导致末两步删 site/region 400，属环境差异，PG 容器正常（回归用容器跑）；④ 审批飞书卡片通知未接（占位 send_notification 体系）。
