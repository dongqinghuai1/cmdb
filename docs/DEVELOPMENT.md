# 开发规范与模块地图

## 1. 后端结构（backend/）

```
config/          Django 工程：settings(全环境变量化)/urls(/api/v1/) /celery(register_beat)
common/          crypto.py(AES-GCM字段) permissions.py(RBAC+数据权限scoped_queryset)
                 audit.py(审计+脱敏) exception_handler.py(错误拍平可读) models.py(软删除基类)
apps/system      用户/RBAC/凭据/通知/审计/Token —— BaseModelViewSet 在 apps/system/views.py
apps/dcim        Region/Site/Rack/RackReservation/Cable + SiteObject(平面图元素)
                 services.RackService: elevation视图/check_placement(跨表U位互斥)/capacity
apps/cmdb        CiModel/CiModelAttr/Device(15表) —— services.DeviceService: attrs校验/place/excel
apps/monitor     CollectorNode/LogRecord 等 + collector.py(SNMP引擎+VM写入) 
apps/alert       规则/事件(dedup_key去重) + engine.py(评估+通知)
apps/inspect     模板/任务/执行 + tasks.py run_inspect
apps/usage       DeviceUsage(占用)/LoginEvent
apps/<其余7个>    二期空壳（models 定义见 ER 文档对应章节）
```

### 硬性纪律（评审定案，勿破坏）

1. **跨 App 不 import 模型**：裸 `BigIntegerField(db_constraint=False)`，访问走对方 `services.py`。同域内真 FK + `on_delete=PROTECT`
2. **动态属性**：内置高频字段列存投影，自定义走 `attrs` JSONB；校验在 `DeviceService.validate_attrs`（含"与内置字段重名"拒绝）
3. **设备状态双轨**：`lifecycle_status`（资产阶段）≠ `usage_status`（占用即时态，仅 test/dev/shared 设备生效）
4. **软删除**：`deleted_at`；唯一索引均为 partial；超管 `?hard=1` 硬删、`?all=1` 查含软删
5. **新周期任务**：`shared_task` + `config/celery.py` 的 `register_beat`，不要集中硬编码
6. **时间全 UTC**（timestamptz），前端本地化
7. **写文件规则**：源码用 write/edit 工具（PowerShell 写中文会 GBK 损坏）；写完模板串 grep `$glm` 防静默替换

### API 约定

- 统一前缀 `/api/v1/<app>/`，DefaultRouter；认证 JWT（`/auth/login/`），权限 `required_perm = "<app>.<res>.<view>"`
- 错误响应 `{"code": N, "detail": "可读文本"}`；校验错误含字段名
- 分页 `?page=&page_size=`（默认 20，max 500）；筛选 django-filter（Device 支持 `rack__isnull=true` 查未上架）

## 2. 前端结构（frontend/src/）

```
api.js          axios 封装（JWT 注入/401跳转/错误弹窗）
router.js       路由 + 登录守卫
layout.vue      侧边菜单 + 顶栏
pages/
  Login/Dashboard/Dcim/Devices/Device360/Alerts/Inspects/System
components/
  FloorPlan.vue    机房平面图 DIY 编辑器（放置/拖动(pointer增量式)/缩放手柄/属性面板/
                   绑定机柜/整图bulk保存/U位横排概览；切换机房watch重载）
  RackElevation    （已被 Dcim 内联替代，保留树形导航组件角色）
```

- 组件内跳机柜：`Dcim.vue openRackFromPlan`；页面间设备详情 `/devices/:id`
- 平面图坐标系：**米制**，SCALE=38px/m；拖拽 clamp 到画布；保存走 `POST /dcim/site-objects/bulk/`（全删重建语义）
- 前端容器 nginx：`/api` 反代 nops-api:8000；index.html 强制 no-cache

## 3. 数据库约束（docker/constraints.sql，migrate 后执行）

U 位 EXCLUDE（device/rack_reservation 各自表内，跨表互斥在 RackService）、告警活跃事件 partial unique（dedup_key）、占用时间窗 tstzrange EXCLUDE、线缆方向 CHECK、trgm 全局搜索索引。**改这些表结构后需同步更新该文件并重放**。

## 4. 测试基线（改动后必须保持全绿）

```
api_test.py 33 | verify_errors.py 22 | verify_ghost.py 4 | verify_edit.py 7 | smoke_test.py 10
```

前端交互验证（拖拽/切换/下架）曾用 Playwright 脚本（临时写的已删，模式见 HANDOVER.md 第 5 节）。

## 5. 二期开发指引（按 PRD 第 9 章）

骨架 app 补模型时直接照抄 ER 文档 4.8-4.16 字段表；NCM 配置备份参考 Oxidized 思路（sha256 去重已定）；拓扑用 AntV G6（PRD 7.2）；syslog 接收建议独立 UDP 容器写 PG 分区表；AI 模块先做 LLM 网关（settings 已有 LLM_BASE_URL/LLM_API_KEY，OpenAI 兼容协议）。
