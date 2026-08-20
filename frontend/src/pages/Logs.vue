<template>
  <el-card>
    <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;align-items:center">
      <el-select v-model="f.device_id" placeholder="全部设备" clearable filterable style="width:170px" @change="load(1)">
        <el-option v-for="d in devices" :key="d.id" :label="d.name" :value="d.id" />
      </el-select>
      <el-select v-model="f.severity_lte" placeholder="全部级别" clearable style="width:130px" @change="load(1)">
        <el-option v-for="(n, v) in SEV" :key="v" :label="n + '(' + v + ')'" :value="v" />
      </el-select>
      <el-input v-model="f.keyword" placeholder="关键字包含" style="width:180px" clearable
                @keyup.enter="load(1)" @clear="load(1)" />
      <el-date-picker v-model="range" type="datetimerange" range-separator="至" start-placeholder="开始"
                      end-placeholder="结束" size="default" style="width:340px" value-format="YYYY-MM-DDTHH:mm:ss"
                      @change="load(1)" />
      <el-button type="primary" @click="load(1)">查询</el-button>
      <el-button @click="testWrite">写入测试日志</el-button>
      <el-switch v-model="auto" active-text="10s 自动刷新" @change="toggleAuto" />
      <span style="color:#909399;font-size:12px">接收端口：UDP 514（设备 syslog 指向本机即可）</span>
    </div>

    <el-table :data="rows" size="small" stripe>
      <el-table-column prop="occurred_at" label="时间" width="180">
        <template #default="{row}">{{ (row.occurred_at||'').replace('T',' ').slice(0,19) }}</template>
      </el-table-column>
      <el-table-column label="设备" width="140">
        <template #default="{row}">
          <el-link v-if="row.device_id" @click="$router.push('/devices/' + row.device_id)">{{ devName(row.device_id) }}</el-link>
          <span v-else style="color:#c0c4cc">未匹配</span>
        </template>
      </el-table-column>
      <el-table-column label="级别" width="90">
        <template #default="{row}">
          <el-tag size="small" :type="sevType(row.severity)">{{ SEV[row.severity] || row.severity }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="facility" label="facility" width="90" />
      <el-table-column prop="source" label="来源" width="80" />
      <el-table-column prop="message" label="消息" min-width="380" show-overflow-tooltip />
    </el-table>
    <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="count"
                   :page-size="50" :current-page="page" @current-change="load" />
  </el-card>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import api from "../api";

const SEV = { 0: "emerg", 1: "alert", 2: "crit", 3: "error", 4: "warning", 5: "notice", 6: "info", 7: "debug" };
const sevType = (s) => (s <= 2 ? "danger" : s === 3 ? "warning" : s === 4 ? "warning" : "info");

const devices = ref([]); const rows = ref([]); const count = ref(0); const page = ref(1);
const f = reactive({ device_id: null, severity_lte: null, keyword: "" });
const range = ref(null);
const auto = ref(false);
let timer = null;

const devName = (id) => (devices.value.find((d) => d.id === id) || {}).name || "#" + id;

const load = async (p = 1) => {
  page.value = p;
  const params = { page: p, page_size: 50 };
  if (f.device_id) params.device_id = f.device_id;
  if (f.severity_lte !== null && f.severity_lte !== "") params.severity_lte = f.severity_lte;
  if (f.keyword) params.keyword = f.keyword;
  if (range.value && range.value[0]) { params.occurred_after = range.value[0]; params.occurred_before = range.value[1]; }
  const r = await api.get("/monitor/logs/", { params });
  rows.value = r.results || [];
  count.value = r.count;
};

const testWrite = async () => {
  await api.post("/monitor/logs/test-write/",
                 { message: "nops 测试日志：OSPF neighbor 10.1.1.2 Down", severity: 3,
                   device: f.device_id || null });
  ElMessage.success("已写入（severity=error）");
  load(1);
};

const toggleAuto = (v) => {
  if (timer) { clearInterval(timer); timer = null; }
  if (v) timer = setInterval(() => load(page.value), 10000);
};

onMounted(async () => {
  const dv = await api.get("/cmdb/devices/", { params: { page_size: 200 } });
  devices.value = dv.results || [];
  await load();
});
onBeforeUnmount(() => { if (timer) clearInterval(timer); });
</script>
