<template>
  <div style="display:flex;gap:14px;height:100%">
    <el-card style="width:290px" body-style="padding:8px">
      <template #header>
        <b>位置导航</b>
        <el-button size="small" style="float:right" @click="$emit('add')">新建</el-button>
      </template>
      <el-tree :data="tree" node-key="key" :props="{ label: 'label', children: 'children' }"
               default-expand-all highlight-current @node-click="onClick" />
    </el-card>

    <el-card style="flex:1;overflow:auto">
      <template #header>
        <b>{{ elevation.rack?.name || "机柜视图" }}</b>
        <span v-if="elevation.rack">
          {{ elevation.rack.region }} · {{ elevation.rack.site }} ·
          已用 {{ elevation.summary?.used_u }}U / {{ elevation.rack.u_total }}U
        </span>
      </template>
      <div class="rack">
        <div v-for="u in elevation.units || []" :key="u.u" class="unit" :class="u.status"
             @dragover.prevent @drop="onDrop(u)">
          <span class="u-no">{{ u.u }}</span>
          <span v-if="u.status === 'occupied'" class="dev" @click="$emit('openDevice', u.device)">
            {{ u.device?.name }}
            <el-tag size="small" :type="u.device?.online_status === 'online' ? 'success' : 'info'">
              {{ u.device?.online_status === "online" ? "在线" : "离线" }}</el-tag>
          </span>
          <span v-else-if="u.status === 'reserved'" class="resv">预留：{{ u.reservation?.reason }}</span>
          <span v-else class="free">空闲（拖入设备）</span>
        </div>
      </div>
    </el-card>

    <el-card style="width:270px" body-style="padding:8px">
      <template #header>待上架设备（拖到机柜）</template>
      <div v-for="d in unplaced" :key="d.id" class="drag-item" draggable="true"
           @dragstart="dragDevice = d" :title="d.name + ' ' + d.rack_units + 'U'">
        <b>{{ d.name }}</b>
        <span style="color:#909399"> {{ d.vendor }} {{ d.rack_units }}U</span>
      </div>
      <el-empty v-if="!unplaced.length" description="无未上架设备" :image-size="50" />
    </el-card>
  </div>
</template>

<script setup>
import { defineEmits, defineProps, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import api from "../api";

const props = defineProps({ rackId: Number, tree: Array });
const emit = defineEmits(["rackClick", "openDevice", "add"]);
const elevation = ref({});
const unplaced = ref([]);
const dragDevice = ref(null);

const load = async () => {
  if (!props.rackId) return;
  elevation.value = await api.get("/dcim/racks/" + props.rackId + "/elevation/");
};
const loadUnplaced = async () => {
  const r = await api.get("/cmdb/devices/", { params: { page_size: 100, rack__isnull: true } });
  unplaced.value = r.results || [];
};
onMounted(() => { loadUnplaced(); watch(() => props.rackId, load, { immediate: true }); });

const onClick = (node) => { if (node.type === "rack") emit("rackClick", node.id); };

const onDrop = async (u) => {
  if (!dragDevice.value) return;
  if (u.status !== "free") { ElMessage.warning("U" + u.u + " 不是空闲位"); return; }
  try {
    await api.post("/cmdb/devices/" + dragDevice.value.id + "/place/",
                   { rack: props.rackId, rack_start_u: u.u });
    ElMessage.success(dragDevice.value.name + " 已上架 U" + u.u);
    dragDevice.value = null;
    await Promise.all([load(), loadUnplaced()]);
  } catch (e) { /* interceptor 已提示 */ }
};
</script>

<style scoped>
.drag-item { padding: 8px; border: 1px dashed #c0c4cc; border-radius: 6px; margin: 4px 0;
             cursor: grab; background: #fafafa; font-size: 13px; }
.drag-item:hover { border-color: #409eff; }
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
