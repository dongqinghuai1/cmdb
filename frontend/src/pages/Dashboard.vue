<template>
  <el-row :gutter="16">
    <el-col :span="6" v-for="c in cards" :key="c.label">
      <el-card>
        <div style="color:#909399;font-size:13px">{{ c.label }}</div>
        <div style="font-size:30px;font-weight:700" :style="{ color: c.color }">{{ c.value }}</div>
      </el-card>
    </el-col>
  </el-row>
  <el-card style="margin-top:16px">
    <template #header>最新告警</template>
    <el-table :data="alerts" size="small" stripe>
      <el-table-column prop="last_fired_at" label="时间" width="180">
        <template #default="{row}">{{ (row.last_fired_at||'').replace('T',' ').slice(0,19) }}</template>
      </el-table-column>
      <el-table-column prop="severity" label="级别" width="90">
        <template #default="{row}">
          <el-tag :type="row.severity==='critical'?'danger':row.severity==='major'?'warning':'info'">
            {{ row.severity }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="device_id" label="设备ID" width="90" />
      <el-table-column prop="title" label="告警" />
      <el-table-column prop="status" label="状态" width="110">
        <template #default="{row}">
          <el-tag :type="row.status==='firing'?'danger':row.status==='resolved'?'success':'warning'">
            {{ row.status }}</el-tag>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
  <el-card style="margin-top:16px">
    <template #header>设备在线状态</template>
    <el-row :gutter="12">
      <el-col :span="4" v-for="m in models" :key="m.code">
        <el-tag :type="m.count>0?'primary':'info'" size="large" style="width:100%;justify-content:center">
          {{ m.name }} × {{ m.count }}
        </el-tag>
      </el-col>
    </el-row>
  </el-card>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import api from "../api";

const alerts = ref([]);
const stats = reactive({ total: 0, online: 0, firing: 0 });
const models = ref([]);

onMounted(async () => {
  const [dev, online, firing, alertList, modelList] = await Promise.all([
    api.get("/cmdb/devices/", { params: { page_size: 1 } }),
    api.get("/cmdb/devices/", { params: { page_size: 1, online_status: "online" } }),
    api.get("/alerts/events/", { params: { page_size: 1, status: "firing" } }),
    api.get("/alerts/events/", { params: { page_size: 10 } }),
    api.get("/cmdb/models/", { params: { page_size: 100 } }),
  ]);
  stats.total = dev.count; stats.online = online.count; stats.firing = firing.count;
  alerts.value = alertList.results || [];
  for (const m of (modelList.results || [])) {
    const c = await api.get("/cmdb/devices/", { params: { page_size: 1, model: m.id } });
    models.value.push({ code: m.code, name: m.name, count: c.count });
  }
});

const cards = computed(() => [
  { label: "设备总数", value: stats.total, color: "#303133" },
  { label: "在线设备", value: stats.online, color: "#67c23a" },
  { label: "活跃告警", value: stats.firing, color: "#f56c6c" },
  { label: "设备类型", value: models.value.length, color: "#409eff" },
]);
</script>
