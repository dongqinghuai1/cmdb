<template>
  <div>
    <el-card shadow="never">
      <el-form inline size="small" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:4px">
        <el-select v-model="f.action" placeholder="动作" clearable style="width:130px">
          <el-option v-for="a in ACTIONS" :key="a" :label="a" :value="a" />
        </el-select>
        <el-input v-model="f.q" placeholder="对象类型 / 对象ID / 来源IP（模糊）" clearable style="width:240px"
                  @keyup.enter="load(1)" />
        <el-date-picker v-model="f.date" type="daterange" value-format="YYYY-MM-DD"
                        start-placeholder="开始" end-placeholder="结束" style="width:230px" />
        <el-button type="primary" @click="load(1)">查询</el-button>
        <el-button @click="reset">重置</el-button>
        <span style="margin-left:auto;color:#909399">共 {{ total }} 条 · 审计数据只读，来源于全站写操作留痕</span>
      </el-form>
      <el-table :data="rows" size="small" stripe max-height="560" @row-click="openDetail">
        <el-table-column label="时间" width="165">
          <template #default="{row}">{{ fmt2(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="username" label="操作人" width="110" />
        <el-table-column label="动作" width="90">
          <template #default="{row}">
            <el-tag size="small" :type="ACTION_TYPE[row.action] || 'info'">{{ row.action }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="resource_type" label="对象类型" width="130" />
        <el-table-column prop="resource_id" label="对象ID" width="90" />
        <el-table-column prop="source_ip" label="来源IP" width="130" />
        <el-table-column label="变更摘要" min-width="220">
          <template #default="{row}">
            <span style="color:#909399">{{ summaryOf(row) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div style="margin-top:10px;display:flex;justify-content:flex-end">
        <el-pagination background layout="total, prev, pager, next" :total="total"
                       :page-size="pageSize" :current-page="f.page" @current-change="load" />
      </div>
    </el-card>

    <el-dialog v-model="dlg" title="操作审计详情（变更前后对照）" width="720px" top="6vh">
      <el-descriptions :column="2" border size="small" style="margin-bottom:10px">
        <el-descriptions-item label="时间">{{ fmt2(cur?.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="操作人">{{ cur?.username }}（IP {{ cur?.source_ip }}）</el-descriptions-item>
        <el-descriptions-item label="对象">{{ cur?.resource_type }} #{{ cur?.resource_id }}</el-descriptions-item>
        <el-descriptions-item label="动作">
          <el-tag size="small" :type="ACTION_TYPE[cur?.action] || 'info'">{{ cur?.action }}</el-tag>
        </el-descriptions-item>
      </el-descriptions>
      <el-alert v-if="!diffRows.length" type="info" :closable="false"
                title="该记录未携带结构化变更内容（或仅状态类动作）" />
      <el-table v-else :data="diffRows" size="small" border max-height="400">
        <el-table-column prop="k" label="字段" width="190" />
        <el-table-column label="变更前">
          <template #default="{row}">
            <div class="cell before">{{ pretty(row.before) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="变更后">
          <template #default="{row}">
            <div class="cell after">{{ pretty(row.after) }}</div>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="dlg=false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import api from "../api";

const ACTIONS = ["create", "update", "delete", "restore", "purge", "execute"];
const ACTION_TYPE = { create: "success", update: "", delete: "danger", restore: "warning",
                      purge: "danger", execute: "info" };
const f = reactive({ action: "", q: "", date: null, page: 1 });
const rows = ref([]);
const total = ref(0);
const pageSize = 50;
const dlg = ref(false);
const cur = ref(null);
const diffRows = ref([]);

const fmt2 = (s) => (s || "").replace("T", " ").slice(0, 19);
const pretty = (v) => (v === undefined || v === null ? "" : typeof v === "object" ? JSON.stringify(v) : String(v));
const load = async (page) => {
  f.page = page || 1;
  const params = { page: f.page, page_size: pageSize };
  if (f.action) params.action = f.action;
  if (f.q) params.search = f.q;
  if (f.date && f.date.length === 2) {
    params.created_at_after = f.date[0];
    params.created_at_before = f.date[1];
  }
  const r = await api.get("/system/audit-logs/", { params });
  rows.value = r.results || [];
  total.value = r.count || 0;
};
const reset = () => { f.action = ""; f.q = ""; f.date = null; load(1); };
const summaryOf = (row) => {
  const b = row.before || {}, a = row.after || {};
  const ks = new Set([...Object.keys(b), ...Object.keys(a)]);
  const changed = [...ks].filter((k) => JSON.stringify(b[k]) !== JSON.stringify(a[k]));
  if (row.action === "create") return "新增记录";
  if (row.action === "delete") return "删除记录";
  if (row.action === "execute") return "执行操作";
  return changed.length ? `变更 ${changed.length} 个字段：${changed.slice(0, 4).join("、")}` + (changed.length > 4 ? "…" : "") : "记录更新";
};
const openDetail = (row) => {
  cur.value = row;
  const b = row.before || {}, a = row.after || {};
  const ks = [...new Set([...Object.keys(b), ...Object.keys(a)])];
  diffRows.value = ks
    .filter((k) => JSON.stringify(b[k]) !== JSON.stringify(a[k]))
    .map((k) => ({ k, before: b[k], after: a[k] }));
  dlg.value = true;
};
onMounted(() => load(1));
</script>

<style scoped>
.cell { max-height: 80px; overflow: auto; white-space: pre-wrap; word-break: break-all;
        font-size: 12px; padding: 2px 4px; border-radius: 3px; }
.before { background: #fef0f0; color: #c45656; }
.after { background: #f0f9eb; color: #529b2e; }
:deep(.el-table__row) { cursor: pointer; }
</style>
