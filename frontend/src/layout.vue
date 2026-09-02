<template>
  <el-container style="height: 100vh">
    <el-aside width="232px" class="side">
      <div class="logo">nops · 运维平台</div>
      <el-menu :default-active="$route.path" router background-color="#001529" text-color="#b7c0cd"
               active-text-color="#fff">
        <template v-for="mi in visibleMenus" :key="mi.kind + (mi.path || mi.index)">
          <el-menu-item v-if="mi.kind === 'item'" :index="mi.path">
            <el-icon><component :is="iconOf(mi.icon)" /></el-icon>{{ mi.label }}
          </el-menu-item>
          <el-sub-menu v-else :index="mi.index">
            <template #title>
              <el-icon><component :is="iconOf(mi.icon)" /></el-icon>
              <span>{{ mi.label }}</span>
            </template>
            <el-menu-item v-for="ch in mi.children" :key="ch.path" :index="ch.path">{{ ch.label }}</el-menu-item>
          </el-sub-menu>
        </template>
      </el-menu>
      <div class="hint">菜单按登录账号的 menu.* 导航权限过滤（RBAC）。<br/>角色与域分组规划见 docs/IA-MENU.md</div>
    </el-aside>
    <el-container>
      <el-header class="top">
        <span class="crumb">{{ $route.meta.title || "" }}</span>
        <span style="margin-left:auto;display:flex;align-items:center;gap:14px;font-size:13px">
          <el-button link @click="logout">退出（{{ user.username }}）</el-button>
        </span>
      </el-header>
      <el-main style="background:#f0f2f5"><router-view /></el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { Bell, Connection, Lock, Monitor, OfficeBuilding, Promotion, Setting, Tickets } from "@element-plus/icons-vue";
import api from "./api";

// 菜单项 ↔ menu.* 导航权限码（RBAC 动态菜单）；分组在其子项全部无权时整组隐藏
const MENU = [
  { kind: "item", path: "/dashboard", label: "工作台", icon: "Monitor", codes: ["menu.home"] },
  {
    kind: "group", index: "g-monitor", icon: "Bell", label: "监控与告警 · 值班/监控管理员",
    children: [
      { path: "/alerts", label: "告警中心", codes: ["menu.monitor"] },
      { path: "/incidents", label: "事件单（值班台）", codes: ["menu.monitor"] },
      { path: "/inspects", label: "巡检中心", codes: ["menu.monitor"] },
    ],
  },
  {
    kind: "group", index: "g-net", icon: "Connection", label: "网络 · 网络管理员",
    children: [
      { path: "/ipam", label: "IP · VLAN · 地址", codes: ["menu.net"] },
      { path: "/topo", label: "网络拓扑", codes: ["menu.net"] },
      { path: "/ncm", label: "配置备份与 diff", codes: ["menu.net"] },
      { path: "/network", label: "网络总览（路由/链路/无线）", codes: ["menu.net"] },
    ],
  },
  {
    kind: "group", index: "g-asset", icon: "OfficeBuilding", label: "资产与机房 · 机房/桌面管理员",
    children: [
      { path: "/devices", label: "设备台账（360°）", codes: ["menu.asset"] },
      { path: "/cmdb-tools", label: "设备运营（质量/分组/软件/保修）", codes: ["menu.asset"] },
      { path: "/dcim", label: "机房与机柜（U 位/平面图）", codes: ["menu.dcim"] },
    ],
  },
  {
    kind: "group", index: "g-workflow", icon: "Promotion", label: "流程与自动化 · 变更/执行",
    children: [
      { path: "/automate", label: "自动化运维（脚本执行）", codes: ["menu.workflow"] },
      { path: "/changes", label: "变更管理（含网络割接）", codes: ["menu.workflow"] },
    ],
  },
  {
    kind: "group", index: "g-sec", icon: "Lock", label: "安全与合规 · 安全/审计员",
    children: [
      { path: "/audit", label: "操作审计（全站留痕+diff）", codes: ["menu.security"] },
    ],
  },
  { kind: "item", path: "/logs", label: "日志中心", icon: "Tickets", codes: ["menu.log"] },
  { kind: "item", path: "/system", label: "系统管理", icon: "Setting", codes: ["menu.sysadmin"] },
];
const ICONS = { Monitor, Bell, Connection, OfficeBuilding, Promotion, Lock, Tickets, Setting };
const iconOf = (n) => ICONS[n] || Monitor;

const user = ref({});
const perms = ref([]);
const hasNav = (need) => {
  const cs = perms.value;
  if (!need || !need.length) return true;
  if (!cs.length) return true; // 兜底：无权限信息时保持全显（接口仍受后端功能码拦截）
  return need.some((p) => cs.includes(p));
};
const visibleMenus = computed(() => {
  return MENU.map((mi) => {
    if (mi.kind === "item") return hasNav(mi.codes) ? mi : null;
    const kids = mi.children.filter((ch) => hasNav(ch.codes));
    return kids.length ? { ...mi, children: kids } : null;
  }).filter(Boolean);
});
onMounted(async () => {
  const me = await api.get("/auth/me/");
  user.value = me;
  perms.value = me.perm_codes || [];
});
const logout = () => {
  localStorage.removeItem("token");
  location.href = "/login";
};
</script>

<style scoped>
.side { background: #001529; display: flex; flex-direction: column; }
.logo { color: #fff; font-weight: 600; padding: 18px 16px; font-size: 16px; letter-spacing: 1px; }
.top { display: flex; align-items: center; border-bottom: 1px solid #e8e8e8; background: #fff; }
.crumb { font-weight: 600; }
.el-menu { border-right: none; flex: 1; overflow-y: auto; }
:deep(.el-menu) { width: 232px; }
.hint { color: #5a6b7c; font-size: 11px; padding: 10px 12px 14px; line-height: 1.6; }
</style>
