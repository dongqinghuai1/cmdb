<template>
  <el-card>
    <div style="display:flex;gap:8px;margin-bottom:12px">
      <el-select v-model="f.status" placeholder="状态" clearable style="width:140px" @change="load(1)">
        <el-option v-for="s in ['firing','acknowledged','processing','resolved','closed']"
                   :key="s" :label="s" :value="s" />
      </el-select>
      <el-select v-model="f.severity" placeholder="级别" clearable style="width:120px" @change="load(1)">
        <el-option v-for="s in ['critical','major','warning','info']" :key="s" :label="s" :value="s" />
      </el-select>
      <el-button type="primary" @click="load(1)">查询</el-button>
    </div>
    <el-table :data="rows" size="small" stripe>
      <el-table-column label="时间" width="170">
        <template #default="{row}">{{ (row.last_fired_at||'').replace('T',' ').slice(0,19) }}</template>
      </el-table-column>
      <el-table-column prop="severity" label="级别" width="90">
        <template #default="{row}">
          <el-tag :type="row.severity==='critical'?'danger':row.severity==='major'?'warning':'info'">
            {{ row.severity }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="device_id" label="设备ID" width="80" />
      <el-table-column prop="title" label="告警内容" min-width="220" />
      <el-table-column prop="fired_count" label="次数" width="70" />
      <el-table-column prop="status" label="状态" width="110">
        <template #default="{row}">
          <el-tag :type="row.status==='firing'?'danger':row.status==='resolved'?'success':'warning'">
            {{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="170">
        <template #default="{row}">
          <template v-if="['firing','acknowledged'].includes(row.status)">
            <el-button size="small" @click.stop="ack(row.id)">确认</el-button>
            <el-button size="small" type="success" @click.stop="resolve(row.id)">解决</el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="count"
                   :page-size="20" :current-page="page" @current-change="load" />
  </el-card>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import api from "../api";

const rows = ref([]); const count = ref(0); const page = ref(1);
const f = reactive({ status: null, severity: null });

const load = async (p = 1) => {
  page.value = p;
  const r = await api.get("/alerts/events/", { params: { page: p, ...f } });
  rows.value = r.results || []; count.value = r.count;
};
onMounted(load);

const ack = async (id) => { await api.post(`/alerts/events/${id}/ack/`); ElMessage.success("已确认"); load(page.value); };
const resolve = async (id) => { await api.post(`/alerts/events/${id}/resolve/`); ElMessage.success("已解决"); load(page.value); };
</script>
