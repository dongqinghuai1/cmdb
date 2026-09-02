<template>
  <el-container style="height: 100vh">
    <el-aside width="210px" class="side">
      <div class="logo">nops · 运维平台</div>
      <el-menu :default-active="$route.path" router background-color="#001529" text-color="#b7c0cd"
               active-text-color="#fff">
        <el-menu-item index="/dashboard"><el-icon><Monitor /></el-icon>工作台</el-menu-item>
        <el-menu-item index="/dcim"><el-icon><OfficeBuilding /></el-icon>机房管理</el-menu-item>
        <el-menu-item index="/topo"><el-icon><Connection /></el-icon>拓扑管理</el-menu-item>
        <el-menu-item index="/ncm"><el-icon><Document /></el-icon>配置管理</el-menu-item>
        <el-menu-item index="/automate"><el-icon><Promotion /></el-icon>自动化运维</el-menu-item>
        <el-menu-item index="/changes"><el-icon><EditPen /></el-icon>变更管理</el-menu-item>
        <el-menu-item index="/logs"><el-icon><Tickets /></el-icon>日志中心</el-menu-item>
        <el-menu-item index="/ipam"><el-icon><Grid /></el-icon>IP 管理</el-menu-item>
        <el-menu-item index="/devices"><el-icon><Cpu /></el-icon>设备台账</el-menu-item>
        <el-menu-item index="/alerts"><el-icon><Bell /></el-icon>告警中心</el-menu-item>
        <el-menu-item index="/incidents"><el-icon><Service /></el-icon>事件单</el-menu-item>
        <el-menu-item index="/inspects"><el-icon><List /></el-icon>巡检中心</el-menu-item>
        <el-menu-item index="/system"><el-icon><Setting /></el-icon>系统管理</el-menu-item>
      </el-menu>
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
import { Bell, Connection, Cpu, Document, EditPen, Grid, List, Monitor, OfficeBuilding, Promotion, Service, Setting, Tickets } from "@element-plus/icons-vue";
import api from "./api";

const user = ref({});
onMounted(async () => { user.value = await api.get("/auth/me/"); });
const logout = () => {
  localStorage.removeItem("token");
  location.href = "/login";
};
</script>

<style scoped>
.side { background: #001529; }
.logo { color: #fff; font-weight: 600; padding: 18px 16px; font-size: 16px; letter-spacing: 1px; }
.top { display: flex; align-items: center; justify-content: space-between;
       border-bottom: 1px solid #e8e8e8; background: #fff; }
.crumb { font-weight: 600; }
.el-menu { border-right: none; }
</style>
