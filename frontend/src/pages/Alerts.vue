<template>
  <el-tabs v-model="tab">
    <el-tab-pane label="告警事件" name="events">
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
          <el-table-column label="操作" width="240">
            <template #default="{row}">
              <template v-if="['firing','acknowledged'].includes(row.status)">
                <el-button size="small" @click.stop="ack(row.id)">确认</el-button>
                <el-button size="small" type="success" @click.stop="resolve(row.id)">解决</el-button>
                <el-button size="small" link type="warning" @click.stop="toIncident(row.id)">转事件单</el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="count"
                       :page-size="20" :current-page="page" @current-change="load" />
      </el-card>
    </el-tab-pane>

    <el-tab-pane label="静默窗口" name="silence">
      <el-card>
        <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;align-items:center">
          <el-select v-model="silForm.all" placeholder="范围" style="width:130px">
            <el-option :value="false" label="指定设备" />
            <el-option :value="true" label="全部设备" />
          </el-select>
          <el-select v-if="!silForm.all" v-model="silForm.device_ids" multiple filterable collapse-tags
                     placeholder="选择设备（可多选）" style="min-width:260px">
            <el-option v-for="d in devices" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
          <el-input-number v-model="silForm.minutes" :min="5" :max="1440" />
          <span style="color:#909399;font-size:13px">分钟</span>
          <el-input v-model="silForm.reason" placeholder="原因（如：割接变更 CHG-001）" style="width:260px" />
          <el-button type="warning" @click="createSilence">开始静默</el-button>
        </div>
        <el-table :data="silences" size="small" stripe>
          <el-table-column prop="started_at" label="开始" width="170">
            <template #default="{row}">{{ (row.started_at||'').replace('T',' ').slice(0,19) }}</template>
          </el-table-column>
          <el-table-column prop="ended_at" label="结束" width="170">
            <template #default="{row}">{{ (row.ended_at||'').replace('T',' ').slice(0,19) }}</template>
          </el-table-column>
          <el-table-column label="范围" min-width="200">
            <template #default="{row}">
              <el-tag v-if="row.scope?.all" type="danger" size="small">全部设备</el-tag>
              <span v-else>{{ (row.scope?.device_ids||[]).map(devName).join('、') }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="原因" min-width="160" />
          <el-table-column label="状态" width="90">
            <template #default="{row}">
              <el-tag :type="active(row) ? 'warning' : 'info'">{{ active(row) ? '生效中' : '已结束' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{row}">
              <el-button v-if="active(row)" size="small" link type="primary" @click="endSilence(row.id)">提前结束</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </el-tab-pane>
  </el-tabs>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import api from "../api";

const tab = ref("events");
const rows = ref([]); const count = ref(0); const page = ref(1);
const f = reactive({ status: null, severity: null });
const devices = ref([]); const silences = ref([]);
const silForm = reactive({ all: false, device_ids: [], minutes: 60, reason: "" });

const devName = (id) => (devices.value.find((d) => d.id === id) || {}).name || "#" + id;
const active = (s) => {
  if (s.ended_at) return new Date(s.ended_at) > new Date();
  return true;
};

const load = async (p = 1) => {
  page.value = p;
  const r = await api.get("/alerts/events/", { params: { page: p, ...f } });
  rows.value = r.results || []; count.value = r.count;
};
const loadSil = async () => {
  const r = await api.get("/alerts/silences/", { params: { page_size: 50 } });
  silences.value = r.results || [];
};
onMounted(async () => {
  load();
  loadSil();
  const d = await api.get("/cmdb/devices/", { params: { page_size: 200 } });
  devices.value = d.results || [];
});

const ack = async (id) => { await api.post("/alerts/events/" + id + "/ack/"); ElMessage.success("已确认"); load(page.value); };
const resolve = async (id) => { await api.post("/alerts/events/" + id + "/resolve/"); ElMessage.success("已解决"); load(page.value); };
const toIncident = async (id) => {
  const r = await api.post("/alerts/events/" + id + "/create-incident/", {});
  ElMessage.success("已创建事件单 " + r.ticket_no);
  load(page.value);
};

const createSilence = async () => {
  if (!silForm.all && !silForm.device_ids.length) { ElMessage.warning("请选择设备或选全部"); return; }
  const start = new Date();
  const end = new Date(Date.now() + silForm.minutes * 60000);
  await api.post("/alerts/silences/", {
    scope: silForm.all ? { all: true } : { device_ids: silForm.device_ids },
    reason: silForm.reason, started_at: start.toISOString(), ended_at: end.toISOString(),
    silence_type: "maintenance",
  });
  ElMessage.success("静默已生效（" + silForm.minutes + " 分钟）");
  silForm.device_ids = []; silForm.reason = "";
  loadSil();
};
const endSilence = async (id) => {
  await api.post("/alerts/silences/" + id + "/end/");
  ElMessage.success("已结束"); loadSil();
};
</script>
