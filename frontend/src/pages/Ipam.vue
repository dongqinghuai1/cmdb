<template>
  <el-tabs v-model="tab">
    <el-tab-pane label="网段 / IP" name="subnet">
      <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
        <el-button type="primary" @click="dlgSubnet = true">新建网段</el-button>
        <el-button @click="dlgArp = true">ARP 导入比对</el-button>
        <el-button @click="loadAll">刷新</el-button>
        <span style="color:#909399;font-size:12px">
          绿=已用 黄=保留 红=冲突 灰=空闲；点击方块登记/编辑
        </span>
      </div>

      <el-table :data="subnets" size="small" stripe highlight-current-row
                @current-change="(r) => r && selectSubnet(r)">
        <el-table-column prop="cidr" label="网段" width="150" />
        <el-table-column label="VLAN" width="90">
          <template #default="{row}">{{ vlanName(row.vlan_id) }}</template>
        </el-table-column>
        <el-table-column prop="gateway" label="网关" width="130" />
        <el-table-column prop="purpose" label="用途" min-width="120" />
        <el-table-column label="使用率" min-width="220">
          <template #default="{row}">
            <el-progress :percentage="pct(row.usage)" :stroke-width="14"
                         :format="() => row.usage.used + '/' + row.usage.total" />
          </template>
        </el-table-column>
        <el-table-column label="冲突" width="70">
          <template #default="{row}">
            <el-badge v-if="row.usage.conflict" :value="row.usage.conflict" type="danger" />
            <span v-else style="color:#c0c4cc">0</span>
          </template>
        </el-table-column>
      </el-table>

      <!-- IP 格子图 -->
      <el-card v-if="cur" style="margin-top:12px" body-style="padding:10px">
        <template #header>
          <b>{{ cur.cidr }}</b> 格子图（{{ cur.usage.used }} 已用 / {{ cur.usage.reserved }} 保留 /
          {{ cur.usage.conflict }} 冲突 / {{ cur.usage.total }} 可用）
          <el-button size="small" style="float:right" @click="loadIps">刷新IP</el-button>
        </template>
        <div class="grid">
          <div v-for="n in totalHosts" :key="n" class="cell" :class="ipMap[hostAt(n)]?.status || 'none'"
               :title="hostAt(n) + ' ' + (ipMap[hostAt(n)] ? statusName(ipMap[hostAt(n)].status) + ' ' + (ipMap[hostAt(n)].mac || '') : '未登记/空闲')"
               @click="clickCell(hostAt(n))">
            <span class="last">{{ hostAt(n).split('.').pop() }}</span>
          </div>
        </div>
      </el-card>
    </el-tab-pane>

    <el-tab-pane label="VLAN" name="vlan">
      <el-button type="primary" @click="dlgVlan = true">新建 VLAN</el-button>
      <el-table :data="vlans" size="small" stripe style="margin-top:10px">
        <el-table-column prop="vid" label="VLAN ID" width="100" />
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="purpose" label="用途" />
      </el-table>
    </el-tab-pane>
  </el-tabs>

  <!-- IP 编辑 -->
  <el-dialog v-model="dlgIp" :title="'IP ' + ipForm.address" width="460">
    <el-form :model="ipForm" label-width="90px">
      <el-form-item label="状态">
        <el-radio-group v-model="ipForm.status">
          <el-radio value="used">已用</el-radio>
          <el-radio value="reserved">保留</el-radio>
          <el-radio value="free">空闲</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="绑定设备">
        <el-select v-model="ipForm.device_id" clearable filterable placeholder="可空">
          <el-option v-for="d in devices" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="MAC"><el-input v-model="ipForm.mac" placeholder="可空" /></el-form-item>
      <el-form-item label="使用人/备注"><el-input v-model="ipForm.assignee" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button v-if="ipForm.id" type="danger" plain @click="delIp">删除</el-button>
      <el-button @click="dlgIp = false">取消</el-button>
      <el-button type="primary" @click="saveIp">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="dlgSubnet" title="新建网段" width="460">
    <el-form :model="snForm" label-width="80px">
      <el-form-item label="网段"><el-input v-model="snForm.cidr" placeholder="10.1.30.0/24" /></el-form-item>
      <el-form-item label="VLAN">
        <el-select v-model="snForm.vlan_id" clearable>
          <el-option v-for="v in vlans" :key="v.id" :label="v.vid + ' ' + v.name" :value="v.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="网关"><el-input v-model="snForm.gateway" /></el-form-item>
      <el-form-item label="用途"><el-input v-model="snForm.purpose" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dlgSubnet = false">取消</el-button>
      <el-button type="primary" @click="saveSubnet">创建</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="dlgVlan" title="新建 VLAN" width="420">
    <el-form :model="vlanForm" label-width="80px">
      <el-form-item label="VLAN ID"><el-input-number v-model="vlanForm.vid" :min="1" :max="4094" /></el-form-item>
      <el-form-item label="名称"><el-input v-model="vlanForm.name" /></el-form-item>
      <el-form-item label="用途"><el-input v-model="vlanForm.purpose" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dlgVlan = false">取消</el-button>
      <el-button type="primary" @click="saveVlan">创建</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="dlgArp" title="ARP 导入比对" width="640">
    <p style="color:#909399;font-size:13px;margin-top:0">
      粘贴交换机 ARP 表（每行 IP 与 MAC，空格分隔）。网段内未登记 IP 自动置“已用”；
      已登记但 MAC 不一致自动标红“冲突”。</p>
    <el-input v-model="arpText" type="textarea" :rows="12"
              placeholder="10.1.10.11  6c92-bf3a-2211&#10;10.1.10.12  00e0-4c68-0123" />
    <template #footer>
      <el-button @click="dlgArp = false">取消</el-button>
      <el-button type="primary" @click="doArp">导入比对</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "../api";

const tab = ref("subnet");
const vlans = ref([]); const subnets = ref([]); const devices = ref([]); const ips = ref([]);
const cur = ref(null);
const dlgIp = ref(false); const dlgSubnet = ref(false); const dlgVlan = ref(false); const dlgArp = ref(false);
const arpText = ref("");
const ipForm = reactive({ id: null, address: "", status: "used", device_id: null, mac: "", assignee: "" });
const snForm = reactive({ cidr: "", vlan_id: null, gateway: "", purpose: "" });
const vlanForm = reactive({ vid: 10, name: "", purpose: "" });

const vlanName = (id) => { const v = vlans.value.find((x) => x.id === id); return v ? v.vid : "-"; };
const pct = (u) => Math.min(Math.round((u.used / Math.max(u.total, 1)) * 100), 100);
const statusName = (s) => ({ used: "已用", reserved: "保留", conflict: "冲突", free: "空闲" }[s] || s);

const loadAll = async () => {
  const [v, s, d] = await Promise.all([
    api.get("/ipam/vlans/", { params: { page_size: 100 } }),
    api.get("/ipam/subnets/", { params: { page_size: 100 } }),
    api.get("/cmdb/devices/", { params: { page_size: 200 } }),
  ]);
  vlans.value = v.results || []; subnets.value = s.results || []; devices.value = d.results || [];
  if (!cur.value && subnets.value.length) selectSubnet(subnets.value[0]);
};

const ipMap = computed(() => {
  const m = {};
  for (const ip of ips.value) m[ip.address] = ip;
  return m;
});
const base = computed(() => cur.value ? cur.value.cidr.split("/")[0].split(".").slice(0, 3).join(".") : "");
const totalHosts = computed(() => {
  if (!cur.value) return 0;
  const mask = parseInt(cur.value.cidr.split("/")[1] || "24");
  const size = Math.pow(2, 32 - mask) - 2;
  return Math.min(size, 512);
});
const hostAt = (n) => base.value + "." + (n + 1);

const selectSubnet = async (s) => { cur.value = s; await loadIps(); };
const loadIps = async () => {
  if (!cur.value) return;
  const r = await api.get("/ipam/ips/", { params: { subnet: cur.value.id, page_size: 600 } });
  ips.value = r.results || [];
};
onMounted(loadAll);

const clickCell = (addr) => {
  const ip = ipMap.value[addr];
  Object.assign(ipForm, ip ? { ...ip } : { id: null, address: addr, status: "used", device_id: null, mac: "", assignee: "" });
  dlgIp.value = true;
};

const saveIp = async () => {
  const payload = { address: ipForm.address, status: ipForm.status, device_id: ipForm.device_id,
                    mac: ipForm.mac || "", assignee: ipForm.assignee || "", subnet: cur.value.id };
  if (ipForm.id) await api.patch("/ipam/ips/" + ipForm.id + "/", payload);
  else await api.post("/ipam/ips/", payload);
  ElMessage.success("已保存"); dlgIp.value = false;
  await Promise.all([loadIps(), loadAll()]);
};

const delIp = async () => {
  await api.delete("/ipam/ips/" + ipForm.id + "/");
  ElMessage.success("已删除"); dlgIp.value = false;
  await Promise.all([loadIps(), loadAll()]);
};

const saveSubnet = async () => {
  await api.post("/ipam/subnets/", { ...snForm });
  ElMessage.success("网段已创建"); dlgSubnet.value = false;
  Object.assign(snForm, { cidr: "", vlan_id: null, gateway: "", purpose: "" });
  loadAll();
};

const saveVlan = async () => {
  await api.post("/ipam/vlans/", { ...vlanForm });
  ElMessage.success("VLAN 已创建"); dlgVlan.value = false;
  Object.assign(vlanForm, { vid: 10, name: "", purpose: "" });
  loadAll();
};

const doArp = async () => {
  const r = await api.post("/ipam/ips/import-arp/", { text: arpText.value });
  const msg = `新增 ${r.created}，更新 ${r.updated}，冲突 ${r.conflict}，网段外 ${r.out_of_scope}`;
  if (r.conflict) ElMessage.warning(msg + "（详情见控制台/冲突标红）");
  else ElMessage.success(msg);
  if (r.conflict_detail?.length) console.table(r.conflict_detail);
  dlgArp.value = false; arpText.value = "";
  await Promise.all([loadIps(), loadAll()]);
};
</script>

<style scoped>
.grid { display: flex; flex-wrap: wrap; gap: 3px; }
.cell { width: 34px; height: 26px; border-radius: 3px; font-size: 10px; display: flex;
        align-items: center; justify-content: center; cursor: pointer; border: 1px solid #dcdfe6;
        background: #f4f4f5; color: #909399; }
.cell:hover { outline: 2px solid #409eff; }
.cell.used { background: #f0f9eb; border-color: #b3e19d; color: #4e8f33; }
.cell.reserved { background: #fdf6ec; border-color: #f3d19e; color: #a3742a; }
.cell.conflict { background: #fef0f0; border-color: #f56c6c; color: #c04f4f; font-weight: 700; }
</style>
