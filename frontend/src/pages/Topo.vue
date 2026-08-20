<template>
  <el-card>
    <div style="display:flex;gap:10px;align-items:center;margin-bottom:10px;flex-wrap:wrap">
      <b>网络拓扑</b>
      <el-select v-model="regionId" placeholder="全部地区" clearable style="width:150px" @change="siteId = null; load()">
        <el-option v-for="r in regions" :key="r.id" :label="r.name" :value="r.id" />
      </el-select>
      <el-select v-model="siteId" placeholder="全部机房" clearable style="width:150px" @change="load">
        <el-option v-for="s in siteOptions" :key="s.id" :label="s.name" :value="s.id" />
      </el-select>
      <el-button type="primary" @click="load">刷新</el-button>
      <span v-if="stats" style="color:#909399;font-size:13px">
        设备 {{ stats.devices }} · 未纳管 {{ stats.unmanaged }} · 链路 {{ stats.links }}
      </span>
      <span style="color:#909399;font-size:12px;margin-left:auto">拖拽画布/滚轮缩放/拖动节点 · 点击节点进设备详情</span>
    </div>
    <div ref="container" style="height:calc(100vh - 260px);border:1px solid #dcdfe6;border-radius:6px;background:#fafbfc"></div>
    <el-empty v-if="loaded && !stats?.devices" description="暂无设备或 LLDP 数据，先在台账录入设备并运行邻居发现" />
    <div style="margin-top:8px;display:flex;gap:14px;font-size:12px;color:#606266">
      <span><i style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#67c23a"></i> 在线</span>
      <span><i style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#f56c6c"></i> 离线</span>
      <span><i style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#e6a23c"></i> 采集异常</span>
      <span><i style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#909399"></i> 未纳管/未知</span>
      <span>红圈 = 有活跃告警</span>
    </div>
  </el-card>
</template>

<script setup>
import G6 from "@antv/g6";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import api from "../api";

const router = useRouter();
const container = ref(null);
const regions = ref([]); const sites = ref([]);
const regionId = ref(null); const siteId = ref(null);
const stats = ref(null); const loaded = ref(false);
let graph = null;

const siteOptions = computed(() =>
  sites.value.filter((s) => !regionId.value || s.region === regionId.value));

const COLORS = { online: "#67c23a", offline: "#f56c6c", collect_error: "#e6a23c", unknown: "#909399" };

const load = async () => {
  const params = {};
  if (siteId.value) params.site = siteId.value;
  else if (regionId.value) params.region = regionId.value;
  const data = await api.get("/topo/graph/", { params });
  stats.value = data.stats;
  loaded.value = true;
  render(data);
};

const render = (data) => {
  if (graph) { graph.destroy(); graph = null; }
  if (!container.value) return;
  const nodes = data.nodes.map((n) => ({
    id: String(n.id),
    label: (n.label || "").slice(0, 12),
    size: n.managed ? 36 : 26,
    style: {
      fill: COLORS[n.online] || COLORS.unknown,
      stroke: n.alert_severity > 0 ? "#f56c6c" : "#fff",
      lineWidth: n.alert_severity > 0 ? 4 : 2,
    },
    labelCfg: { style: { fill: "#303133", fontSize: 11, background: { fill: "#fff", padding: [2, 4, 2, 4] } } },
    _meta: n,
  }));
  const edges = data.edges.map((e, i) => ({
    id: "e" + i,
    source: String(e.source),
    target: String(e.target),
    label: e.label || "",
    style: { stroke: e.kind === "cable" ? "#909399" : "#409eff",
             lineWidth: 1.5, endArrow: false, lineDash: e.kind === "cable" ? [4, 4] : null },
    labelCfg: { autoRotate: true, style: { fill: "#909399", fontSize: 9 } },
  }));
  graph = new G6.Graph({
    container: container.value,
    layout: { type: "force", linkDistance: 130, nodeStrength: -80, collide: 40, alphaDecay: 0.028 },
    modes: { default: ["drag-canvas", "zoom-canvas", "drag-node"] },
    defaultNode: { type: "circle" },
    defaultEdge: { type: "line" },
  });
  graph.data({ nodes, edges });
  graph.render();
  graph.on("node:click", (evt) => {
    const meta = evt.item.getModel()._meta;
    if (meta && meta.managed && typeof meta.id === "number") router.push("/devices/" + meta.id);
  });
};

onMounted(async () => {
  const [rg, st] = await Promise.all([
    api.get("/dcim/regions/", { params: { page_size: 100 } }),
    api.get("/dcim/sites/", { params: { page_size: 100 } }),
  ]);
  regions.value = rg.results || [];
  sites.value = st.results || [];
  await load();
});
onBeforeUnmount(() => { if (graph) graph.destroy(); });
</script>
