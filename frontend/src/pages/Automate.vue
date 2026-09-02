<template>
  <el-tabs v-model="tab">
    <!-- ============ 脚本库 ============ -->
    <el-tab-pane label="脚本库" name="scripts">
      <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;align-items:center">
        <el-button type="primary" @click="openScript(null)">新建脚本</el-button>
        <el-button @click="openRun()">发起批量执行</el-button>
        <el-button @click="loadScripts">刷新</el-button>
        <span style="color:#e6a23c;font-size:12px">⚠ 高危脚本执行需主管审批；脚本内容 AES 加密存储</span>
      </div>
      <el-table :data="scripts" size="small" stripe v-loading="loading">
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="category" label="分类" width="120" />
        <el-table-column label="类型" width="110">
          <template #default="{row}">
            <el-tag size="small" effect="plain">{{ typeName(row.script_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="危险级别" width="90">
          <template #default="{row}">
            <el-tag size="small" :type="row.danger_level === 'high' ? 'danger'
                     : row.danger_level === 'mid' ? 'warning' : 'info'">
              {{ dangerName(row.danger_level) }}{{ row.requires_approval ? '·审批' : '' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="{row}">
            <el-switch :model-value="row.enabled" size="small"
                       @change="(v) => toggle(row, v)" />
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="140" show-overflow-tooltip />
        <el-table-column prop="updated_at" label="更新时间" width="160">
          <template #default="{row}">{{ (row.updated_at || '').slice(0, 19).replace('T', ' ') }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{row}">
            <el-button link type="primary" @click="openRun(row)">执行</el-button>
            <el-button link @click="openScript(row)">编辑</el-button>
            <el-button link type="danger" @click="delScript(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-tab-pane>

    <!-- ============ 执行历史 ============ -->
    <el-tab-pane label="执行历史" name="runs">
      <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;align-items:center">
        <el-select v-model="runF.script_id" placeholder="全部脚本" clearable style="width:200px" @change="loadRuns">
          <el-option v-for="s in scripts" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-select v-model="runF.status" placeholder="全部状态" clearable style="width:140px" @change="loadRuns">
          <el-option v-for="(v, k) in STATUS" :key="k" :label="v" :value="k" />
        </el-select>
        <el-button type="primary" @click="openRun()">发起批量执行</el-button>
        <el-button @click="loadRuns">刷新</el-button>
      </div>
      <el-table :data="runs" size="small" stripe v-loading="loading">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="script_name_snapshot" label="脚本" min-width="150" />
        <el-table-column label="危险" width="80">
          <template #default="{row}">
            <el-tag v-if="row.danger_snapshot" size="small"
                    :type="row.danger_snapshot === 'high' ? 'danger' : row.danger_snapshot === 'mid' ? 'warning' : 'info'">
              {{ dangerName(row.danger_snapshot) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{row}">
            <el-tag size="small" :type="statusType(row.status)">{{ STATUS[row.status] || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="150">
          <template #default="{row}">
            <el-progress v-if="row.stats?.total" :percentage="Math.round((row.stats.done / row.stats.total) * 100)"
                         :stroke-width="10" :status="row.status === 'running' ? undefined : 'success'"
                         :format="() => row.stats.done + '/' + row.stats.total" />
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="执行人" prop="executed_by_name" width="100" />
        <el-table-column label="灰度" width="70">
          <template #default="{row}">
            <el-tag v-if="row.gray_batch?.enabled" size="small" type="warning">
              剩 {{ row.gray_remaining }}
            </el-tag>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="summary" label="结果摘要" min-width="150" show-overflow-tooltip />
        <el-table-column label="发起时间" width="160">
          <template #default="{row}">{{ (row.created_at || '').slice(0, 19).replace('T', ' ') }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{row}">
            <el-button v-if="row.status === 'pending'" link type="success" @click="startRun(row)">开始执行</el-button>
            <el-button v-if="row.status === 'running' && row.gray_remaining > 0" link type="warning"
                       @click="continueRun(row)">继续灰度({{ row.gray_remaining }})</el-button>
            <el-button v-if="['pending', 'approving'].includes(row.status)" link type="danger"
                       @click="cancelRun(row)">取消</el-button>
            <el-button link @click="showDetails(row)">明细</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-tab-pane>

    <!-- ============ 我的审批 ============ -->
    <el-tab-pane label="我的审批" name="approvals">
      <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;align-items:center">
        <el-radio-group v-model="apF.status" @change="loadApprovals">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="pending">待处理</el-radio-button>
          <el-radio-button value="approved">已通过</el-radio-button>
          <el-radio-button value="rejected">已驳回</el-radio-button>
        </el-radio-group>
        <el-button @click="loadApprovals">刷新</el-button>
        <span style="color:#909399;font-size:12px">作为审批人/申请人均可在此看到相关单据</span>
      </div>
      <el-table :data="approvals" size="small" stripe v-loading="loading">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="biz_title" label="脚本" min-width="160" />
        <el-table-column label="危险" width="90">
          <template #default="{row}">
            <el-tag v-if="row.run_danger" size="small"
                    :type="row.run_danger === 'high' ? 'danger' : row.run_danger === 'mid' ? 'warning' : 'info'">
              {{ dangerName(row.run_danger) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="applicant_name" label="申请人" width="110" />
        <el-table-column prop="approver_name" label="审批人" width="110" />
        <el-table-column label="执行单状态" width="100">
          <template #default="{row}">
            <el-tag size="small" :type="statusType(row.run_status)">{{ STATUS[row.run_status] || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="审批" width="90">
          <template #default="{row}">
            <el-tag size="small" :type="row.status === 'approved' ? 'success'
                     : row.status === 'rejected' ? 'danger' : 'warning'">
              {{ row.status === 'approved' ? '已通过' : row.status === 'rejected' ? '已驳回' : '待处理' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="comment" label="意见" min-width="140" show-overflow-tooltip />
        <el-table-column label="申请时间" width="160">
          <template #default="{row}">{{ (row.created_at || '').slice(0, 19).replace('T', ' ') }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{row}">
            <template v-if="row.status === 'pending' && row.approver_id === me.id">
              <el-button link type="success" @click="decide(row, true)">通过</el-button>
              <el-button link type="danger" @click="decide(row, false)">驳回</el-button>
            </template>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
      </el-table>
    </el-tab-pane>
  </el-tabs>

  <!-- ============ 脚本编辑 ============ -->
  <el-dialog v-model="dlgScript" :title="scriptForm.id ? '编辑脚本' : '新建脚本'" width="680">
    <el-form :model="scriptForm" label-width="80px">
      <el-row :gutter="10">
        <el-col :span="12">
          <el-form-item label="名称" required><el-input v-model="scriptForm.name" /></el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="分类"><el-input v-model="scriptForm.category" placeholder="如 端口操作/配置备份" /></el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="10">
        <el-col :span="12">
          <el-form-item label="类型">
            <el-select v-model="scriptForm.script_type" style="width:100%">
              <el-option label="网络 CLI 命令" value="cli_command" />
              <el-option label="Shell 脚本" value="shell" />
              <el-option label="Python 脚本" value="python" />
              <el-option label="Ansible(未接入)" value="ansible" disabled />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="危险级别">
            <el-radio-group v-model="scriptForm.danger_level">
              <el-radio value="low">低危</el-radio>
              <el-radio value="mid">中危</el-radio>
              <el-radio value="high"><b style="color:#f56c6c">高危·需审批</b></el-radio>
            </el-radio-group>
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="内容" required>
        <el-input v-model="scriptForm.content" type="textarea" :rows="8" class="mono"
                  placeholder="支持多行命令；{{key}} 支持执行参数插值（预留）" />
      </el-form-item>
      <el-form-item label="备注"><el-input v-model="scriptForm.remark" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dlgScript = false">取消</el-button>
      <el-button type="primary" @click="saveScript">保存</el-button>
    </template>
  </el-dialog>

  <!-- ============ 发起批量执行 ============ -->
  <el-dialog v-model="dlgRun" title="发起批量执行" width="640" :close-on-click-modal="false">
    <el-form :model="runForm" label-width="86px">
      <el-form-item label="脚本" required>
        <el-select v-model="runForm.script_id" filterable style="width:100%"
                   @change="onPickScript">
          <el-option v-for="s in scripts.filter(x => x.enabled)" :key="s.id" :value="s.id">
            <span>{{ s.name }}</span>
            <el-tag size="small" style="margin-left:8px"
                    :type="s.danger_level === 'high' ? 'danger' : s.danger_level === 'mid' ? 'warning' : 'info'">
              {{ dangerName(s.danger_level) }}{{ s.requires_approval ? '·审批' : '' }}
            </el-tag>
          </el-option>
        </el-select>
      </el-form-item>
      <el-form-item v-if="curScript" label="脚本内容">
        <pre class="preview">{{ curScript.content }}</pre>
      </el-form-item>
      <el-form-item label="目标设备" required>
        <el-button @click="dlgDev = true">选择设备（{{ runForm.device_ids.length }} 台）</el-button>
        <span style="color:#909399;font-size:12px;margin-left:8px">{{ devNames }}</span>
      </el-form-item>
      <el-form-item label="灰度">
        <el-switch v-model="runForm.gray_first" />
        <span style="color:#e6a23c;font-size:12px;margin-left:8px">先执行 1 台 → 人工确认 → 再执行剩余</span>
      </el-form-item>
      <el-form-item v-if="curScript?.requires_approval" label="审批人" required>
        <el-select v-model="runForm.approver_id" filterable style="width:100%" placeholder="高危脚本必须选择审批人">
          <el-option v-for="u in users" :key="u.id" :label="u.username + (u.id === me.id ? '（我）' : '')"
                     :value="u.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="执行原因"><el-input v-model="runForm.reason" placeholder="操作目的（写入审计）" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dlgRun = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submitRun">提交并{{ curScript?.requires_approval ? '送审批' : '执行' }}</el-button>
    </template>
  </el-dialog>

  <!-- 设备选择 -->
  <el-dialog v-model="dlgDev" title="选择目标设备" width="760">
    <el-input v-model="devSearch" placeholder="搜索名称 / IP / 型号，回车加载" clearable style="width:320px"
              @keyup.enter="loadDevices" />
    <el-button style="margin-left:8px" @click="loadDevices">搜索</el-button>
    <span style="color:#909399;font-size:12px;margin-left:8px">已选 {{ runForm.device_ids.length }} 台</span>
    <el-table :data="devices" size="small" stripe height="380" style="margin-top:10px"
              @selection-change="(rows) => (runForm.device_ids = rows.map(r => r.id))">
      <el-table-column type="selection" width="40" :reserve-selection="false" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="manage_ip" label="管理 IP" width="130" />
      <el-table-column prop="vendor" label="厂商" width="90" />
      <el-table-column prop="hw_model" label="型号" min-width="120" />
      <el-table-column prop="online_status" label="在线" width="80">
        <template #default="{row}">
          <el-tag size="small" :type="row.online_status === 'online' ? 'success' : 'info'">
            {{ row.online_status }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-button @click="dlgDev = false">完成</el-button>
    </template>
  </el-dialog>

  <!-- 执行明细 -->
  <el-drawer v-model="dlgDetail" :title="'执行明细 #' + (detailRun?.id || '')" size="70%">
    <el-table :data="details" size="small" stripe max-height="560">
      <el-table-column prop="device_name" label="设备" width="150" />
      <el-table-column prop="device_id" label="ID" width="60" />
      <el-table-column label="状态" width="90">
        <template #default="{row}">
          <el-tag size="small" :type="row.status === 'success' ? 'success' : row.status === 'failed' ? 'danger'
                   : row.status === 'running' ? 'warning' : 'info'">{{ DETAIL[row.status] || row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="回显 / 错误">
        <template #default="{row}">
          <pre class="out" :class="{ err: row.error }">{{ row.error || row.output || '(无回显)' }}</pre>
        </template>
      </el-table-column>
      <el-table-column width="90">
        <template #default="{row}">
          <el-button v-if="row.output" link size="small" @click="copy(row.output)">复制</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-drawer>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "../api";

const STATUS = {
  pending: "待执行", approving: "待审批", running: "执行中",
  partial_success: "部分成功", success: "成功", failed: "失败", cancelled: "已取消",
};
const DETAIL = { pending: "排队中", running: "执行中", success: "成功", failed: "失败" };

const tab = ref("scripts");
const loading = ref(false);
const submitting = ref(false);
const me = ref({});
const scripts = ref([]);
const runs = ref([]);
const approvals = ref([]);
const users = ref([]);
const devices = ref([]);

const runF = reactive({ script_id: null, status: "" });
const apF = reactive({ status: "pending" });

const dlgScript = ref(false);
const dlgRun = ref(false);
const dlgDev = ref(false);
const dlgDetail = ref(false);
const scriptForm = reactive({ id: null, name: "", category: "", script_type: "cli_command",
                              danger_level: "low", content: "", remark: "", enabled: true });
const runForm = reactive({ script_id: null, device_ids: [], gray_first: false,
                           approver_id: null, reason: "" });
const curScript = ref(null);
const devSearch = ref("");
const detailRun = ref(null);
const details = ref([]);

const typeName = (t) => ({ cli_command: "CLI", python: "Python", shell: "Shell", ansible: "Ansible" }[t] || t);
const dangerName = (d) => ({ low: "低危", mid: "中危", high: "高危" }[d] || d);
const statusType = (s) => ({
  success: "success", running: "", approving: "warning", partial_success: "warning",
  pending: "info", failed: "danger", cancelled: "info",
}[s] || "info");
const devNames = computed(() => {
  const all = [...runForm.device_ids];
  return "已选 " + all.length + " 台";
});

const loadScripts = async () => {
  const r = await api.get("/automate/scripts/", { params: { page_size: 100 } });
  scripts.value = r.results || [];
};
const loadRuns = async () => {
  loading.value = true;
  try {
    const r = await api.get("/automate/script-runs/", { params: { ...runF, page_size: 50 } });
    runs.value = r.results || [];
  } finally { loading.value = false; }
};
const loadApprovals = async () => {
  loading.value = true;
  try {
    const params = { page_size: 100 };
    if (apF.status) params.status = apF.status;
    const r = await api.get("/automate/approvals/", { params });
    approvals.value = r.results || [];
  } finally { loading.value = false; }
};
const loadUsers = async () => {
  const r = await api.get("/system/users/", { params: { page_size: 200 } });
  users.value = r.results || [];
};
const loadDevices = async () => {
  const r = await api.get("/cmdb/devices/", { params: { search: devSearch.value || undefined, page_size: 50 } });
  devices.value = r.results || [];
};

// ---------- 脚本 ----------
const openScript = (row) => {
  Object.assign(scriptForm, row ? { ...row } : { id: null, name: "", category: "",
    script_type: "cli_command", danger_level: "low", content: "", remark: "", enabled: true });
  dlgScript.value = true;
};
const saveScript = async () => {
  if (!scriptForm.name.trim() || !scriptForm.content.trim()) {
    return ElMessage.warning("名称与内容必填");
  }
  const payload = { name: scriptForm.name, category: scriptForm.category,
                    script_type: scriptForm.script_type, danger_level: scriptForm.danger_level,
                    content: scriptForm.content, remark: scriptForm.remark };
  if (scriptForm.id) await api.patch("/automate/scripts/" + scriptForm.id + "/", payload);
  else await api.post("/automate/scripts/", payload);
  ElMessage.success("已保存");
  dlgScript.value = false;
  loadScripts();
};
const toggle = async (row, v) => {
  await api.patch("/automate/scripts/" + row.id + "/", { enabled: v });
  row.enabled = v;
};
const delScript = async (row) => {
  await ElMessageBox.confirm(`删除脚本「${row.name}」？已有执行记录的脚本会被拒绝删除。`, "确认", { type: "warning" });
  await api.delete("/automate/scripts/" + row.id + "/");
  ElMessage.success("已删除");
  loadScripts();
};

// ---------- 执行 ----------
const openRun = (script) => {
  Object.assign(runForm, { script_id: script?.id ?? null, device_ids: [], gray_first: false,
                           approver_id: null, reason: "" });
  curScript.value = script && scripts.value.find((s) => s.id === script.id) || null;
  if (script) onPickScript(script.id);
  loadDevices();
  dlgRun.value = true;
};
const onPickScript = (id) => {
  curScript.value = scripts.value.find((s) => s.id === id) || null;
};
const submitRun = async () => {
  if (!runForm.script_id || !runForm.device_ids.length) {
    return ElMessage.warning("请选择脚本与至少一台目标设备");
  }
  if (curScript.value?.requires_approval && !runForm.approver_id) {
    return ElMessage.warning("高危脚本必须选择审批人");
  }
  submitting.value = true;
  try {
    const body = { script_id: runForm.script_id,
                   scope: { device_ids: runForm.device_ids, gray_first: runForm.gray_first,
                            reason: runForm.reason },
                   approver_id: curScript.value?.requires_approval ? runForm.approver_id : undefined };
    const r = await api.post("/automate/script-runs/", body);
    const run = r.run;
    if (r.need_approval) {
      ElMessage.success("已提交审批，等待审批人通过后即可在「执行历史」启动");
    } else {
      await api.post(`/automate/script-runs/${run.id}/start/`, {});
      const msg = run.gray_first || runForm.gray_first
        ? "首批（1 台）已执行，确认无误后点「继续灰度」执行剩余设备"
        : "执行完成，详见「执行历史」明细";
      ElMessage.success(msg);
    }
    dlgRun.value = false;
    await loadRuns();
    tab.value = "runs";
  } finally { submitting.value = false; }
};
const startRun = async (row) => {
  await api.post(`/automate/script-runs/${row.id}/start/`, {});
  ElMessage.success("已开始执行");
  loadRuns();
};
const continueRun = async (row) => {
  const r = await api.post(`/automate/script-runs/${row.id}/continue/`, {});
  ElMessage.success(`已下发剩余 ${r.dispatched} 台`);
  loadRuns();
};
const cancelRun = async (row) => {
  const { value } = await ElMessageBox.prompt("取消原因（写入审计）", "取消执行", {
    inputPlaceholder: "如：改期 / 误操作", inputValue: "",
  }).catch(() => ({}));
  if (value === undefined) return;
  await api.post(`/automate/script-runs/${row.id}/cancel/`, { reason: value || "" });
  ElMessage.success("已取消");
  loadRuns();
};
const showDetails = async (row) => {
  detailRun.value = row;
  const r = await api.get(`/automate/script-runs/${row.id}/details/`, { params: { page_size: 500 } });
  details.value = r.results || [];
  dlgDetail.value = true;
};
const copy = async (text) => {
  await navigator.clipboard.writeText(text || "");
  ElMessage.success("已复制");
};

// ---------- 审批 ----------
const decide = async (row, approved) => {
  const { value } = await ElMessageBox.prompt(approved ? "通过意见（可空）" : "驳回原因（必填）", approved ? "通过" : "驳回", {
    inputValue: "", inputPlaceholder: approved ? "可选" : "必填，将写入执行单",
  }).catch(() => ({}));
  if (value === undefined) return;
  if (!approved && !value) return ElMessage.warning("驳回必须填写原因");
  const r = await api.post(`/automate/approvals/${row.id}/${approved ? "approve" : "reject"}/`,
                           { comment: value || "" });
  ElMessage.success(r.run_status === "pending" ? "已通过，执行人可启动任务"
                     : approved ? "已通过" : "已驳回，执行单已取消");
  loadApprovals();
  if (tab.value === "runs") loadRuns();
};

onMounted(async () => {
  const r = await api.get("/auth/me/");
  me.value = r;
  await Promise.all([loadScripts(), loadRuns(), loadApprovals(), loadUsers()]);
});
</script>

<style scoped>
.mono :deep(textarea), .out, .preview {
  font-family: Consolas, Menlo, monospace; font-size: 12px;
}
.preview {
  background: #f5f7fa; border: 1px solid #e4e7ed; border-radius: 4px;
  padding: 8px; width: 100%; max-height: 140px; overflow: auto; margin: 0;
  white-space: pre-wrap; word-break: break-all;
}
.out {
  background: #f5f7fa; margin: 0; padding: 6px 8px; border-radius: 4px;
  max-height: 150px; overflow: auto; white-space: pre-wrap; word-break: break-all;
}
.out.err { background: #fef0f0; color: #c04f4f; }
</style>
