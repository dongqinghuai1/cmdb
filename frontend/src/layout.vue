<template>
  <el-container style="height: 100vh">
    <el-aside width="232px" class="side">
      <div class="logo">nops · 运维平台</div>
      <el-menu :default-active="$route.path" router background-color="#001529" text-color="#b7c0cd"
               active-text-color="#fff">
        <el-menu-item index="/dashboard"><el-icon><Monitor /></el-icon>工作台</el-menu-item>

        <el-sub-menu index="g-monitor">
          <template #title><el-icon><Bell /></el-icon><span>监控与告警 · 值班/监控管理员</span></template>
          <el-menu-item index="/alerts">告警中心</el-menu-item>
          <el-menu-item index="/incidents">事件单（值班台）</el-menu-item>
          <el-menu-item index="/inspects">巡检中心</el-menu-item>
          <el-menu-item disabled class="plan">⌛ 温湿度等环境告警联动（规划）</el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="g-net">
          <template #title><el-icon><Connection /></el-icon><span>网络 · 网络管理员</span></template>
          <el-menu-item index="/ipam">IP · VLAN · 地址</el-menu-item>
          <el-menu-item index="/topo">网络拓扑</el-menu-item>
          <el-menu-item index="/ncm">配置备份与 diff</el-menu-item>
          <el-menu-item disabled class="plan">⌛ 路由/NAT/链路质量/无线总览（规划）</el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="g-asset">
          <template #title><el-icon><OfficeBuilding /></el-icon><span>资产与机房 · 机房/桌面管理员</span></template>
          <el-menu-item index="/devices">设备台账（360°）</el-menu-item>
          <el-menu-item index="/cmdb-tools">设备运营（质量/分组/软件/保修）</el-menu-item>
          <el-menu-item index="/dcim">机房与机柜（U 位/平面图）</el-menu-item>
          <el-menu-item disabled class="plan">⌛ 上下架·维修工单 / 布线视图（规划）</el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="g-workflow">
          <template #title><el-icon><Promotion /></el-icon><span>流程与自动化 · 变更/执行</span></template>
          <el-menu-item index="/automate">自动化运维（脚本执行）</el-menu-item>
          <el-menu-item index="/changes">变更管理（含网络割接）</el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="g-sec">
          <template #title><el-icon><Lock /></el-icon><span>安全与合规 · 安全/审计员</span></template>
          <el-menu-item index="/audit">操作审计（全站留痕+diff）</el-menu-item>
          <el-menu-item disabled class="plan">⌛ 登录审计视图（LoginEvent，规划）</el-menu-item>
          <el-menu-item disabled class="plan">⌛ 安全基线 / 漏洞 / 批量修复（规划）</el-menu-item>
        </el-sub-menu>

        <el-menu-item index="/logs"><el-icon><Tickets /></el-icon>日志中心</el-menu-item>
        <el-menu-item index="/system"><el-icon><Setting /></el-icon>系统管理</el-menu-item>
      </el-menu>
      <div class="hint">菜单按角色域分组 · 规划项为禁用占位<br/>动态菜单（按 RBAC 过滤）见 docs/IA-MENU.md</div>
    </el-aside>
    <el-container>
      <el-header class="top">
        <span class="crumb">{{ $route.meta.title || "" }}</span>
        <el-button link @click="logout">退出（{{ user.username }}）</el-button>
      </el-header>
      <el-main style="background:#f0f2f5"><router-view /></el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { Bell, Collection, Connection, Cpu, Document, EditPen, Grid, List, Lock, Monitor,
         OfficeBuilding, Promotion, Service, Setting, Tickets } from "@element-plus/icons-vue";
import api from "./api";

const user = ref({});
onMounted(async () => { user.value = await api.get("/auth/me/"); });
const logout = () => {
  localStorage.removeItem("token");
  location.href = "/login";
};
</script>

<style scoped>
.side { background: #001529; display: flex; flex-direction: column; }
.logo { color: #fff; font-weight: 600; padding: 18px 16px; font-size: 16px; letter-spacing: 1px; }
.top { display: flex; align-items: center; justify-content: space-between;
       border-bottom: 1px solid #e8e8e8; background: #fff; }
.crumb { font-weight: 600; }
.el-menu { border-right: none; flex: 1; overflow-y: auto; }
:deep(.el-menu) { width: 232px; }
:deep(.plan) { color: #5a6b7c !important; font-size: 12px; opacity: .9; cursor: default; }
.hint { color: #5a6b7c; font-size: 11px; padding: 10px 12px 14px; line-height: 1.6; }
</style>
