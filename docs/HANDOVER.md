# 交接文档（面向下一个开发智能体）

> 最后更新：2026-09-03（资产生命周期+保修到期提醒上线 M2026-09-03d）。
> 一期+二期已完成并实测通过；三期「自动化运维」（M2026-09-02）、「轻量事件单」（M2026-09-02b）、「轻量变更单」（M2026-09-02c）、「CMDB 基础补齐 R1/R2/R3」（M2026-09-03/03b/03c）、「资产生命周期」（M2026-09-03d）已上线，见文末里程碑。
> 读完本文 + DEPLOY.md + DEVELOPMENT.md 即可接手。

## 1. 当前状态总览

**一期已完成并实测通过**（对应 PRD 第 9 章路线图）：

| 模块 | 状态 | 说明 |
|---|---|---|
| system | ✅ 完成 | RBAC+数据权限、凭据保险箱(AES-GCM)、通知渠道(飞书webhook)、审计、ApiToken |
| dcim | ✅ 完成 | 地区->机房->机柜树、机柜 U 位可视化(elevation API)、线缆表、**机房平面图 DIY 编辑器** |
| cmdb | ✅ 完成（R1-R3 + 资产生命周期） | 动态模型(attrs JSONB)、设备台账、Excel 导入导出、360° 视图、拖拽上架/换位/下架；**R1：质量看板/回收站/附件/维保/变更历史/动态分组/软件一致性；R2：设备运营页+360技术概览；R3：ACL/IPSec TechSnapshot 建模；5.5.7：生命周期流转(自动留事件)+资产事件+保修到期提醒** |
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
| **verify_cmdb_r2.py** | **CMDB R2：tech 概览端点区块/扩展入口 / 动态分组仅预览不改成员 / 软件版本聚合与 hw_model 过滤** | **9 PASS（sqlite 与容器 PG 各一遍）** |
| **verify_cmdb_r3.py** | **CMDB R3：TechSnapshot 越权/参数校验/写入/最新覆盖/tech 透出/占位回落/只读可见** | **7 PASS（sqlite 与容器 PG 各一遍）** |
| **verify_lifecycle.py** | **资产生命周期：流转留事件/同状态与非法 400/资产事件读写/越权/保修汇总口径与清单(临期±1天容差)** | **12 PASS（sqlite 与容器 PG 各一遍）** |
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

---

## 12. 里程碑 M2026-09-03b：CMDB 基础补齐 R2（设备运营页 + 360 技术概览）

**范围**：台账运营层界面化 + 把已有采集数据在 360 串成"技术概览"，并给出 OSPF/IPsec/ACL 扩展入口（建模留给采集驱动落地）。

**后端**（apps/cmdb）：
- `GET /cmdb/devices/{id}/tech/` 技术概览端点：OSPF/BGP 邻居(cmdb_routingneighbor)、最新路由快照(route_meta+前 500 条)、接口聚合 VLAN 集合、无线 AP 信息(ap_info)、登录会话(usage_loginevent raw SQL，跨应用不 import)、`extensions.acl/ipsec`（supported=false + 待接入说明，R3 建模锚点）。
- 设备列表 filterset 补 `hw_model` 等值过滤（软件一致性页按型号取明细用）。

**前端**：
- 新页面 `frontend/src/pages/Cmtools.vue`（路由 `/cmdb-tools`，侧栏"设备运营" Collection 图标，置于设备台账后），双 Tab：
  - **设备分组**：左分组列表（静态/动态 + 规则文本），动态分组规则可视化构建（品牌/地区/设备类型 code）→ 预览命中数（evaluate 不 apply，不改成员）→ 保存并应用（PATCH filter + apply 回写 members）；静态分组支持挑选/移除设备成员（devices m2m 全量回写）。
  - **软件版本一致性**：型号×版本分布聚合表（每行版本 chips × 数量 + 多版本告警标记），点行展开该品牌+型号全部设备明细（按版本排序、多数版本高亮为参考线）。
- `Device360.vue` 追加「技术概览」卡：VLAN chips / 路由快照前 120 条只读 / 邻居表 / AP 描述块 / 登录会话表，各区块空态用 el-empty；底部 extensions 用 el-alert 展示 ACL/IPSec 待接入说明。

**验证**：`scripts/verify_cmdb_r2.py` 9 PASS（sqlite 与容器 PG 各一遍，含只读 viewer_pg 可读、动态分组预览不改成员、hw_model 过滤覆盖分布合计）；`verify_cmdb_r1.py` 33 PASS 复跑不回归；`/cmdb-tools` 页面 200、容器 healthy。

**待办/坑**：① ACL/IPSec 仅入口设计，采集建模待设备驱动落地（见 objective ④，建议 R3 建 TechSnapshot 通用表 + fortigate/asa driver 采集 vpn/access-list 状态）；② 路由快照内容多时 360 仅展示前 120 条 JSON 文本，未做 prefix 表格/差分高亮（接 NCM 路由快照视图后替换）；③ 动态分组规则字段仍 3 个，condition 扩展在 evaluate 服务里集中维护；④ 会话 Tab 数据来自 usage_loginevent，量大的表建议按月分区（ER D12 已列技术债）。

---

## 13. 里程碑 M2026-09-03c：ACL/IPSec 等扩展概览建模（objective ④ 收口）

**范围**：把 360 技术概览里"未接入"的 ACL/IPSec 占位变成**真实建模**——通用技术快照表 + 采集驱动写入路径 + 概览透出，设备驱动解析落地后即可无感展示。

**后端**：
- 新模型 `TechSnapshot`（迁移 cmdb.0002，表 `cmdb_techsnapshot`）：device_id + kind(acl/ipsec，choices 可扩) + payload jsonb + created_at；`Meta.ordering=-id` + `(device_id, kind)` 索引；**读取语义=最新一条覆盖**（采集驱动每次写新行）。
- 写入 API：`POST /cmdb/devices/{id}/tech-snapshot/` body `{kind, payload:{...}}`（execute 权限；kind 白名单；payload 必须对象且 ≤200KB），供 fortigate/asa 等驱动解析设备输出后调用。
- `GET .../tech/` extensions 逻辑升级：kind 有快照 → `{supported:true, updated_at, payload}`；无 → 占位 `{supported:false, note}`（note 指引写入口）。OSPF 邻居/BGP 走既有 cmdb_routingneighbor，不重复建模。
- 前端 `Device360.vue` 扩展卡：supported 显示"已采集"标签 + 快照时间 + payload 只读预览（1600 字符内）；未接入显示空态说明。

**验证**：`scripts/verify_cmdb_r3.py` 7 PASS（sqlite 与容器 PG 各一遍）：只读 403 / 非法 kind 400 / payload 非对象 400 / 写快照 201 / tech 透出**最新**快照 / 未写前占位回落 / 只读可见。`/cmdb-tools` 页面 200。

**待办/坑**：① payload 结构规范由各采集驱动自定（表结构刻意通用）；建议 fortigate 驱动输出 `{tunnels:[{name,peer,status,bytes_in/out,up_since}]}`、asa `{acls:[{id,name,action,protocol,src,dst,hits}]}` 供前端将来做表格化；② 快照无限增长——后续按 kind+device 只保留 N 天/条（清理由 celery 周期任务做）；③ 本表未与 NCM/告警联动（如隧道 down 转告警属四期/运营项）。

---

## 14. 里程碑 M2026-09-03d：资产生命周期 + 保修到期提醒（PRD 5.5.7 P1）

**范围**：资产全生命周期状态机（规划→采购中→到货入库→上架运行→维修中→备件库→报废，字段早已具备）+ 每次流转留资产事件流水 + 保修到期 30/60/90/180 天与已过期提醒；不引入审批流（延续用户"审批类延后"口径）。

**后端**（apps/cmdb，无新表——DeviceAssetEvent / Device.warranty_until 均在）：
- `POST /cmdb/devices/{id}/lifecycle/`：body `{lifecycle_status, counterparty?, event_type?}`；校验目标合法且≠当前；自动写 DeviceAssetEvent（目标→事件映射 purchasing→purchase / in_stock / deploy / repair / spare / retire）+ auditlog update（before/after 状态）。门禁 cmdb.device.edit。
- `GET|POST /cmdb/devices/{id}/asset-events/`：事件流水（operator 由 auth_user 反查，detail 展示 note 等）；POST 写事件（event_type 白名单，occurred_at 默认当前）。门禁 edit。
- `GET /cmdb/devices/warranty-expiring/?within_days=`：summary {30/60/90/180, expired} + rows（临期升序 + 已过期降序，days_left 可为负，含位置/责任人）。
- 设备 filterset 已支持 hw_model 等（R2 提供）。

**前端**：
- `Device360.vue` 新增「资产生命周期」卡：当前状态中文标签 + 保修到期剩余天数（<0 红 / ≤90 黄 / 其余绿）、状态下拉流转（禁用同状态）→记录流转即留事件；事件流水表（时间/类型标签/操作人/对方单号/备注）+「新增资产事件」弹窗。
- `Cmtools.vue` 新增「保修到期」Tab：30/60/90/180/已过期计数 chips + 清单（设备名可点进 360、剩余天数红黄绿标签、责任人）。

**验证**：`scripts/verify_lifecycle.py` 12 PASS（sqlite op_low 与容器 PG viewer_pg 各一遍）：只读 403×2、流转 200 且自动事件含 from/to 与操作人、同状态 400、非法状态 400、手工借出事件+备注回读、保修汇总口径(60 含临期 35 天 & 已过期计数)、清单 days_left（容器 UTC 差一天用 ±1 容差）、清理测试设备。`/cmdb-tools` 页面 200。

**待办/坑**：① 保修提醒目前仅界面清单，无定时推送（如需飞书/邮件提醒，用 NotifyChannel 发提醒任务挂 celery beat，PRD 期望 30/60/90 提前提醒）；② 生命周期流转未做强制顺序（可直接 deployed→retired，P1 可接受，重流程可加过渡校验）；③ 资产事件 detail 前端仅展示 note，结构化字段（金额/单号/合同）由后续采购模块扩展；④ borrow/return 与 usage 模块占用/释放未联动（5.17 使用与共享域，独立交付）。

---

## 15. 里程碑 M2026-09-03e：菜单 IA 角色域重组（规划文档 + 侧栏分组）

- **问题**：14 个路由平铺单级菜单，无角色归属；用户提出按 网络/系统/机房运维/审计/监控/安全/桌面 管理员 7 类角色拆分。
- **产出**：`docs/IA-MENU.md`——角色×关注点矩阵（含数据来源→现状→规划/依赖）、补充角色（领导大屏/值班NOC/资产采购/存储备份/无线/流程合规）、菜单树（本次落地+规划占位）、RBAC 动态菜单三步路线、阶段 2/3 开发建议。
- **落地**：`frontend/src/layout.vue` 改为域分组二级菜单——总览；监控与告警（告警/事件单/巡检）；网络（IPAM/拓扑/NCM）；资产与机房（设备台账/设备运营/机房管理）；流程与自动化（自动化/变更）；安全与合规（规划位占位）；日志中心；系统管理。规划位一律 disabled 占位，避免空页假入口。
- 无后端改动；`npm run build` 通过；web 容器重建后生效。
- **后续**：动态菜单 = /auth/me perms → layout 过滤（先按菜单项-权限码映射，后授权树界面），对应 docs/IA-MENU.md §4。

---

## 16. 里程碑 M2026-09-04a：操作审计独立页（安全与合规分组首个真入口）

- **背景**：审计日志此前仅藏在系统管理 Tab（列表无 diff）；菜单 IA（§15）把「安全与合规」设为审计员分组。
- **后端**（apps/system/views.py）：AuditLogViewSet 增 `AuditLogFilter`（django_filters）：action/resource_type/user/source_ip 等值 + `created_at_after/before` 日期区间；`search_fields` 支持 resource_type/resource_id/source_ip 模糊。
- **前端**：新页 `frontend/src/pages/Audit.vue`（路由 `/audit`，菜单 安全与合规→操作审计）：动作筛选 + 关键字 + 日期区间；行内"变更摘要"（create/delete/execute/字段数+字段名）；点击行弹详情：对象/人/IP/时间 + **变更前后 diff 表**（before 红 / after 绿，字段级，嵌套 JSON 展示）。审计数据只读。
- **验证**：sqlite 263 条 / PG 541 条审计均真实可查：list/action+resource_type 过滤/search=Device/日期区间/未来空区间全 200；`/audit` 页面 200。
- **待办**：登录审计视图（usage LoginEvent 已建表未做 UI）、按用户/操作人下拉过滤、审计导出 CSV（阶段 2）。

---

## 17. 里程碑 M2026-09-04b：网络总览页（跨设备汇总，路由/邻居/链路/无线/VLAN + 扩展位）

- **范围**：IA 路线第 2 步——把分散在 360 的采集数据提为**跨设备汇总视图**；无新表，复用 cmdb_routingneighbor / RouteTableSnapshot / DeviceInterface(+Stat) / WirelessApInfo；预留 NAT/ACL/质量时序等扩展位，满足"后续随时拓展与迁移"。
- **后端**：`GET /cmdb/devices/network-overview/`（可选 region_id/site_id 过滤），返回分区：
  `meta{devices_covered, extensible}` / `neighbors{rows,by_state}`（up/full/down 统计）/ `routes`（每设备最新快照 + 前缀总数 + 新鲜度）/ `links{summary{checked,down,high_error}, rows}`（下行或高错包接口，带错包率与光功率）/ `ap` / `vlans`（native+tagged 使用分布 top50）/ `extensions`（nat/acl/quality_history/wireless_deep 说明位：接入即展示，无需改前端分区）。
  行内 device 名/IP/区域/站点由 Device 一次性映射（避免 N+1）。
- **前端**：`frontend/src/pages/Network.vue`（路由 `/network`，菜单 网络→网络总览）：顶部 4 统计卡 + 邻居表（状态标签、click 进 360）+ 路由快照表（新鲜度/过期警告）+ 链路状态表（下行/高错包、错包率、光功率收/发）+ AP 表 + 扩展采集位说明；全空态文案指引采集入口。
- **验证**：`scripts/verify_cmdb_net.py` 11 PASS ×2（sqlite op_low / 容器 PG viewer_pg）：分区齐全、行字段结构、链路 summary 口径、扩展位 4 项、区域过滤（不存在区域→覆盖 0 仍 200）、只读可读；`/network` 页面 200。
- **设计点（可迁移性）**：新增采集品类只往 `extensions`/新分区追加字段，前端按 key 渲染；`region_id/site_id` 为统一租户级过滤入口，后续跨区域报表可复用。

---

## 18. 里程碑 M2026-09-04c：RBAC 动态菜单（IA 路线第 3 步收口）

- **目标**：登录用户只看到自己有权限的菜单域/页面，替代静态全量侧栏。
- **后端**：`/auth/me` 已带 `perm_codes`（common.permissions.user_perm_codes，超管返回全量 37 项）；本轮零后端改动。
- **前端**（`frontend/src/layout.vue` 重构为配置驱动）：
  - `MENU` 常量登记「菜单项 ↔ 门禁权限码」（any-of；`dcim.*`/前缀匹配 `.view`；工作台恒显；空权限兜底全显——接口仍受 RbacPermission 保护）；
  - 分组在其子项全部无权时整组隐藏；菜单按 `/auth/me` 后异步渲染；
  - 「系统管理」由通配 system.* 收紧为显式列表（user/role/permission/dept/config/credential/notify/apitoken 的 view），避免审计码误放行；
  - 移除占位规划项（规划见 IA-MENU，避免噪音）。
- **权限码口径来自各 viewset 的 required_perm**：ipam/topo/ncm/network/devices 等共用 cmdb.device.view；告警 alert.rule/event；事件单 change.incident；巡检 inspect；自动化 automate.script/run；变更 change.ticket；审计 system.audit；日志 monitor.log；dcim 按 dcim.*。
- **演示账号**：新增角色“审计员”+用户 `auditor/NopsTest@2025`（仅 system.audit.view）——sqlite 与容器 PG 均已种入，登录后菜单仅「工作台 + 操作审计」。
- **验证**：本地与容器 `/auth/me` perm_codes 断言（auditor=['system.audit.view']）；admin 37 码全量可见；只读 op_low 21 码保持原可见集合（其角色带全域 view，属预期）；页面 200。
- **待办/坑**：① 角色普遍过宽导致过滤差异小——建议按域建角色（网络/系统/机房/安全/审计/桌面），并把 init_nops_data 的宽正则 grants 收紧到目录级；② 菜单授权界面（拖树）未做；③ 直链 URL（如 /system）不受菜单过滤保护——仅影响导航可见性，数据安全仍靠后端 required_perm。

---

## 19. 里程碑 M2026-09-05：导航权限点 menu.* + 角色化演示账号（RBAC 细化）

- **问题**：前端菜单此前按"功能权限码"过滤——ipam/拓扑/NCM/网络总览/设备台账共用 `cmdb.device.view`，导致角色间菜单几乎全同，无法体现 IA 域划分。
- **方案**：新增一类**导航权限点 `menu.*`（view 级，非功能门禁）**，前端菜单只按导航码过滤；功能码继续由后端 required_perm 拦截。menu.* 共 9 项：home/monitor/net/asset/dcim/workflow/security/log/sysadmin。
- **角色种子**（init_nops_data，幂等；每次运行重置演示账号密码=角色）：
  - 新增内置角色：`net_admin` 网络管理员 / `sys_admin` 系统运维 / `dcim_admin` 机房运维 / `auditor` 审计员（升级原演示角色）；
  - 演示账号（密码均 `NopsTest@2025`）：`net_demo`/`sys_demo`/`dcim_demo`/`auditor`；
  - 旧角色自动兼容：admin 全量 46 码；net_ops 补 menu.* 前缀（保留原功能码正则）；readonly（op_low 等）经 action=view 自动含全部导航码。
- **可见菜单差异（实测，sqlite 与容器 PG 一致）**：
  - net_demo：监控+网络+资产+流程（无日志/审计/系统管理）
  - sys_demo：监控+资产+流程+日志（**不见网络组**）
  - dcim_demo：仅 工作台+资产与机房
  - auditor：仅 工作台+操作审计
  - admin/op_low：全量
- **验证**：五账号 `/auth/me` perm_codes 断言；net_demo 直连 network-overview 200（看得见进得去）；页面 200。
- **待办/坑**：① 导航码与功能码分离属"展示层 RBAC"——直链仍可达无导航权的页面（数据安全由后端兜底，符合 IA 说明）；② 授权界面（角色-菜单拖树）仍远期；③ init 需在新增页面时同步 menu.* 与前端 MENU 常量（单点维护：layout MENU ↔ init menu.* ↔ viewset required_perm 三处对齐）。

---

## 20. 里程碑 M2026-09-06：采集解析驱动 tech-parse（ACL/NAT/IPSec 真数据填充）

- **范围**：把网络总览/设备 360 里的 NAT/ACL/IPSec"扩展位"变成**可落真数据的采集路径**——延续 AP 同步的"粘贴设备输出→解析落库"模式，未来接 SSH 驱动直接复用同一 payload 结构（纯函数解析器可离线单测）。
- **后端**：
  - 新模块 `apps/cmdb/collectors.py`：`parse_acl`（Cisco ASA/FTD show access-list，含 permit/deny/hitcnt/spec）、`parse_nat`（FortiOS show firewall vip → VIP 块 extip/mappedip/extintf）、`parse_ipsec`（FortiOS get vpn ipsec tunnel status → name/id/proto/peer/local/status）；无法识别抛 ValueError（附示例提示）。
  - TechSnapshot.Kind 增加 `nat`（迁移 cmdb.0003，仅 choices）；`GET tech` 扩展透出 acl/nat/ipsec。
  - 新动作 `POST /cmdb/devices/{id}/tech-parse/`：body {kind, text, save?}——预览仅需视图权限；`save=true` 需 execute 权限并写 audit（execute 留痕），落库后 tech 与 network-overview 立即透出。
  - `network-overview` 扩展位升级：按设备取 acl/nat/ipsec 最新快照聚合 `{collected, devices, total, latest_at}`，quality_history/wireless_deep 仍为未接入说明。
- **前端**：Device360 技术概览卡头加「粘贴输出解析」按钮（品类+输出+解析预览 summary/rows→保存为快照，保存后刷新）；网络总览扩展位卡：已采集→绿标「N 台 / M 条 + 最新时间」，未接入→灰标说明。
- **验证**：`scripts/verify_techparse.py` 13 PASS ×2（sqlite op_low / 容器 PG viewer_pg）：预览不落库、垃圾输入 400+hint、只读可预览但保存 403、三类落库与 tech 透出、总览聚合 collected/devices/total、只读可见、purge 后孤儿快照不计入回落未采集（acl 可能含 R3 遗留数据故只断言 nat/ipsec）。
- **待办/坑**：① 解析器覆盖的是"典型输出"，真实设备页头/版本差异需在驱动阶段补样例回归；② 快照清理（按 kind+device 保留 N 条）尚未做；③ SSH 自动采集驱动（Netmiko 或跳板执行 + 周期任务）为后续目标，tech-parse 即其共享落库通道。

---

## 21. 里程碑 M2026-09-07：TechSnapshot 保留策略（周期清理 + 按需执行）

- **范围**：限制 cmdb_techsnapshot 无限增长——按 (device_id, kind) 只保留最近 N 条。
- **服务**：`apps/cmdb/retention.py::cleanup_techsnapshots(keep=5)`——倒序分组计数，批量删除超龄记录，返回 {kept_groups, removed, keep, retained}；**模型在函数内惰性导入**（celery autodiscover 阶段 django 未 ready，顶层 import 会让任务静默注册失败——本轮踩坑并修复）。
- **任务**：`apps/cmdb/tasks.py::cmdb.cleanup_techsnapshots`，beat 新增 `cmdb-techsnapshot-retention`（每日 04:30，crontab）。
- **按需接口**：`POST /cmdb/devices/tech-retention/` body {keep?}——execute 权限；非超管需 confirm=1；执行写 audit（execute 留痕）。
- **验证**：`scripts/verify_retention.py` 9 PASS ×2（sqlite + 容器 PG）：7 条写库最新透出 → 无 confirm 400 → confirm 执行 removed=4 keep=3 → 最新仍 marker=6 → 幂等 removed=0 → 非法 keep 400 → purge 后全量清理正常；worker 日志确认任务注册（`. cmdb.cleanup_techsnapshots`）。
- **待办/坑**：保留条数当前全局 keep=5，未做按品类差异化（如 acl 保留更多）；清理仅覆盖 TechSnapshot，路由快照 RouteTableSnapshot 的保留策略同机制待接入（NCM 侧）。

---

## 22. 里程碑 M2026-09-08：业务-设备归属 + 形态/系统清单（系统管理员域视图）

- **范围**：IA 1.2 系统管理员域——业务矩阵（DeviceBusiness 表早已建、无 API）与形态/系统清单（复用设备字段聚合，无新表）。
- **后端**（apps/cmdb/views.py）：
  - 设备列表扩展过滤：`business_id`（跨 DeviceBusiness）/ `is_virtual=1|0` / `model_category`；
  - `GET /cmdb/devices/business-summary/`：业务列表（等级/设备数/覆盖区域站点）+ linked/unassigned 统计；
  - `POST /cmdb/devices/business-assign/`：{business_id, device_ids, action: add|remove}（edit 权限 + audit update）；
  - `GET /cmdb/devices/system-summary/`：形态(物理/虚拟)/型号类别/厂商/系统版本/用途 计数分布。
- **前端**：新页 `Bizsys.vue`（路由 `/bizsys`，资产与机房→「业务与系统清单」，nav=menu.asset）：
  - Tab 业务设备归属：业务列表（点击高亮）→ 成员设备表（可移除）→「添加设备」多选弹窗；顶部未归属计数提醒；
  - Tab 形态与系统清单：形态/型号类别/OS 版本/厂商/用途分布，点 OS 行或按 形态/类别/关键字 过滤设备明细（行进 360）。
- **验证**：`scripts/verify_bizsys.py` 12 PASS ×2（sqlite op_low / 容器 PG viewer_pg）：矩阵结构、临时业务建-归属-add-过滤-汇总-remove-清理全链路、只读归属维护 403、is_virtual 过滤数与汇总一致、清理无残留。
- **待办/坑**：① Business CRUD 已有（BaseModelViewSet，cmdb.device 门禁）但无独立菜单（页面入口内嵌本页+设备台账）；② system-summary 未含 attrs 动态字段（硬件配置/内核细项在 attrs，需按模型模板聚合）；③ 应用服务/备份状态仍需采集（IA 1.2 远期）。

---

## 23. 里程碑 M2026-09-09：设备借还台账（占用/释放联动，IA 5.17）

- **范围**：把设备"借出/归还"做成闭环台账——借出即占用（usage_status=occupied）、归还释放为 idle；逾期（≥30 天）可审计；借还即资产事件留痕。桌面/机房/审计角色的公共底座。
- **后端**（apps/cmdb/views.py）：
  - `GET /cmdb/devices/loan-summary/`：按设备最近事件推断在借集合（设备仅统计未删除、孤儿不计入）+ 最近 40 条借还动态 + stats{borrowed, overdue}；
  - `POST /cmdb/devices/{id}/usage-claim/`：{claim: borrow|return, counterparty?, occurred_at?, note?}——借出需 counterparty（重复借出 400）、置 occupied 并建 borrow 事件；归还仅 occupied 可归（提前归 400）、置 idle 并建 return 事件；均写 audit(update)。
- **前端**：Cmtools「设备运营」新增 Tab「设备借还」：在借清单（天数/逾期标红/点行进 360/归还按钮）+ 借出弹窗（仅列出 idle 设备）+ 最近借还动态表。
- **验证**：`scripts/verify_loans.py` 13 PASS ×2（sqlite op_low / 容器 PG viewer_pg）：只读 403、缺对方 400、历史时间借出→台账在借 days≥40 overdue≥1、重复借出/提前归还 400、归还释放 idle、借还事件双留痕、purge 孤儿不计入。
- **待办/坑**：① overdue 阈值目前常量 30（未做成参数/按设备类型差异）；② 借出仅走 usage-claim（旧"手工事件"路径不改 usage_status，可能产生账外状态——后续建议收敛到 usage-claim 单一入口）；③ 归还时 counterparty/实还日期归还凭证尚未建模（预留 note）。

---

## 24. 里程碑 M2026-09-10：机房作业工单（dcim 域，IA 机房运维）

- **范围**：机房上下架/迁移/检修/布线作业闭环——计划→开工→完成/取消，关联机柜与设备、登记目标 U 位、执行人与结果留痕。
- **模型**：`apps/dcim/models.py::DcimTicket`（迁移 dcim.0003）——kind(rack_in/rack_out/move/repair/cable，choices 含中文 label)、rack FK、device_id(跨 app 裸外键)+device_name 快照、u_from/u_to、status(planned/doing/done/cancelled)、assignee、planned_at/finished_at、note/result、operator_id。
- **API**：`/dcim/op-tickets/` CRUD（读=dcim.rack.view，写经显式 `_need_perm(dcim.rack.edit)`——坑：RbacPermission 只控读，create/update/destroy 均需在 perform_* 显式门禁，本里程碑补齐）+ 动作 `start`(仅 planned)/`finish`(填 result+finished_at)/`cancel`(填 reason)，终态保护。
- **前端**：`DcimOps.vue`（资产与机房→「机房作业工单」，nav=menu.dcim）：状态过滤、新建/编辑弹窗（类型/机柜/关联设备/目标 U 位/执行人/计划时间）、开工/完成(结果)/取消流转。
- **验证**：`scripts/verify_dcimops.py` 12 PASS ×2（sqlite op_low / 容器 PG viewer_pg）：只读建单 403、建单/过滤/开工/重复开工 400/完成+结果落库/终态不可取消/取消流转/编辑/清理。
- **待办/坑**：① U 位为"计划目标值"，设备实际机柜位置变更仍走设备编辑——双入口可能存在不一致（后续可做"完成时按 U 位校验冲突并一键落位"）；② 无独立菜单权限点（复用 menu.dcim + dcim.rack.*，符合角色既有授权）；③ 工单未接 change 审批流（作业类工单当前无需审批，符合轻量定位）。

---

## 25. 里程碑 M2026-09-11：审计概览 + CSV 导出（审计员域增强）

- **范围**：审计页从"裸日志流水"升级为审计员工作台——近 24h 总量/动作/对象/人 TOP、近 7 日趋势、一键导出当前筛选。
- **后端**（apps/system/views.py::AuditLogViewSet，均 system.audit.view）：
  - `GET /system/audit-logs/summary/?hours=n`：近 N 小时总览 + 动作/对象类型/操作人 TOP6 + 近 7 日按日计数；
  - `GET /system/audit-logs/export/`：当前筛选条件导出 CSV（≤5000 行；时间/操作人/动作/对象/来源 IP + 变更前后 JSON 两列，UTF-8 BOM）。
- **前端**：Audit.vue 顶部新增概览条——24h 总量 Tag + 近 7 日标签、动作/对象/操作人 TOP 小标签组、「导出当前筛选（CSV）」按钮（客户端 BOM CSV，最多 2000 行）。
- **验证**：`scripts/verify_audit.py` 6 PASS ×2（sqlite auditor / 容器 PG auditor）：auditor（仅 system.audit.view）可看 summary 与导出 CSV（表头/非空）、hours 生效、列表最新可读。
- **待办/坑**：① export 用 csv 模块直接流式写 resp（审计表字段无转义隐患），但筛选参数沿用 filterset 需与页面参数一致（created_at_after/before、search）；② 导出上限 5000（如需要全量导出需加分页参数）；③ by_user 无姓名前缀区分（用户名即人名体系内约定）。

---

## 26. 里程碑 M2026-09-12：链路质量时间序列（IA 网络管理员·链路质量）

- **范围**：链路质量从"当前快照"升级为时间序列——周期取样落库 → 聚合/降采样 → 趋势图；历史可审计、可回溯故障时段。
- **模型**：`apps.cmdb.LinkQualitySample`（迁移 cmdb.0004）——device_id/interface_id(裸外键)/iface_name 快照、sampled_at(索引)+ (device,sampled_at) 复合索引、in/out bps/pps、错误率、光功率收发。注意 Django 6 已移除 Meta `index_together` → 用 `indexes`（本轮踩坑）。
- **取样**：`apps/cmdb/linkquality.py::sample_link_quality(keep_days=7)`（函数内惰性导入模型）——读全部 DeviceInterfaceStat → bulk_create 快照 → 同轮删除 keep_days 前旧样本；celery 任务 `cmdb.sample_link_quality` 注册（worker 日志确认），beat 每 5 分钟；另有按需 POST 动作 `link-quality-sample`（execute + audit）。
- **概览 API**：`GET /cmdb/devices/link-quality-overview/?hours=n`（网络级聚合，前端无需设备 id）——按接口聚合并**降采样 36 桶**，输出 device/iface、样本数、均值/峰值、错包峰值、buckets[{ts,in,out,err}]。
- **前端**：Network 链路卡头部「质量趋势」按钮 → Drawer：每接口一行（设备·接口 + 样本/均值/峰值/错包元信息 + 36 桶下行带宽迷你柱状图，tooltip 含时间/上下行/错包）。
- **验证**：`scripts/verify_linkq.py` 7 PASS ×2（sqlite/容器 PG）：只读取样 403、取样执行计数、非法 keep_days 400、概览结构、桶单调且 ≤36、均值≤峰值（无统计源时优雅跳过）、只读可看、清理 keep_days=0。worker 日志确认任务注册。
- **待办/坑**：① 演示库当前无 DeviceInterfaceStat 源数据 → 无真实曲线（driver/采集写入 stat 后自动有）；② 每分钟 5 取样量级可控，若海量接口需按接口去重/分层采样；③ 概览 6000 行截断+36 桶为简化版，长周期(周/月)需落到小时/天聚合表。④ 前端为迷你柱状图（无图表库依赖），宽幅趋势另需引入 echarts。
