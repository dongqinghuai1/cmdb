<template>
  <el-tabs v-model="tab" type="border-card">
    <!-- 业务-设备归属矩阵 -->
    <el-tab-pane label="业务设备归属" name="biz">
      <div style="display:flex;gap:10px;margin-bottom:12px">
        <el-tag type="info">业务 {{ bizCount }}</el-tag>
        <el-tag type="success">已归属设备 {{ sum.linked_devices ?? 0 }}</el-tag>
        <el-tag :type="(sum.unassigned_devices||0) > 0 ? 'warning' : 'success'">
          未归属 {{ sum.unassigned_devices ?? 0 }}</el-tag>
        <el-button size="small" style="margin-left:auto" type="primary"
                   @click="$router.push('/devices')">去设备台账认领</el-button>
      </div>
      <el-row :gutter="12">
        <el-col :span="10">
          <el-card shadow="never">
            <template #header><b>业务列表（点击查看成员）</b></template>
            <el-table :data="bizRows" size="small" max-height="440" highlight-current-row
                      @row-click="pickBiz">
              <el-table-column prop="name" label="业务" min-width="110" />
              <el-table-column prop="code" label="编码" width="90" />
              <el-table-column label="等级" width="70">
                <template #default="{row}">
                  <el-tag size="small" :type="row.importance==='critical' ? 'danger'
                          : row.importance==='high' ? 'warning' : 'info'">{{ row.importance }}</el-tag></template>
              </el-table-column>
              <el-table-column prop="device_count" label="设备" width="70" />
              <el-table-column prop="regions" label="覆盖区域" min-width="90">
                <template #default="{row}">{{ (row.regions||[]).join("、") || "-" }}</template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
        <el-col :span="14">
          <el-card shadow="never">
            <template #header>
              <div style="display:flex;justify-content:space-between;align-items:center">
                <b>成员设备{{ curBiz ? "：" + curBiz.name : "（点左表选择）" }}</b>
                <el-button size="small" type="primary" :disabled="!curBiz" @click="openAdd">
                  添加设备</el-button>
              </div>
            </template>
            <el-table :data="members" size="small" max-height="440" @row-click="rowGo">
              <el-table-column prop="name" label="设备" min-width="120" />
              <el-table-column prop="manage_ip" label="管理IP" width="120" />
              <el-table-column prop="region_name" label="区域" width="90" />
              <el-table-column prop="site_name" label="站点" width="90" />
              <el-table-column prop="owner_name" label="责任人" width="90" />
              <el-table-column label="操作" width="80" align="center">
                <template #default="{row}">
                  <el-button link type="danger" @click.stop="removeMember([row.id])">移除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
      </el-row>
      <el-dialog v-model="addDlg" title="添加设备到业务（可多选）" width="640px">
        <el-input v-model="addQ" placeholder="按名称/管理IP 过滤" clearable style="margin-bottom:8px" />
        <el-table :data="candFiltered" size="small" max-height="360" @selection-change="onSelection">
          <el-table-column type="selection" width="44" />
          <el-table-column prop="name" label="设备" min-width="120" />
          <el-table-column prop="manage_ip" label="管理IP" width="120" />
          <el-table-column prop="region_name" label="区域" width="90" />
          <el-table-column prop="site_name" label="站点" width="90" />
        </el-table>
        <template #footer>
          <el-button @click="addDlg=false">取消</el-button>
          <el-button type="primary" :disabled="!selIds.length" @click="confirmAdd">加入（{{ selIds.length }}）</el-button>
        </template>
      </el-dialog>
    </el-tab-pane>

    <!-- 形态与系统清单 -->
    <el-tab-pane label="形态与系统清单" name="sys">
      <el-row :gutter="12">
        <el-col :span="8">
          <el-card shadow="never">
            <template #header><b>设备形态</b></template>
            <div v-for="m in sum2.morph || []" :key="m.is_virtual" style="display:flex;gap:8px;margin-bottom:8px">
              <el-tag size="small" :type="m.is_virtual ? 'info' : 'success'">{{ m.label }}</el-tag>
              <b>{{ m.count }}</b>
            </div>
          </el-card>
          <el-card shadow="never" style="margin-top:12px">
            <template #header><b>型号类别</b></template>
            <el-table :data="sum2.model_cat || []" size="small" max-height="300">
              <el-table-column prop="model__name" label="型号" min-width="100" />
              <el-table-column prop="model__code" label="编码" width="80" />
              <el-table-column prop="model__category" label="类别" width="80" />
              <el-table-column prop="c" label="数量" width="60" />
            </el-table>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="never">
            <template #header><b>系统/内核版本（sw_version）</b></template>
            <el-table :data="sum2.os || []" size="small" max-height="380" @row-click="osClick">
              <el-table-column prop="sw_version" label="版本" min-width="150" />
              <el-table-column prop="c" label="数量" width="70" />
            </el-table>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="never">
            <template #header><b>厂商与用途</b></template>
            <div style="margin-bottom:8px">
              <el-tag v-for="v in sum2.vendor || []" :key="v.vendor" size="small"
                      style="margin:2px 6px 2px 0">{{ v.vendor }} ×{{ v.c }}</el-tag>
            </div>
            <el-divider style="margin:10px 0" />
            <div>
              <el-tag v-for="u in sum2.usage || []" :key="u.usage_tag" size="small" type="info"
                      style="margin:2px 6px 2px 0">{{ u.usage_tag }} ×{{ u.c }}</el-tag>
            </div>
          </el-card>
        </el-col>
      </el-row>
      <el-card shadow="never" style="margin-top:12px">
        <template #header>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <b>设备明细</b>
            <el-select v-model="f.virtual" size="small" style="width:120px"
                       @change="loadDevs">
              <el-option label="全部形态" value="" /><el-option label="物理机" value="0" />
              <el-option label="虚拟机/云主机" value="1" /></el-select>
            <el-select v-model="f.cat" size="small" style="width:130px" clearable placeholder="型号类别"
                       @change="loadDevs">
              <el-option v-for="c in CATS" :key="c" :label="c" :value="c" /></el-select>
            <el-input v-model="f.q" size="small" style="width:200px" placeholder="设备名/IP 过滤"
                      clearable @keyup.enter="loadDevs" />
            <el-button size="small" type="primary" @click="loadDevs">过滤</el-button>
            <span style="margin-left:auto;color:#909399">共 {{ devs.length }} 台（行点击进 360）</span>
          </div>
        </template>
        <el-table :data="devs" size="small" max-height="360" @row-click="rowGo">
          <el-table-column prop="name" label="设备" min-width="130" />
          <el-table-column prop="manage_ip" label="管理IP" width="120" />
          <el-table-column prop="model_code" label="型号" width="90" />
          <el-table-column prop="sw_version" label="系统版本" min-width="120" />
          <el-table-column label="形态" width="70">
            <template #default="{row}">
              <el-tag size="small" :type="row.is_virtual ? 'info' : 'success'">
                {{ row.is_virtual ? "虚机" : "物理" }}</el-tag></template>
          </el-table-column>
        </el-table>
      </el-card>
    </el-tab-pane>
  </el-tabs>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "../api";

const router = useRouter();
const tab = ref("biz");
const sum = ref({});
const bizRows = ref([]);
const bizCount = computed(() => (bizRows.value || []).length);
const curBiz = ref(null);
const members = ref([]);
const addDlg = ref(false);
const addQ = ref("");
const cand = ref([]);
const selIds = ref([]);
const sum2 = ref({});
const CATS = ["network", "security", "wireless", "server", "facility", "terminal"];
const f = reactive({ virtual: "", cat: "", q: "" });
const devs = ref([]);

const loadSum = async () => {
  sum.value = await api.get("/cmdb/devices/business-summary/");
  bizRows.value = sum.value.businesses || [];
};
const pickBiz = async (b) => {
  curBiz.value = b;
  const r = await api.get("/cmdb/devices/", { params: { business_id: b.id, page_size: 500 } });
  members.value = r.results || [];
};
const openAdd = async () => {
  addDlg.value = true;
  addQ.value = "";
  const r = await api.get("/cmdb/devices/", { params: { page_size: 500 } });
  const memIds = new Set(members.value.map((m) => m.id));
  cand.value = (r.results || []).filter((d) => !memIds.has(d.id));
  selIds.value = [];
};
const candFiltered = computed(() => {
  const q = addQ.value.trim().toLowerCase();
  return q ? cand.value.filter((d) => (d.name || "").toLowerCase().includes(q)
                                 || (d.manage_ip || "").includes(q)) : cand.value;
});
const onSelection = (rows) => { selIds.value = rows.map((r) => r.id); };
const confirmAdd = async () => {
  await api.post("/cmdb/devices/business-assign/", {
    business_id: curBiz.value.id, device_ids: selIds.value, action: "add",
  });
  ElMessage.success("已加入 " + selIds.value.length + " 台");
  addDlg.value = false;
  loadSum();
  pickBiz(curBiz.value);
};
const removeMember = async (ids) => {
  await ElMessageBox.confirm(`从业务「${curBiz.value.name}」移除 ${ids.length} 台设备？`, "确认", { type: "warning" });
  await api.post("/cmdb/devices/business-assign/", {
    business_id: curBiz.value.id, device_ids: ids, action: "remove",
  });
  ElMessage.success("已移除");
  loadSum();
  pickBiz(curBiz.value);
};
const rowGo = (row) => router.push("/devices/" + row.id);

const loadSys = async () => { sum2.value = await api.get("/cmdb/devices/system-summary/"); };
const osClick = async (row) => {
  f.q = "";
  const r = await api.get("/cmdb/devices/", { params: { page_size: 500 } });
  devs.value = (r.results || []).filter((d) => d.sw_version === row.sw_version);
};
const loadDevs = async () => {
  const params = { page_size: 500 };
  if (f.virtual !== "") params.is_virtual = f.virtual;
  if (f.cat) params.model_category = f.cat;
  const r = await api.get("/cmdb/devices/", { params });
  let rows = r.results || [];
  const q = f.q.trim().toLowerCase();
  if (q) rows = rows.filter((d) => (d.name || "").toLowerCase().includes(q)
                              || (d.manage_ip || "").includes(q));
  devs.value = rows;
};
onMounted(() => { loadSum(); loadSys(); });
</script>
