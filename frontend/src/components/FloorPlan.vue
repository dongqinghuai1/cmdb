<template>
  <div style="display:flex;flex-direction:column;gap:10px;height:100%">
    <!-- 工具栏 -->
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <b>{{ site.name }} · 平面全景</b>
      <el-tag size="small">{{ site.code }}</el-tag>
      <el-switch v-model="edit" active-text="编辑模式" />
      <template v-if="edit">
        <el-button v-for="t in TYPES" :key="t.k" size="small" :type="pal === t.k ? 'primary' : 'default'"
                   @click="pal = (pal === t.k ? null : t.k)">{{ t.n }}</el-button>
        <el-input-number v-model="len" :min="2" :max="60" size="small" controls-position="right" style="width:90px" title="机房长(米)" />
        ×
        <el-input-number v-model="wid" :min="2" :max="60" size="small" controls-position="right" style="width:90px" title="机房宽(米)" />
        米
        <el-button size="small" type="primary" @click="save">保存布局</el-button>
      </template>
      <el-button size="small" @click="load">刷新</el-button>
      <span style="color:#c0c4cc;font-size:12px">BUILD=fp6</span>
      <span style="color:#909399;font-size:12px" v-if="edit && pal">点击画布放置「{{ typeName(pal) }}」</span>
    </div>

    <!-- 拖拽实时调试徽标：卡住时请把这行数值发我 -->
    <div v-if="dragBadge" class="dbg">拖拽中 {{ dragBadge.name }}: x={{ dragBadge.x }} y={{ dragBadge.y }}
      w={{ dragBadge.w }} h={{ dragBadge.h }} | 画布 {{ len }}×{{ wid }}m |
      y可到[0 ~ {{ (wid - dragBadge.h).toFixed(1) }}] x可到[0 ~ {{ (len - dragBadge.w).toFixed(1) }}]</div>

    <div style="display:flex;gap:10px;flex:1;min-height:0">
      <!-- 画布 -->
      <div class="canvas-wrap">
        <div ref="canvasRef" class="canvas" :style="canvasStyle" @click.self="onCanvasClick">
          <div v-for="(o, i) in objects" :key="i" class="obj" :class="[o.obj_type, { sel: sel === o, editing: edit }]"
               :style="objStyle(o)" @pointerdown.stop="onDown($event, o)" @click.stop="onObjClick(o)">
            <span class="obj-name">{{ o.name || typeName(o.obj_type) }}</span>
            <div v-if="o.obj_type === 'rack' && rackInfo(o.rack_id)" class="rack-fill"
                 :style="{ height: rackFill(o.rack_id) + '%' }"></div>
            <span v-if="o.obj_type === 'rack' && rackInfo(o.rack_id)" class="rack-u">
              {{ rackInfo(o.rack_id).used_u }}/{{ rackInfo(o.rack_id).u_total }}U
            </span>
            <span v-if="edit" class="rz" title="拖动调整大小"
                  @pointerdown.stop.prevent="onRzDown($event, o)"></span>
            <span v-if="edit" class="coord">({{ o.x }},{{ o.y }}) {{ o.w }}×{{ o.h }}</span>
          </div>
        </div>
        <el-empty v-if="!objects.length && !edit" description="尚无布局，打开「编辑模式」DIY 机房平面图" :image-size="60" />
      </div>

      <!-- 属性面板（编辑模式 + 选中元素） -->
      <div v-if="edit && sel" class="props">
        <b style="font-size:13px">元素属性</b>
        <el-input v-model="sel.name" placeholder="名称" size="small" style="margin-top:8px" />
        <template v-if="sel.obj_type === 'rack'">
          <div style="font-size:12px;color:#909399;margin:8px 0 4px">绑定实体机柜</div>
          <el-select v-model="sel.rack_id" size="small" clearable placeholder="未绑定（纯占位）">
            <el-option v-for="r in racks" :key="r.id" :label="r.name + (boundRacks.has(r.id) && r.id !== sel.rack_id ? '（已被其他元素绑定）' : '')"
                       :value="r.id" :disabled="boundRacks.has(r.id) && r.id !== sel.rack_id" />
          </el-select>
          <div v-if="sel.rack_id" style="font-size:12px;color:#67c23a;margin-top:4px">
            将显示 U 位占用并支持点击进入
          </div>
          <div v-else style="font-size:12px;color:#e6a23c;margin-top:4px">
            未绑定实体机柜：仅作平面占位
          </div>
        </template>
        <div style="font-size:12px;color:#909399;margin:8px 0 4px">尺寸（米）</div>
        <div style="display:flex;gap:6px;align-items:center">
          <el-input-number v-model="sel.w" :min="0.2" :max="len" :step="0.1" size="small" controls-position="right" style="width:100px" />
          ×
          <el-input-number v-model="sel.h" :min="0.2" :max="wid" :step="0.1" size="small" controls-position="right" style="width:100px" />
        </div>
        <div style="font-size:12px;color:#909399;margin:8px 0 4px">位置（米，左上角）</div>
        <div style="display:flex;gap:6px;align-items:center">
          <el-input-number v-model="sel.x" :min="0" :max="len" :step="0.1" size="small" controls-position="right" style="width:100px" />
          <el-input-number v-model="sel.y" :min="0" :max="wid" :step="0.1" size="small" controls-position="right" style="width:100px" />
        </div>
        <el-button size="small" type="danger" plain style="margin-top:10px;width:100%"
                   @click="delSel">删除该元素</el-button>
      </div>
    </div>

    <!-- 机柜 U 位横排概览 -->
    <el-card v-if="racks.length" body-style="padding:8px 12px">
      <div v-for="rk in racks" :key="rk.id" class="hbar" @click="$emit('openRack', rk.id)">
        <span style="width:60px">{{ rk.name }}</span>
        <div class="htrack">
          <div class="hfill" :style="{ width: (rk.used_u || 0) / rk.u_total * 100 + '%' }"></div>
        </div>
        <span style="width:70px;color:#909399">{{ rk.used_u || 0 }}/{{ rk.u_total }}U</span>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, defineEmits, defineProps, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import api from "../api";

const props = defineProps({ site: Object });
const emit = defineEmits(["openRack", "siteUpdated"]);

const TYPES = [
  { k: "rack", n: "机柜" }, { k: "ups", n: "UPS" }, { k: "ap", n: "AP" },
  { k: "power", n: "电箱" }, { k: "fire", n: "消防" }, { k: "door", n: "门" }, { k: "other", n: "其他" },
];
const typeName = (k) => (TYPES.find((t) => t.k === k) || { n: k }).n;

const edit = ref(false);
const pal = ref(null);
const objects = ref([]);
const racks = ref([]);
const len = ref(props.site.floor_len_m || 12);
const wid = ref(props.site.floor_w_m || 8);
const sel = ref(null);
const canvasRef = ref(null);
const SCALE = 38; // px / 米

const canvasStyle = computed(() => ({
  width: len.value * SCALE + "px",
  height: wid.value * SCALE + "px",
  backgroundSize: `${SCALE}px ${SCALE}px`,
}));
const objStyle = (o) => ({
  left: o.x * SCALE + "px", top: o.y * SCALE + "px",
  width: o.w * SCALE + "px", height: o.h * SCALE + "px",
  zIndex: sel.value === o ? 5 : 1,
});
const rackInfo = (id) => racks.value.find((r) => r.id === id);
const rackFill = (id) => {
  const r = rackInfo(id);
  return r ? Math.min(((r.used_u || 0) / r.u_total) * 100, 100) : 0;
};
const boundRacks = computed(() =>
  new Set(objects.value.filter((o) => o.rack_id && o !== sel.value).map((o) => o.rack_id)));

let sizeInit = false;
const sanitize = (o) => {  // 载入时把越界/超尺寸元素拉回画布内（历史数据兜底）
  o.w = clamp(o.w, 0.2, len.value);
  o.h = clamp(o.h, 0.2, wid.value);
  o.x = clamp(o.x, 0, len.value - o.w);
  o.y = clamp(o.y, 0, wid.value - o.h);
};
const load = async () => {
  const [objs, rks] = await Promise.all([
    api.get("/dcim/site-objects/", { params: { site: props.site.id, page_size: 500 } }),
    api.get("/dcim/racks/", { params: { site: props.site.id, page_size: 200 } }),
  ]);
  objects.value = objs.results || [];
  objects.value.forEach(sanitize);
  racks.value = rks.results || [];
  if (!sizeInit) {
    len.value = props.site.floor_len_m || 12;
    wid.value = props.site.floor_w_m || 8;
    sizeInit = true;
  }
  sel.value = null;
};
onMounted(load);

// 切换机房时组件被复用（不重挂载），必须监听 site 变化重新拉取数据
watch(() => props.site && props.site.id, async (nv, ov) => {
  if (nv === ov || nv == null) return;
  if (edit.value) ElMessage.warning("已切换机房，未保存的布局修改已丢弃");
  edit.value = false;
  pal.value = null;
  sel.value = null;
  sizeInit = false;  // 长宽从新机房重新初始化
  await load();
});

const onCanvasClick = (e) => {
  if (!edit.value || !pal.value) { sel.value = null; return; }
  const rect = e.currentTarget.getBoundingClientRect();
  const x = +Math.max((e.clientX - rect.left) / SCALE, 0).toFixed(2);
  const y = +Math.max((e.clientY - rect.top) / SCALE, 0).toFixed(2);
  const isRack = pal.value === "rack";
  const o = { obj_type: pal.value, name: "", rack_id: null, x, y, w: 0.6, h: 1.2, meta: {} };
  if (!isRack) { o.w = 1; o.h = 1; }
  else {
    const free = racks.value.find((r) => !boundRacks.value.has(r.id));
    if (!free) { ElMessage.warning("该机房机柜都已绑定或无机柜，元素将作为纯占位（可在属性面板绑定）"); }
    else { o.rack_id = free.id; o.name = free.name; }
  }
  objects.value.push(o);
  sel.value = o;
};

const snap = (v) => Math.round(v * 10) / 10;
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(hi, lo));

/* window 级监听 + 增量计算：按下记录起点，移动按 Δ 更新；无论指针去哪都不丢、不联动其他元素。 */
let dragCtx = null;  // {o, sx, sy, ox, oy, ow, oh, move}
const dragBadge = ref(null);
const onWinMove = (ev) => {
  if (!dragCtx) return;
  const { o, sx, sy, ox, oy, ow, oh } = dragCtx;
  if (dragCtx.mode === "move") {
    o.x = snap(clamp(ox + (ev.clientX - sx) / SCALE, 0, len.value - o.w));
    o.y = snap(clamp(oy + (ev.clientY - sy) / SCALE, 0, wid.value - o.h));
  } else {
    o.w = snap(clamp(ow + (ev.clientX - sx) / SCALE, 0.2, len.value - o.x));
    o.h = snap(clamp(oh + (ev.clientY - sy) / SCALE, 0.2, wid.value - o.y));
  }
  dragBadge.value = { name: o.name || typeName(o.obj_type), x: o.x, y: o.y, w: o.w, h: o.h };
};
const onWinUp = () => {
  dragCtx = null;
  dragBadge.value = null;
  window.removeEventListener("pointermove", onWinMove);
  window.removeEventListener("pointerup", onWinUp);
  document.body.style.cursor = "";
};
const startDragCtx = (mode, e, o) => {
  dragCtx = { mode, o, sx: e.clientX, sy: e.clientY, ox: o.x, oy: o.y, ow: o.w, oh: o.h };
  window.addEventListener("pointermove", onWinMove);
  window.addEventListener("pointerup", onWinUp);
  document.body.style.cursor = mode === "resize" ? "nwse-resize" : "move";
};

const onDown = (e, o) => {
  sel.value = o;
  if (!edit.value) return;
  e.preventDefault();
  startDragCtx("move", e, o);
};
const onRzDown = (e, o) => {
  sel.value = o;
  startDragCtx("resize", e, o);
};
const onObjClick = (o) => {
  if (!edit.value && o.obj_type === "rack" && o.rack_id) emit("openRack", o.rack_id);
};
const delSel = () => {
  objects.value = objects.value.filter((o) => o !== sel.value);
  sel.value = null;
};

const save = async () => {
  const r = await api.post("/dcim/site-objects/bulk/", {
    site: props.site.id, floor_len_m: len.value, floor_w_m: wid.value,
    objects: objects.value,
  });
  const s = await api.get("/dcim/sites/" + props.site.id + "/");
  if (s.floor_len_m) len.value = s.floor_len_m;
  if (s.floor_w_m) wid.value = s.floor_w_m;
  emit("siteUpdated", s);
  ElMessage.success("布局已保存（" + r.saved + " 个元素，机房 " + len.value + "×" + wid.value + " 米）");
  edit.value = false;
  pal.value = null;
  await load();
};
</script>

<style scoped>
.canvas-wrap { flex: 1; overflow: auto; border: 1px solid #dcdfe6; border-radius: 6px; padding: 10px; background: #fafafa; }
.canvas { position: relative; background: #fff;
  background-image: linear-gradient(#eee 1px, transparent 1px), linear-gradient(90deg, #eee 1px, transparent 1px);
  border: 2px solid #909399; }
.obj { position: absolute; border: 1px solid; border-radius: 4px; font-size: 11px;
  display: flex; align-items: center; justify-content: center; overflow: visible; cursor: pointer;
  user-select: none; text-align: center; touch-action: none; }
.obj.editing { cursor: move; }
.obj.sel { outline: 2px dashed #409eff; }
.obj.rack { background: #ecf5ff; border-color: #409eff; color: #1d64b8; }
.obj.ups { background: #f0f9eb; border-color: #67c23a; color: #4e8f33; }
.obj.ap { background: #f5f0ff; border-color: #9b6ef3; color: #6e4fc7; }
.obj.power { background: #fdf6ec; border-color: #e6a23c; color: #a3742a; }
.obj.fire { background: #fef0f0; border-color: #f56c6c; color: #c04f4f; }
.obj.door, .obj.other { background: #f4f4f5; border-color: #909399; color: #606266; }
.rack-fill { position: absolute; bottom: 0; left: 0; right: 0; background: rgba(64, 158, 255, 0.35); pointer-events: none; }
.obj-name { position: relative; z-index: 1; word-break: break-all; padding: 0 2px; }
.rack-u { position: absolute; bottom: 0; right: 2px; font-size: 10px; color: #333; z-index: 1; }
.rz { position: absolute; right: -1px; bottom: -1px; width: 10px; height: 10px;
      background: #409eff; border-radius: 3px 0 4px 0; cursor: nwse-resize; z-index: 2; }
.coord { position: absolute; top: -16px; left: 0; background: rgba(48, 49, 51, 0.85); color: #fff;
         font-size: 10px; padding: 0 4px; border-radius: 3px; white-space: nowrap; z-index: 4;
         font-family: Consolas, monospace; }
.props { width: 210px; border: 1px solid #dcdfe6; border-radius: 6px; padding: 10px;
         background: #fff; height: fit-content; flex-shrink: 0; }
.dbg { background: #303133; color: #ffd049; font-size: 12px; padding: 4px 10px;
       border-radius: 4px; width: fit-content; font-family: Consolas, monospace; }
.hbar { display: flex; align-items: center; gap: 10px; padding: 4px 0; cursor: pointer; font-size: 13px; }
.hbar:hover { color: #409eff; }
.htrack { flex: 1; height: 12px; background: #f0f2f5; border-radius: 6px; overflow: hidden; }
.hfill { height: 100%; background: linear-gradient(90deg, #409eff, #67c23a); }
</style>
