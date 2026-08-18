<template>
  <el-card style="margin-bottom:12px" body-style="padding:10px 14px">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <b>机房管理</b>
      <div>
        <el-button type="primary" @click="dlg = true">新建（地区/机房/机柜）</el-button>
        <el-button type="danger" plain :disabled="!selected" @click="removeSelected">
          删除选中{{ selected ? "（" + selected.label.split("（")[0] + "）" : "" }}
        </el-button>
        <el-button @click="loadAll">刷新</el-button>
      </div>
    </div>
  </el-card>

  <div style="display:flex;gap:14px;height:calc(100vh - 220px)">
    <el-card style="width:290px" body-style="padding:8px;overflow:auto">
      <template #header><b>位置导航</b></template>
      <el-tree :data="tree" node-key="key" :props="{ label: 'label', children: 'children' }"
               default-expand-all highlight-current @node-click="onClick" />
      <el-empty v-if="!tree.length" description="还没有地区，点右上角新建" :image-size="60" />
    </el-card>

    <el-card v-if="mode === 'rack' && rackId" style="flex:1;overflow:auto">
      <template #header>
        <b>{{ elevation.rack?.name || "" }}</b>
        <span v-if="elevation.rack" style="color:#909399">
          {{ elevation.rack.region }} · {{ elevation.rack.site }} ·
          已用 {{ elevation.summary?.used_u }}U / {{ elevation.rack.u_total }}U
        </span>
      </template>
      <div>
        <div v-for="u in elevation.units || []" :key="u.u" class="unit" :class="u.status"
             @dragover.prevent @drop="onDrop(u)">
          <span class="u-no">{{ u.u }}</span>
          <span v-if="u.status === 'occupied'" class="dev" draggable="true"
                @dragstart="dragPlaced = u.device; dragDevice = null"
                :title="'拖回右侧列表 = 下架；拖到空闲U = 换位'"
                @click="openDevice(u.device)">
            {{ u.device?.name }}
            <el-tag size="small" :type="u.device?.online_status === 'online' ? 'success' : 'info'">
              {{ u.device?.online_status === "online" ? "在线" : "离线" }}</el-tag>
          </span>
          <span v-else-if="u.status === 'reserved'" class="resv">预留：{{ u.reservation?.reason }}</span>
          <span v-else class="free">空闲（拖入设备）</span>
        </div>
      </div>
    </el-card>

    <el-card v-else-if="mode === 'site' && curSite" style="flex:1;overflow:auto" body-style="padding:10px">
      <FloorPlan :site="curSite" @open-rack="openRackFromPlan" @site-updated="onSiteUpdated" />
    </el-card>

    <el-card v-else-if="mode === 'region' && curRegion" style="flex:1;overflow:auto">
      <template #header><b>{{ curRegion.label }}</b> 下的机房（点击进入平面全景）</template>
      <el-row :gutter="12">
        <el-col :span="8" v-for="s in regionSites" :key="s.id" style="margin-bottom:12px">
          <el-card shadow="hover" style="cursor:pointer" @click="openSite(s)">
            <b>{{ s.name }}</b>
            <div style="color:#909399;font-size:13px;margin-top:6px">
              编码 {{ s.code }} · 机柜 {{ racks.filter((r) => r.site === s.id).length }} 个 ·
              已用 {{ racks.filter((r) => r.site === s.id).reduce((a, r) => a + (r.used_u || 0), 0) }}U
            </div>
          </el-card>
        </el-col>
      </el-row>
      <el-empty v-if="!regionSites.length" description="该地区暂无机房" :image-size="60" />
    </el-card>

    <el-card v-else style="flex:1">
      <el-empty description="左侧选择地区（看机房卡片）、机房（看平面全景）或机柜（看 U 位）" />
    </el-card>

    <el-card style="width:270px" body-style="padding:8px;overflow:auto">
      <template #header>待上架设备（拖到机柜 / 设备拖回此处=下架）</template>
      <div class="drop-zone" @dragover.prevent @drop="onDropUnplace">
        <div v-for="d in unplaced" :key="d.id" class="drag-item" draggable="true"
             @dragstart="dragDevice = d; dragPlaced = null" :title="d.name + ' ' + d.rack_units + 'U'">
          <b>{{ d.name }}</b>
          <span style="color:#909399"> {{ d.vendor }} {{ d.rack_units }}U</span>
        </div>
        <div v-if="dragPlaced" class="drop-hint">松开以下架「{{ dragPlaced.name }}」</div>
        <el-empty v-if="!unplaced.length && !dragPlaced" description="无未上架设备" :image-size="50" />
      </div>
    </el-card>
  </div>

  <el-dialog v-model="dlg" title="新建 位置/机房/机柜" width="480">
    <el-form :model="form" label-width="80px">
      <el-form-item label="层级">
        <el-radio-group v-model="form.level">
          <el-radio value="region">地区</el-radio>
          <el-radio value="site">机房</el-radio>
          <el-radio value="rack">机柜</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="名称"><el-input v-model="form.name" placeholder="如：华东 / 核心机房 / A01" /></el-form-item>
      <el-form-item label="编码" v-if="form.level !== 'rack'">
        <el-input v-model="form.code" placeholder="如 cn-east / idc-core" />
      </el-form-item>
      <el-form-item label="U数" v-if="form.level === 'rack'">
        <el-select v-model="form.u_total"><el-option :value="42" /><el-option :value="47" /><el-option :value="50" /></el-select>
      </el-form-item>
      <el-form-item label="所属地区" v-if="form.level === 'site'">
        <el-select v-model="form.region" placeholder="必选">
          <el-option v-for="r in regions" :key="r.id" :label="r.name" :value="r.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="所属机房" v-if="form.level === 'rack'">
        <el-select v-model="form.site" placeholder="必选">
          <el-option v-for="s in sites" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dlg = false">取消</el-button>
      <el-button type="primary" @click="save">创建</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { useRouter } from "vue-router";
import api from "../api";
import FloorPlan from "../components/FloorPlan.vue";

const router = useRouter();
const regions = ref([]); const sites = ref([]); const racks = ref([]);
const rackId = ref(null);
const elevation = ref({});
const unplaced = ref([]);
const dragDevice = ref(null);
const dragPlaced = ref(null);
const dlg = ref(false);
const selected = ref(null);
const mode = ref("rack");            // rack | site | region
const curSite = ref(null);
const curRegion = ref(null);
const regionSites = computed(() =>
  sites.value.filter((s) => s.region === curRegion.value?.id));
const form = reactive({ level: "region", name: "", code: "", u_total: 42, region: null, site: null });

const tree = computed(() => regions.value.map((r) => ({
  key: "r" + r.id, label: r.name, type: "region", id: r.id,
  children: sites.value.filter((s) => s.region === r.id).map((s) => ({
    key: "s" + s.id, label: s.name, type: "site", id: s.id,
    children: racks.value.filter((k) => k.site === s.id).map((k) => ({
      key: "k" + k.id, label: k.name + "（" + (k.used_u || 0) + "U）", type: "rack", id: k.id,
    })),
  })),
})));

const loadElevation = async () => {
  if (!rackId.value) return;
  elevation.value = await api.get("/dcim/racks/" + rackId.value + "/elevation/");
};
const loadUnplaced = async () => {
  const r = await api.get("/cmdb/devices/", { params: { page_size: 100, rack__isnull: true } });
  unplaced.value = r.results || [];
};
const loadAll = async () => {
  const [rg, st, rk] = await Promise.all([
    api.get("/dcim/regions/", { params: { page_size: 100 } }),
    api.get("/dcim/sites/", { params: { page_size: 100 } }),
    api.get("/dcim/racks/", { params: { page_size: 200 } }),
  ]);
  regions.value = rg.results || []; sites.value = st.results || []; racks.value = rk.results || [];
  if (!racks.value.find((k) => k.id === rackId.value)) {
    rackId.value = racks.value.length ? racks.value[0].id : null;
  }
  await Promise.all([loadElevation(), loadUnplaced()]);
};
onMounted(loadAll);

const onClick = (node) => {
  selected.value = node;
  if (node.type === "rack") { mode.value = "rack"; rackId.value = node.id; loadElevation(); }
  else if (node.type === "site") { openSite(sites.value.find((s) => s.id === node.id)); }
  else { mode.value = "region"; curRegion.value = node; }
};

const openSite = (s) => {
  if (!s) return;
  curSite.value = s;
  mode.value = "site";
};
const openRackFromPlan = (id) => {
  mode.value = "rack";
  rackId.value = id;
  loadElevation();
};
const onSiteUpdated = (s) => {
  const i = sites.value.findIndex((x) => x.id === s.id);
  if (i >= 0) sites.value[i] = s;
  curSite.value = s;
};

const TYPE_PATH = { region: "/dcim/regions/", site: "/dcim/sites/", rack: "/dcim/racks/" };
const removeSelected = async () => {
  const n = selected.value;
  if (!n) return;
  const typeNames = { region: "地区", site: "机房", rack: "机柜" };
  try {
    await ElMessageBox.confirm(
      "确认删除" + typeNames[n.type] + "「" + n.label.split("（")[0] + "」？存在下级或设备时会被拒绝。",
      "删除确认", { type: "warning" });
    await api.delete(TYPE_PATH[n.type] + n.id + "/");
    ElMessage.success("已删除");
    selected.value = null;
    await loadAll();
  } catch (e) { /* 取消或后端提示（引用约束等） */ }
};
import { ElMessageBox } from "element-plus";
const openDevice = (d) => router.push("/devices/" + d.id);

const onDrop = async (u) => {
  const dev = dragDevice.value || dragPlaced.value;
  if (!dev) return;
  if (u.status !== "free") { ElMessage.warning("U" + u.u + " 不是空闲位"); return; }
  try {
    await api.post("/cmdb/devices/" + dev.id + "/place/",
                   { rack: rackId.value, rack_start_u: u.u });
    ElMessage.success(dev.name + " 已上架/移动至 U" + u.u);
    dragDevice.value = null;
    dragPlaced.value = null;
    await Promise.all([loadElevation(), loadUnplaced(), loadAll()]);
  } catch (e) { /* interceptor 提示（409 冲突等） */ }
};

const onDropUnplace = async () => {
  const dev = dragPlaced.value;
  dragPlaced.value = null;
  dragDevice.value = null;
  if (!dev) return;
  try {
    await api.patch("/cmdb/devices/" + dev.id + "/", { rack: null, rack_start_u: null });
    ElMessage.success(dev.name + " 已下架（回到待上架列表）");
    await Promise.all([loadElevation(), loadUnplaced(), loadAll()]);
  } catch (e) { /* interceptor 提示 */ }
};

const save = async () => {
  try {
    if (!form.name) { ElMessage.warning("名称必填"); return; }
    if (form.level === "region") {
      if (!form.code) { ElMessage.warning("编码必填（如 cn-east）"); return; }
      await api.post("/dcim/regions/", { name: form.name, code: form.code });
    } else if (form.level === "site") {
      if (!form.code) { ElMessage.warning("编码必填（如 idc-sh）"); return; }
      if (!form.region) { ElMessage.warning("请选择所属地区"); return; }
      await api.post("/dcim/sites/", { name: form.name, code: form.code, region: form.region });
    } else {
      if (!form.site) { ElMessage.warning("请选择所属机房"); return; }
      const r = await api.post("/dcim/racks/", { name: form.name, site: form.site, u_total: form.u_total });
      rackId.value = r.id;
    }
    ElMessage.success("创建成功");
    dlg.value = false;
    form.name = ""; form.code = "";
    await loadAll();
  } catch (e) { /* interceptor 提示 */ }
};
</script>

<style scoped>
.drag-item { padding: 8px; border: 1px dashed #c0c4cc; border-radius: 6px; margin: 4px 0;
             cursor: grab; background: #fafafa; font-size: 13px; }
.drag-item:hover { border-color: #409eff; }
.drop-zone { min-height: 120px; border-radius: 6px; }
.drop-hint { padding: 10px; border: 2px dashed #67c23a; border-radius: 6px;
             color: #67c23a; text-align: center; font-size: 13px; margin: 4px 0; }
.unit { display: flex; align-items: center; gap: 10px; height: 30px; border: 1px solid #dcdfe6;
        border-radius: 4px; margin-bottom: 2px; padding: 0 8px; font-size: 13px; }
.unit.occupied { background: #f0f9eb; border-color: #b3e19d; }
.unit.reserved { background: #fdf6ec; border-color: #f3d19e; }
.unit.free { background: #fafafa; }
.u-no { width: 30px; color: #909399; text-align: right; }
.dev { cursor: pointer; font-weight: 500; display: flex; gap: 8px; align-items: center; }
.resv { color: #e6a23c; }
.free { color: #c0c4cc; }
</style>
