<template>
  <el-tabs v-model="tab">
    <el-tab-pane label="设备分组" name="groups">
      <el-row :gutter="12">
        <el-col :span="9">
          <el-card shadow="never">
            <template #header>
              <div style="display:flex;justify-content:space-between">
                <b>分组</b>
                <span><el-button size="small" type="primary" link @click="newGroup">新建</el-button>
                  <el-button size="small" type="danger" link :disabled="!cur" @click="delGroup">删除</el-button></span>
              </div>
            </template>
            <el-table :data="groups" size="small" highlight-current-row @current-change="pickGroup">
              <el-table-column prop="name" label="名称" min-width="120" />
              <el-table-column prop="group_type" label="类型" width="80">
                <template #default="{row}">
                  <el-tag size="small" :type="row.group_type==='dynamic'?'warning':'info'">
                    {{ row.group_type === "dynamic" ? "动态" : "静态" }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="规则" min-width="140">
                <template #default="{row}">{{ ruleText(row.filter || {}) || "-" }}</template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
        <el-col :span="15">
          <el-card v-if="form.name || creating" shadow="never">
            <template #header><b>{{ creating ? "新建分组" : "分组配置" }}</b></template>
            <el-form label-width="90px" size="small">
              <el-form-item label="名称" required>
                <el-input v-model="form.name" style="width:280px" />
              </el-form-item>
              <el-form-item label="类型">
                <el-radio-group v-model="form.group_type" :disabled="!creating">
                  <el-radio-button label="static">静态（手工挑设备）</el-radio-button>
                  <el-radio-button label="dynamic">动态（按规则匹配）</el-radio-button>
                </el-radio-group>
              </el-form-item>
              <template v-if="form.group_type==='dynamic'">
                <el-form-item label="匹配规则">
                  <div style="display:flex;gap:8px;flex-wrap:wrap">
                    <el-input v-model="rule.vendor" placeholder="品牌 如 H3C" style="width:150px" clearable />
                    <el-select v-model="rule.region_id" placeholder="地区" clearable style="width:150px">
                      <el-option v-for="r in regions" :key="r.id" :label="r.name" :value="r.id" />
                    </el-select>
                    <el-select v-model="rule.model" placeholder="设备类型(code)" clearable filterable style="width:190px">
                      <el-option v-for="m in models" :key="m.code" :label="m.name + ' (' + m.code + ')'" :value="m.code" />
                    </el-select>
                  </div>
                </el-form-item>
                <el-form-item label="成员">
                  <span>当前命中 <b>{{ previewCount }}</b> 台</span>
                  <div style="display:flex;gap:8px;margin-left:16px">
                    <el-button size="small" type="primary" plain @click="preview">预览</el-button>
                    <el-button size="small" type="success" @click="apply">保存并应用</el-button>
                  </div>
                </el-form-item>
              </template>
              <template v-else>
                <el-form-item label="静态成员">
                  <el-button size="small" @click="memberPick=true">挑选设备</el-button>
                  <span style="margin-left:8px;color:#909399">共 {{ members.length }} 台</span>
                </el-form-item>
              </template>
            </el-form>
            <template v-if="creating">
              <div style="text-align:right">
                <el-button size="small" @click="creating=false;form.name=''">取消</el-button>
                <el-button size="small" type="primary" @click="saveNew">创建</el-button>
              </div>
            </template>
          </el-card>
          <el-card v-else shadow="never">
            <template #header>提示</template>
            在左侧选择一个分组，或在左上角「新建」。
          </el-card>
          <el-card v-if="form.group_type==='static' && cur" shadow="never" style="margin-top:12px">
            <template #header>成员设备（{{ members.length }}）</template>
            <el-table :data="members" size="small" max-height="330">
              <el-table-column prop="name" label="名称" min-width="120" />
              <el-table-column prop="manage_ip" label="管理IP" width="120" />
              <el-table-column prop="model_name" label="类型" width="100" />
              <el-table-column prop="vendor" label="品牌" width="90" />
              <el-table-column label="操作" width="80">
                <template #default="{row}">
                  <el-button size="small" link type="danger" @click="removeMember(row)">移除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
      </el-row>

      <el-dialog v-model="memberPick" title="挑选设备加入静态分组" width="680px">
        <el-input v-model="devQ" placeholder="搜索名称/IP/SN" clearable style="margin-bottom:8px" />
        <el-table :data="devRows" size="small" @selection-change="sel=$event">
          <el-table-column type="selection" width="40" />
          <el-table-column prop="name" label="名称" min-width="110" />
          <el-table-column prop="manage_ip" label="管理IP" width="110" />
          <el-table-column prop="model_name" label="类型" width="100" />
        </el-table>
        <template #footer>
          <el-button @click="memberPick=false">取消</el-button>
          <el-button type="primary" @click="addMembers">加入（{{ sel.length }}）</el-button>
        </template>
      </el-dialog>
    </el-tab-pane>

    <el-tab-pane label="软件版本一致性" name="software">
      <el-card shadow="never">
        <el-table :data="swGroups" size="small" stripe @row-click="(r)=>openSw(r)" highlight-current-row
                  style="cursor:pointer">
          <el-table-column prop="vendor" label="品牌" width="110" />
          <el-table-column prop="hw_model" label="型号" min-width="140" />
          <el-table-column label="版本分布" min-width="260">
            <template #default="{row}">
              <el-tag v-for="v in row.versions" :key="v.v" size="small" style="margin-right:6px"
                      :type="row.versions.length>1?'warning':'success'">
                {{ v.v || "（空）" }} × {{ v.c }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="一致性" width="90">
            <template #default="{row}">
              <el-tag size="small" :type="row.versions.length>1?'warning':'success'">
                {{ row.versions.length > 1 ? "多版本" : "一致" }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-divider v-if="swDetail" content-position="left">
          {{ swDetail.vendor }} {{ swDetail.hw_model }} 设备明细（{{ swDevices.length }}）
        </el-divider>
        <el-table v-if="swDetail" :data="swDevices" size="small" max-height="400">
          <el-table-column prop="name" label="名称" min-width="130" />
          <el-table-column prop="manage_ip" label="管理IP" width="120" />
          <el-table-column prop="sw_version" label="系统版本" width="160">
            <template #default="{row}">
              <el-tag size="small" :type="row.sw_version===swTarget?'success':'warning'">{{ row.sw_version || "（空）" }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="位置" min-width="150">
            <template #default="{row}">{{ row.region_name }} / {{ row.site_name }}</template>
          </el-table-column>
        </el-table>
      </el-card>
    </el-tab-pane>

    <el-tab-pane label="保修到期" name="warranty">
      <el-card shadow="never">
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
          <el-tag v-for="w in WKEYS" :key="w.k" :type="wSel===w.k?'primary':'info'" class="qtag"
                  @click="pickWarranty(w.k)">
            {{ w.l }}：{{ wrSummary[w.k] ?? "-" }}
          </el-tag>
        </div>
        <el-table :data="wrRows" size="small" stripe max-height="480"
                  @row-click="(r) => $router.push('/devices/' + r.id)" style="cursor:pointer">
          <el-table-column prop="name" label="设备" min-width="130" />
          <el-table-column label="位置" min-width="150">
            <template #default="{row}">{{ row.region_name }} / {{ row.site_name }}</template>
          </el-table-column>
          <el-table-column prop="vendor" label="品牌" width="90" />
          <el-table-column prop="hw_model" label="型号" width="120" />
          <el-table-column prop="warranty_until" label="保修到期" width="120" />
          <el-table-column label="剩余" width="110">
            <template #default="{row}">
              <el-tag size="small" :type="row.days_left < 0 ? 'danger' : row.days_left <= 90 ? 'warning' : 'success'">
                {{ row.days_left < 0 ? "已过期" + (-row.days_left) + "天" : row.days_left + "天" }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="owner" label="责任人" width="100" />
        </el-table>
      </el-card>
    </el-tab-pane>
  </el-tabs>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "../api";

const tab = ref("groups");
const groups = ref([]);
const cur = ref(null);
const creating = ref(false);
const regions = ref([]);
const models = ref([]);
const rule = reactive({ vendor: "", region_id: null, model: "" });
const previewCount = ref(0);
const members = ref([]);
const form = reactive({ name: "", group_type: "static" });

const loadGroups = async () => {
  const r = await api.get("/cmdb/groups/", { params: { page_size: 200 } });
  groups.value = r.results || [];
};
const ruleText = (f) => {
  const s = [];
  if (f.vendor) s.push("品牌=" + f.vendor);
  if (f.region_id) s.push("地区#" + f.region_id);
  if (f.model) s.push("类型=" + f.model);
  return s.join(" 且 ");
};

const pickGroup = async (row) => {
  cur.value = row;
  creating.value = false;
  Object.assign(form, { name: row.name, group_type: row.group_type });
  rule.vendor = (row.filter || {}).vendor || "";
  rule.region_id = (row.filter || {}).region_id ?? null;
  rule.model = (row.filter || {}).model || "";
  previewCount.value = 0;
  await loadMembers(row);
};
const loadMembers = async (g) => {
  if (g.group_type === "static") {
    const r = await api.get(`/cmdb/groups/${g.id}/members/`);
    members.value = r.devices || [];
  }
};

const newGroup = () => {
  creating.value = true;
  cur.value = null;
  members.value = [];
  Object.assign(form, { name: "", group_type: "dynamic" });
  rule.vendor = ""; rule.region_id = null; rule.model = "";
  previewCount.value = 0;
};
const saveNew = async () => {
  if (!form.name.trim()) { ElMessage.warning("请填写分组名称"); return; }
  const r = await api.post("/cmdb/groups/", { ...form, filter: { ...rule } });
  ElMessage.success("已创建");
  await loadGroups();
  pickGroup(r);
};
const delGroup = async () => {
  await ElMessageBox.confirm(`确认删除分组「${cur.value.name}」？`, "提示", { type: "warning" });
  await api.delete(`/cmdb/groups/${cur.value.id}/`);
  ElMessage.success("已删除");
  cur.value = null;
  loadGroups();
};
const cleanRule = () => {
  const f = {};
  if (rule.vendor) f.vendor = rule.vendor.trim();
  if (rule.region_id) f.region_id = rule.region_id;
  if (rule.model) f.model = rule.model;
  return f;
};
const preview = async () => {
  const r = await api.post(`/cmdb/groups/${cur.value.id}/evaluate/`, { filter: cleanRule() });
  previewCount.value = r.matched || 0;
  ElMessage.success(`命中 ${r.matched} 台（未保存）`);
};
const apply = async () => {
  await api.patch(`/cmdb/groups/${cur.value.id}/`, { name: form.name, group_type: form.group_type, filter: cleanRule() });
  const r = await api.post(`/cmdb/groups/${cur.value.id}/evaluate/`, { filter: cleanRule(), apply: true });
  ElMessage.success(`已应用，成员 ${r.applied} 台`);
  previewCount.value = r.matched || 0;
  await loadGroups();
  cur.value = groups.value.find((g) => g.id === cur.value.id);
};

// 静态成员
const memberPick = ref(false);
const devQ = ref("");
const devRows = ref([]);
const sel = ref([]);
const openPick = async () => {
  memberPick.value = true;
  const r = await api.get("/cmdb/devices/", { params: { page_size: 300, search: devQ.value || undefined } });
  devRows.value = r.results || [];
};
const addMembers = async () => {
  const ids = [...new Set([...members.value.map((m) => m.id), ...sel.value.map((d) => d.id)])];
  await api.patch(`/cmdb/groups/${cur.value.id}/`, { devices: ids });
  ElMessage.success(`已加入 ${sel.value.length} 台`);
  memberPick.value = false;
  await loadMembers(cur.value);
};
const removeMember = async (row) => {
  const ids = members.value.filter((m) => m.id !== row.id).map((m) => m.id);
  await api.patch(`/cmdb/groups/${cur.value.id}/`, { devices: ids });
  ElMessage.success("已移除");
  await loadMembers(cur.value);
};

// 软件版本
const swGroups = ref([]);
const swDevices = ref([]);
const swDetail = ref(null);
const swTarget = computed(() => {
  if (!swDetail.value || !swDetail.value.versions.length) return "";
  const v = [...swDetail.value.versions].sort((a, b) => b.c - a.c)[0];
  return v.v;
});
const loadSw = async () => {
  const list = await api.get("/cmdb/devices/software-summary/");
  const map = {};
  for (const r of list) {
    const k = (r.vendor || "") + "|" + (r.hw_model || "");
    map[k] = map[k] || { vendor: r.vendor || "", hw_model: r.hw_model || "", versions: [], total: 0 };
    map[k].versions.push({ v: r.sw_version, c: r.c });
    map[k].total += r.c;
  }
  swGroups.value = Object.values(map);
};
const openSw = async (row) => {
  swDetail.value = row;
  const r = await api.get("/cmdb/devices/", {
    params: { vendor: row.vendor || undefined, hw_model: row.hw_model || undefined, page_size: 500 },
  });
  swDevices.value = (r.results || []).sort((a, b) =>
    (a.sw_version || "~") < (b.sw_version || "~") ? -1 : 1);
};

// 保修到期
const WKEYS = [
  { k: "30", l: "30 天内" }, { k: "60", l: "60 天内" }, { k: "90", l: "90 天内" },
  { k: "180", l: "180 天内" }, { k: "expired", l: "已过期" },
];
const wSel = ref("90");
const wrSummary = ref({});
const wrRows = ref([]);
const allWr = ref([]);
const loadWarranty = async () => {
  const r = await api.get("/cmdb/devices/warranty-expiring/", { params: { within_days: 180 } });
  wrSummary.value = r.summary || {};
  allWr.value = r.rows || [];
  pickWarranty(wSel.value);
};
const pickWarranty = async (k) => {
  wSel.value = k;
  wrRows.value = k === "expired"
    ? allWr.value.filter((x) => x.days_left < 0)
    : allWr.value.filter((x) => x.days_left >= 0 && x.days_left <= Number(k));
};

onMounted(async () => {
  loadGroups();
  loadSw();
  loadWarranty();
  const [rg, md] = await Promise.all([
    api.get("/dcim/regions/", { params: { page_size: 100 } }),
    api.get("/cmdb/models/", { params: { page_size: 100 } }),
  ]);
  regions.value = rg.results || [];
  models.value = md.results || [];
});
</script>
