# 交接文档（面向下一个开发智能体）

> 最后更新：2026-09-03（CMDB 基础补齐 R1：数据质量/回收站/附件/维保/变更历史/动态分组/软件一致性）。
> 一期+二期已完成并实测通过；三期「自动化运维」（M2026-09-02）、「轻量事件单」（M2026-09-02b）、「轻量变更单」（M2026-09-02c）、「CMDB 基础补齐 R1」（M2026-09-03）已上线，见文末里程碑。
> 读完本文 + DEPLOY.md + DEVELOPMENT.md 即可接手。

## 1. 当前状态总览

**一期已完成并实测通过**（对应 PRD 第 9 章路线图）：

| 模块 | 状态 | 说明 |
|---|---|---|
| system | ✅ 完成 | RBAC+数据权限、凭据保险箱(AES-GCM)、通知渠道(飞书webhook)、审计、ApiToken |
| dcim | ✅ 完成 | 地区->机房->机柜树、机柜 U 位可视化(elevation API)、线缆表、**机房平面图 DIY 编辑器** |
| cmdb | ✅ 完成（R1 补齐） | 动态模型(attrs JSONB)、设备台账、Excel 导入导出、360° 视图、拖拽上架/换位/下架；**R1：数据质量看板、回收站(恢复/彻底删除)、附件上传下载、维保License、变更历史、动态分组evaluate、软件版本一致性** |
| monitor | ✅ 骨架 | 采集器注册、SNMP 采集引擎(pysnmp, IF-MIB)、VM 统一 label 写入、分片任务 collect_shard |
| usage | ✅ 完成 | 占用/预约(时间窗排他)、LoginEvent 表 |
| alert | ✅ 骨架 | 规则引擎(metric/state)、dedup_key 去重、飞书通知、ack/resolve 闭环 |
| inspect | ✅ 骨架 | 模板/检查项、执行任务、异常转告警(共用事件表) |
| automate | ✅ 三期首模块 | 脚本库 / 高危审批 / 批量执行(灰度批次) / 逐台明细（ER 4.12；Ansible/任务编排/固件升级 P2 待落地） |
| change | ✅ 三期第2/3交付 | **事件单**（报障->分派->处理->反馈->关闭 + SLA + 告警联动）+ **轻量变更单**（12.2-5：申请->审批->实施->验证->关闭/驳回/回滚，审批复用 automate.Approval；角色分离 applicant/implementer/verifier/approver）（ER 4.13） |
| 其余 | ⬜ 骨架 | ai / report：空壳 models + 空路由，模型定义见 ER 4.15/4.16 |

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

**二期**：syslog 接收+日志检索、NCM 配置备份/diff、拓扑(LLDP 自动发现+G6 画布)、AP 台账同步、告警收敛/静默、IPAM、飞书 SSO、Prometheus remote_write、路由快照采集（~~change_ticket 轻量变更单~~ ✅ 已于三期补齐，见 M2026-09-02c）
**三期**：~~自动化运维~~ ✅、~~轻量事件单~~ ✅、~~轻量变更单(二期欠账)~~ ✅；剩余：安全基线、资产生命周期+保修/借用、报表中心、线缆与 LLDP 比对、固件升级/值班、PDU 电源、虚机 vCenter 同步
**四期**：AI（LLM 网关已留 settings.LLM_*、NL2Query、根因分析、ChatOps 飞书机器人、RAG）
**技术债**：ai/report 骨架 app 补全；巡检只实现了 2 种检查类型（online 状态/接口错包阈值）；collect_shard 需要真实 SNMP 设备联调；audit_log/log_record/login_event 分区表转换（ER D12）；事件单超时仅时间线提醒（飞书/升级未接）

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
| **verify_incident.py** | **事件单：权限护栏 / 报障分派处理反馈关闭 / 时间线 / SLA overdue / 告警联动 / 审计留痕** | **28 PASS** |
| **verify_change.py** | **变更单：申请/提交校验 / 审批复用 Approval / 实施验证关闭 / 驳回 / 回滚 / 角色护栏 / 审计** | **28 PASS** |
| **verify_cmdb_r1.py** | **CMDB R1：质量看板 / 回收站 / 附件(本地卷存储) / 维保 / 变更历史 / 动态分组 / 软件一致性 / 只读负例** | **33 PASS（sqlite 与容器 PG 各一遍）** |
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
| 事件单状态机/动作 | apps/change/{models,services,views}.py（ER 4.13 incident；_can 参与人校验 + 状态机集合） |
| 变更单状态机/动作 | 同 apps/change（services 变更单段：submit/decide/start/verify/close/rollback + 角色分离） |
| 告警->事件单联动 | apps/alert/views.py AlertEventViewSet.create_incident -> change.services.create_from_alert |
| SLA 周期任务 | apps/change/tasks.py check_sla；celery 路由 `change.*→nops` |

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

---

## 9. 里程碑 M2026-09-02b：轻量事件单上线（三期第二模块）

**范围（PRD 11.1-14 / ER 4.13 incident）**：报障->分派->处理->反馈->关闭 + 时间线 + SLA 超时提醒 + **告警一键转单**联动；无 ITSM，轻量内置。

**后端** `backend/apps/change/`（迁移 0001 两张表，跨 App 裸 ID 引用，无外键）：
- `IncidentTicket`：ticket_no（INC-YYYYMMDD-NNN 自增）、title/source(manual|alert|inspect)/reporter_id/handler_id/priority(urgent|high|mid|low)/status(new|assigned|processing|feedback|closed)/related_alert_event_id/device_id/sla_deadline/closed_at/description/resolution
- `IncidentEvent`：ticket FK + event_type(comment|assign|status_change|sla_warning) + actor_id + content（时间线）
- `services.py` 状态机：`new→assigned→processing→feedback→closed`（仅 processing/feedback 可关闭）；assign 任意非 closed 可改派；comment 不限状态。细粒度权限 `_can`：报障人/处理人身份或 `change.incident.edit`
- **SLA**：priority→{urgent:2,high:4,mid:8,low:24}h 自动算 sla_deadline；beat 周期 `change.check_sla`（10min）对逾期未关闭且未提醒过的工单写一次 sla_warning 事件（幂等）；队列路由 `change.*→nops`
- **告警联动**：`/alerts/events/{id}/create-incident/`（alert 事件动作）→ `change.services.create_from_alert` 自动带 source=alert/device/标题前缀 `[告警]`；AlertEventViewSet 放开 POST 仅用于动作路由，create 显式 405 防伪造
- **权限点**（init_nops_data 幂等）：`change.incident.view/edit`；net_ops 已授 change.*
- **API**：`/api/v1/changes/incidents/`（list/retrieve 名称富化+overdue+事件时间线、报障 POST；动作 assign/start/feedback/close/comment；`my-stats/` 工作台计数；filter: status/priority/source/handler_id/overdue/search）
- **审计**：生命周期/评论走 write_audit（system_auditlog，resource_type=IncidentTicket）

**前端** `frontend/src/pages/Incidents.vue`：我的报障/待我处理/超时计数卡 + 列表（状态/优先级/来源/SLA 截止带超时标红）+ 报障弹窗（设备检索可选）+ 详情抽屉（描述/处理结果/状态流转按钮/时间线 timeline）。路由 `/incidents` + 侧栏"事件单"（Service 图标，夹在告警与巡检之间）；告警中心每条 firing/ack 告警新增「转事件单」按钮。

**验证**：`scripts/verify_incident.py` 28 PASS（本地 sqlite+eager：权限 403/越权、非法分派/空 resolution 400、全生命周期、时间线、overdue、告警联动、审计行数）；容器栈端到端复测：人工全流程 closed 4 事件 + 联动单 source=alert 关联设备与告警标题 + `celery -A config call change.check_sla` 触发后逾期单出现 sla_warning 时间线 ✅。

**待办/坑**：① change_ticket 轻量变更单（ER 4.13 另一半）未建，可复用 automate.Approval biz_type=change_ticket；② SLA 超时仅时间线提醒，飞书/值班升级未接；③ 事件单超时/分派无站内消息（notification 体系未接）；④ 巡检异常自动建单（source=inspect）入口未在巡检页做按钮（后端已支持 source 字段，可在 Inspects.vue 补）。

---

## 10. 里程碑 M2026-09-02c：轻量变更单上线（change 域完整交付）

**范围（PRD 12.2-5 / ER 4.13 change_ticket）**：申请->审批->实施->验证->关闭，支持驳回/回滚；**审批复用 automate.Approval（biz_type=change_ticket，同表打通脚本执行审批与变更审批）**；申请/实施/验证/审批四角色分离；不做重型 ITSM。

**后端**（apps/change，迁移 0002 一张表 `ChangeTicket`）：
- 字段对齐 ER：ticket_no（CHG-YYYYMMDD-NNN）、change_type(config/device/sw_upgrade/network)、risk_level(high/mid/low)、plan_start/end 变更窗口、actual_start/end、status、applicant/implementer/verifier/approver_id、approval_id、content jsonb(summary/impact/steps/affected_device_ids)、related_script_run_id/related_config_event_id、rollback_plan、result_desc
- 状态机：`draft→approving→approved→implementing→verifying→closed`；approving 驳→`rejected`；implementing/verifying 可→`rolledback`（回滚需实填方案）；每步审计（system_auditlog resource_type=ChangeTicket）
- 审批复用：submit 生成 automate.Approval 行（biz change_ticket + biz_id）；approve/reject 同步审批行状态/意见/decided_at；拒绝必须填原因
- 角色护栏：approve/reject 需审批人身份或 `change.ticket.approve`；start 需实施人/execute 权限；verify 需验证人身份或 execute 权限（**验证人≠实施人** 校验）；close/rollback 需实施/验证/申请人或 execute 权限
- 权限点（init_nops_data 幂等）：`change.ticket.view/edit/execute/approve`；net_ops 已授 change.*
- **API**：`/api/v1/changes/change-tickets/`（list/retrieve 名称+审批行+执行单快照富化；create 草稿；动作 submit/approve/reject/start/verify/close/rollback；filter status/risk/mine=applicant|implement|verify/search）

**前端** `frontend/src/pages/Changes.vue`：发起变更（草稿：标题/类型/风险/摘要/影响面/步骤）-> 列表（类型/风险/窗口/状态过滤、我的申请/实施/验证）-> 详情抽屉（审批状态与意见/变更内容/回滚预案/验证结果 + 按状态与当前用户身份出现 提交审批/通过/驳回/开始实施/提交验证/回滚/关闭）。路由 `/changes` + 侧栏"变更管理"（EditPen 图标，位于自动化运维后）。

**验证**：`scripts/verify_change.py` 28 PASS（本地 sqlite+eager：无权限/越权 403、窗口/角色/内容等 400 校验、审批复用落库、驳回留原因、回滚闭环、审计行数；含只读旁观者负例 viewer_x）；容器栈端到端复测：CHG 全流程 draft→…→closed 且 approval 行 approved/意见回显 ✅，`/changes` 页面 200。

**待办/坑**：① 变更窗口不自动联动 alert_silence（PRD 期望割接期间静默，未接）；② related_script_run_id 仅记录不打通"变更获批后自动发起执行"；③ related_config_event_id 需 NCM 变更事件表落地后才有真引用；④ 变更单无站内/飞书通知（notification 体系统一欠账）。

---

## 11. 里程碑 M2026-09-03：CMDB 基础补齐 R1（档案 + 台账工具层）

**范围**：把 PRD 5.5 已有表但缺 API/界面的"基础 CMDB"能力接齐——数据质量看板、回收站、附件、维保 License、变更历史、动态分组规则、软件版本一致性。审批/事件/变更等模块的深验按用户指示延后。

**后端**（apps/cmdb，无新表）：
- **数据质量**（5.5.6 P1）：`GET /cmdb/devices/data-quality/` 返回 7 类缺失指标汇总（无SN/责任人/保修/品牌/版本/未上架(非虚机)/无管理IP(非虚机)）+ 按 kind 拉缺失清单前 100（含位置/责任人）。
- **回收站**（5.5.2 P1）：`GET /cmdb/devices/?deleted=1` 列出软删行；`POST .../restore/` 恢复；`POST .../purge/?confirm=1` 彻底删除（仅 execute 权限/超管，审计 restore/purge）。
- **附件**（5.5.3 附件 Tab）：`/cmdb/attachments/` multipart 上传(≤25MB)、按 device_id 列表、`.../{id}/download/` 流式下载、删除；写操作分别门禁 cmdb.device.edit/execute。**存储为本地卷**：api 容器挂载命名卷 `nops-media:/app/media`（apps/cmdb/storage.py 相对 uuid 文件名，防穿越；MinIO 迁移预留，file_url 语义不变）。
- **维保 License**：`/cmdb/licenses/` CRUD（type/seats/expire/supplier/contract_no）；`LicenseSerializer.device_id` 用 PrimaryKeyRelatedField(source="device") 解决 FK 字段名入参问题。
- **变更历史**（5.5.3 Tab）：`GET /cmdb/devices/{id}/history/` 直读 system_auditlog（跨应用 raw SQL，含操作人/来源IP）；**顺带修复两处审计缺口**：Device 自定义 create/update 此前绕过 BaseModelViewSet 审计——现补写；`common.audit._mask` 对 date/datetime/Decimal 等不可 JSON 序列化值导致 PG(psycopg) 审计写入静默失败——新增 `_fix_jsonable` 递归归一（影响所有含日期字段资源的 update 审计，属公共 bug 修复）。
- **动态分组**：`POST /cmdb/groups/{id}/evaluate/` body `{filter?, apply?}` 按 model(code)/region_id/vendor 规则重算（与 member_ids 同语义），apply 时固化规则并回写 members。
- **软件版本一致性**（5.5.4 首步）：`GET /cmdb/devices/software-summary/` 型号×版本分布计数（vendor/hw_model/model__code/sw_version + c）。

**前端**：
- `Devices.vue` 头部新增「质量看板」（指标 chips + 按缺失类型切换清单）与「回收站」（列表 + 恢复/彻底删除，危险操作二次确认）两个对话框。
- `Device360.vue` 扩为五张卡：概览 + 接口 + **维保/合同**（新增/删除）+ **附件**（上传/下载/删除）+ **变更历史**（动作标签/操作人/来源IP）。
- 动态分组规则配置界面、软件一致性页、360「技术概览」（OSPF/IPsec/ACL/VLAN/路由快照等）属 R2，未在本次范围。

**验证**：`scripts/verify_cmdb_r1.py` 33 PASS——**本地 sqlite 与容器 PG 各一遍**（只读负例本地 op_low、容器 viewer_pg 新建只读角色账号）：A 质量指标/清单、B 软删-列出-恢复-再删-彻底删除+只读 403、C 维保 CRUD 门禁、D 附件上传/列表/下载一致/删除+只读 403、E 变更历史 update 流水与只读可读、F 动态分组预览-应用-成员一致/删除后 404、G 版本分布含新造带版本设备。容器端另验 `/changes`、`/devices/1` 页面 200 与 8 容器 healthy。

**待办/坑**：① 动态分组 evaluate 仅 3 种规则字段（model/region/vendor），后续扩展 usage_tag/lifecycle/online 等多条件；② 附件仍在 api 本地卷，未接 MinIO（nops-media 已挂载持久）；③ 历史 Tab 只展示时间/动作/人/IP，未做前后值 diff 展示（audit before/after 已可读，R2 可加）；④ 软件一致性仅统计口径，无"目标版本 + 落后清单"差集入口（R2）。
