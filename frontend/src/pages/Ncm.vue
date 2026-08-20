<template>
  <el-tabs v-model="tab">
    <el-tab-pane label="配置备份" name="backup">
      <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
        <el-select v-model="devId" filterable placeholder="选择设备" style="width:220px">
          <el-option v-for="d in devices" :key="d.id" :label="d.name + ' (' + d.manage_ip + ')'" :value="d.id" />
        </el-select>
        <el-button type="primary" :disabled="!devId" @click="triggerBackup">SSH 备份</el-button>
        <el-button :disabled="!devId" @click="dlgImport = true">手工导入配置</el-button>
        <el-button :disabled="diffA === null || diffB === null" @click="showDiff(diffA, diffB)">对比选中两版</el-button>
      </div>
      <el-table :data="backups" size="small" stripe @selection-change="onSel">
        <el-table-column type="selection" width="42" :selectable="(row) => row.device_id === (backups[0]||{}).device_id" />
        <el-table-column prop="device_id" label="设备ID" width="80">
          <template #default="{row}">{{ devName(row.device_id) }}</template>
        </el-table-column>
        <el-table-column prop="trigger" label="来源" width="90" />
        <el-table-column prop="file_hash" label="sha256" min-width="130">
          <template #default="{row}">{{ row.file_hash.slice(0, 12) }}</template>
        </el-table-column>
        <el-table-column prop="size" label="字节" width="90" />
        <el-table-column prop="created_at" label="时间" width="170">
          <template #default="{row}">{{ (row.created_at||'').replace('T',' ').slice(0,19) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{row}">
            <el-button size="small" link type="primary" @click="showContent(row.id)">内容</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-tab-pane>

    <el-tab-pane label="变更事件" name="events">
      <el-table :data="events" size="small" stripe>
        <el-table-column prop="detected_at" label="时间" width="170">
          <template #default="{row}">{{ (row.detected_at||'').replace('T',' ').slice(0,19) }}</template>
        </el-table-column>
        <el-table-column label="设备" width="140">
          <template #default="{row}">{{ devName(row.device_id) }} (#{{ row.device_id }})</template>
        </el-table-column>
        <el-table-column prop="changed_lines" label="变化行数" width="90" />
        <el-table-column label="操作" width="80">
          <template #default="{row}">
            <el-button size="small" link type="primary" @click="showDiff(row.old_backup_id, row.new_backup_id)">diff</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-tab-pane>

    <el-tab-pane label="安全基线" name="baseline">
      <div style="display:flex;gap:8px;margin-bottom:10px">
        <el-button type="primary" @click="dlgRule = true">新建规则</el-button>
        <el-button @click="runCheck">执行核查</el-button>
      </div>
      <el-table :data="rules" size="small" stripe>
        <el-table-column prop="name" label="规则" />
        <el-table-column prop="rule_type" label="类型" width="110" />
        <el-table-column prop="pattern" label="正则" min-width="180" />
        <el-table-column prop="severity" label="级别" width="80" />
      </el-table>
      <h4>最近核查结果</h4>
      <el-table :data="results" size="small" stripe max-height="300">
        <el-table-column prop="rule_name" label="规则" min-width="140" />
        <el-table-column label="设备" width="140">
          <template #default="{row}">{{ devName(row.device_id) }}</template>
        </el-table-column>
        <el-table-column prop="compliant" label="合规" width="90">
          <template #default="{row}">
            <el-tag size="small" :type="row.compliant ? 'success' : 'danger'">{{ row.compliant ? "合规" : "不合规" }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="matched_content" label="命中内容" min-width="220" show-overflow-tooltip />
      </el-table>
    </el-tab-pane>
  </el-tabs>

  <el-dialog v-model="dlgImport" :title="'导入 ' + devName(devId) + ' 配置'" width="700">
    <el-input v-model="importText" type="textarea" :rows="16" placeholder="粘贴 running-config 全文" />
    <template #footer>
      <el-button @click="dlgImport = false">取消</el-button>
      <el-button type="primary" @click="doImport">导入</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="dlgDiff" title="配置 diff" width="820">
    <pre class="diffbox">{{ diffText || "(无差异)" }}</pre>
  </el-dialog>

  <el-dialog v-model="dlgContent" title="配置内容" width="820">
    <pre class="diffbox">{{ contentText }}</pre>
  </el-dialog>

  <el-dialog v-model="dlgRule" title="新建基线规则" width="520">
    <el-form :model="ruleForm" label-width="80px">
      <el-form-item label="名称"><el-input v-model="ruleForm.name" placeholder="如：必须配置日志主机" /></el-form-item>
      <el-form-item label="类型">
        <el-radio-group v-model="ruleForm.rule_type">
          <el-radio value="must_present">必须存在</el-radio>
          <el-radio value="must_absent">禁止存在</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="正则"><el-input v-model="ruleForm.pattern" placeholder="如 ^info-center loghost" /></el-form-item>
      <el-form-item label="级别">
        <el-select v-model="ruleForm.severity"><el-option value="warning" /><el-option value="critical" /></el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dlgRule = false">取消</el-button>
      <el-button type="primary" @click="createRule">创建</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import api from "../api";

const tab = ref("backup");
const devices = ref([]); const backups = ref([]); const events = ref([]);
const rules = ref([]); const results = ref([]);
const devId = ref(null);
const diffA = ref(null); const diffB = ref(null);
const dlgImport = ref(false); const dlgDiff = ref(false); const dlgContent = ref(false); const dlgRule = ref(false);
const importText = ref(""); const diffText = ref(""); const contentText = ref("");
const ruleForm = reactive({ name: "", rule_type: "must_present", pattern: "", severity: "warning" });

const devName = (id) => (devices.value.find((d) => d.id === id) || {}).name || "#" + id;

const load = async () => {
  const [dv, ev, ru, rs] = await Promise.all([
    api.get("/cmdb/devices/", { params: { page_size: 200 } }),
    api.get("/ncm/change-events/", { params: { page_size: 50 } }),
    api.get("/ncm/baseline-rules/", { params: { page_size: 50 } }),
    api.get("/ncm/baseline-results/", { params: { page_size: 50 } }),
  ]);
  devices.value = dv.results || []; events.value = ev.results || [];
  rules.value = ru.results || []; results.value = rs.results || [];
  loadBackups();
};
const loadBackups = async () => {
  const p = devId.value ? { device_id: devId.value, page_size: 100 } : { page_size: 100 };
  const r = await api.get("/ncm/backups/", { params: p });
  backups.value = r.results || [];
};
onMounted(load);

const onSel = (rows) => {
  diffA.value = rows[0]?.id ?? null;
  diffB.value = rows[1]?.id ?? null;
};

const triggerBackup = async () => {
  const r = await api.post("/ncm/backups/trigger/", { device: devId.value });
  ElMessage.success(r.msg || "已下发");
  setTimeout(loadBackups, 6000);
};

const doImport = async () => {
  if (!importText.value.trim()) { ElMessage.warning("内容为空"); return; }
  const r = await api.post("/ncm/backups/import/", { device: devId.value, content: importText.value });
  ElMessage.success(r.changed ? "已导入（检测到配置变更）" : "已导入（与上版相同，去重）");
  dlgImport.value = false; importText.value = "";
  load();
};

const showDiff = async (a, b) => {
  if (!a || !b) { ElMessage.warning("请选择两个版本"); return; }
  const r = await api.get("/ncm/backups/diff/", { params: { a, b } });
  diffText.value = r.diff || "(无差异)";
  dlgDiff.value = true;
};

const showContent = async (id) => {
  const r = await api.get("/ncm/backups/" + id + "/content/");
  contentText.value = r.content;
  dlgContent.value = true;
};

const createRule = async () => {
  if (!ruleForm.name || !ruleForm.pattern) { ElMessage.warning("名称与正则必填"); return; }
  await api.post("/ncm/baseline-rules/", { ...ruleForm });
  ElMessage.success("已创建"); dlgRule.value = false;
  ruleForm.name = ""; ruleForm.pattern = "";
  load();
};

const runCheck = async () => {
  const r = await api.post("/ncm/baseline-rules/check/", {});
  ElMessage.success("核查完成：" + r.checked + " 项");
  load();
};
</script>

<style scoped>
.diffbox { background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 6px;
           max-height: 480px; overflow: auto; font-size: 12px; line-height: 1.5; }
</style>
