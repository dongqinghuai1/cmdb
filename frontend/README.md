# nops 前端（Vue3 + Element Plus）

构建与运行见 `../docs/DEPLOY.md`（Docker：nops-web :8090）。

```powershell
npm install --no-fund --no-audit   # esbuild postinstall 被 npm 策略拦时：npm approve-scripts esbuild && npm rebuild esbuild
npx vite build                     # 本地构建验证
npm run dev                        # 本地开发（:5173，/api 代理到 :8000）
```

## 页面与组件

| 文件 | 说明 |
|---|---|
| src/api.js | axios 封装：JWT 注入、401 跳登录、错误统一弹窗 |
| src/pages/Dcim.vue | 机房管理中枢：左侧地区->机房->机柜树；中部按选中节点切换 机房卡片/平面图/U位图；右侧待上架设备（拖拽源/下架落点） |
| src/components/FloorPlan.vue | 平面图 DIY 编辑器：米制坐标(SCALE=38px/m)、palette 放置、window 级 pointer 拖拽(增量式)、右下角缩放手柄、属性面板(名称/尺寸/绑定机柜)、bulk 整图保存、U 位横排概览；工具栏 BUILD 标记用于确认部署版本 |
| src/pages/Devices.vue | 台账：筛选/搜索/新增/编辑(换位置/下架)/Excel 导入导出/删除(?hard=1 物理删) |
| src/pages/Device360.vue | 设备 360°：全字段 + 接口表(流量/错包/光功率) |
| src/pages/Alerts.vue / Inspects.vue / System.vue | 告警闭环 / 巡检 / 凭据+渠道+用户+审计 |

## 经验教训（勿再踩）

- URL 一律用字符串拼接 `"/api/x/" + id + "/y/"`（模板串曾被静默损坏成 `$glm-5.3_common`）
- 自定义权限类/组件复用切换实体的坑见 `../docs/HANDOVER.md` 第 4 节
- 部署后页面异常先 Ctrl+F5（SPA 旧 JS），FloorPlan 工具栏 BUILD 标记可确认版本
