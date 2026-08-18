<template>
  <el-card v-if="dev">
    <template #header>
      <b>{{ dev.name }}</b>
      <el-tag style="margin-left:10px" :type="dev.online_status==='online'?'success':'info'">
        {{ dev.online_status }}</el-tag>
      <el-tag style="margin-left:6px">{{ dev.model_name }}</el-tag>
      <el-tag v-if="dev.rack_name" style="margin-left:6px" type="warning">
        {{ dev.rack_name }} U{{ dev.rack_start_u }}（{{ dev.rack_units }}U）</el-tag>
    </template>
    <el-descriptions :column="3" border size="small">
      <el-descriptions-item label="SN">{{ dev.sn || "-" }}</el-descriptions-item>
      <el-descriptions-item label="管理IP">{{ dev.manage_ip || "-" }}</el-descriptions-item>
      <el-descriptions-item label="品牌/型号">{{ dev.vendor }} {{ dev.hw_model }}</el-descriptions-item>
      <el-descriptions-item label="系统版本">{{ dev.sw_version || "-" }}</el-descriptions-item>
      <el-descriptions-item label="位置">{{ dev.region_name }} / {{ dev.site_name }}</el-descriptions-item>
      <el-descriptions-item label="生命周期">{{ dev.lifecycle_status }}</el-descriptions-item>
      <el-descriptions-item label="用途标签">{{ dev.usage_tag }}</el-descriptions-item>
      <el-descriptions-item label="占用状态">{{ dev.usage_status }}</el-descriptions-item>
      <el-descriptions-item label="采集驱动">{{ dev.driver_type || "-" }}</el-descriptions-item>
      <el-descriptions-item label="保修到期">{{ dev.warranty_until || "-" }}</el-descriptions-item>
      <el-descriptions-item label="责任人">{{ dev.owner_name || "-" }}</el-descriptions-item>
      <el-descriptions-item label="最近在线">{{ (dev.last_seen_at||"").replace("T"," ").slice(0,19) || "-" }}</el-descriptions-item>
    </el-descriptions>
  </el-card>

  <el-card style="margin-top:14px">
    <template #header>接口（{{ interfaces.length }}）</template>
    <el-table :data="interfaces" size="small" stripe max-height="420">
      <el-table-column prop="name" label="接口" min-width="140" />
      <el-table-column prop="oper_status" label="状态" width="80">
        <template #default="{row}">
          <el-tag size="small" :type="row.oper_status==='up'?'success':'info'">{{ row.oper_status || "-" }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="if_alias" label="描述" min-width="140" />
      <el-table-column label="入流量" width="110">
        <template #default="{row}">{{ fmt(row.stat?.in_bps) }}</template>
      </el-table-column>
      <el-table-column label="出流量" width="110">
        <template #default="{row}">{{ fmt(row.stat?.out_bps) }}</template>
      </el-table-column>
      <el-table-column label="错包速率" width="110">
        <template #default="{row}">{{ row.stat?.in_errors_rate || 0 }} /s</template>
      </el-table-column>
      <el-table-column label="光功率(dBm)" width="130">
        <template #default="{row}">{{ row.stat?.optical_tx_dbm ?? "-" }} / {{ row.stat?.optical_rx_dbm ?? "-" }}</template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import api from "../api";

const route = useRoute();
const dev = ref(null);
const interfaces = ref([]);

const fmt = (bps) => {
  if (!bps) return "0";
  const units = ["b", "Kb", "Mb", "Gb"];
  let i = 0, v = bps;
  while (v >= 1000 && i < 3) { v /= 1000; i++; }
  return v.toFixed(1) + units[i];
};

onMounted(async () => {
  const d = await api.get(`/cmdb/devices/${route.params.id}/360/`);
  dev.value = d;
  interfaces.value = (d.interfaces || []).map((i) => ({ ...i, stat: i.stat || null }));
});
</script>
