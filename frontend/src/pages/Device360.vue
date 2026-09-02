<template>
  <el-card v-if="dev">
    <template #header>
      <b>{{ dev.name }}</b>
      <el-tag style="margin-left:10px" :type="dev.online_status==='online'?'success':'info'">
        {{ dev.online_status }}</el-tag>
      <el-tag style="margin-left:6px">{{ dev.model_name }}</el-tag>
      <el-tag v-if="dev.rack_name" style="margin-left:6px" type="warning">
        {{ dev.rack_name }} U{{ dev.rack_start_u }}（{{ dev.rack_units }}U）</el-tag>
    </template>
    <el-descriptions :column="3" border size="small">
      <el-descriptions-item label="SN">{{ dev.sn || "-" }}</el-descriptions-item>
      <el-descriptions-item label="管理IP">{{ dev.manage_ip || "-" }}</el-descriptions-item>
      <el-descriptions-item label="品牌/型号">{{ dev.vendor }} {{ dev.hw_model }}</el-descriptions-item>
      <el-descriptions-item label="系统版本">{{ dev.sw_version || "-" }}</el-descriptions-item>
      <el-descriptions-item label="位置">{{ dev.region_name }} / {{ dev.site_name }}</el-descriptions-item>
      <el-descriptions-item label="生命周期">{{ dev.lifecycle_status }}</el-descriptions-item>
      <el-descriptions-item label="用途标签">{{ dev.usage_tag }}</el-descriptions-item>
      <el-descriptions-item label="占用状态">{{ dev.usage_status }}</el-descriptions-item>
      <el-descriptions-item label="采集驱动">{{ dev.driver_type || "-" }}</el-descriptions-item>
      <el-descriptions-item label="保修到期">{{ dev.warranty_until || "-" }}</el-descriptions-item>
      <el-descriptions-item label="责任人">{{ dev.owner_name || "-" }}</el-descriptions-item>
      <el-descriptions-item label="最近在线">{{ (dev.last_seen_at||"").replace("T"," ").slice(0,19) || "-" }}</el-descriptions-item>
    </el-descriptions>
  </el-card>

  <el-card style="margin-top:14px">
    <template #header>
      <b>资产生命周期</b>
      <el-tag style="margin-left:10px" size="small" :type="lcTagType(dev.lifecycle_status)">
        {{ LIFECYCLE[dev.lifecycle_status] || dev.lifecycle_status }}</el-tag>
      <span style="margin-left:16px;font-size:13px">
        保修到期 {{ dev.warranty_until || "未设置" }}
        <b v-if="dev.warranty_until" :style="{color: warrantyColor}">
          （{{ warrantyDays >= 0 ? "剩余 " + warrantyDays + " 天" : "已过期 " + (-warrantyDays) + " 天" }}）</b>
      </span>
    </template>
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap">
      <span style="font-size:13px;color:#606266">流转到：</span>
      <el-select v-model="lcNew" size="small" style="width:170px" placeholder="选择目标状态">
        <el-option v-for="(l, v) in LIFECYCLE" :key="v" :label="l" :value="v"
                   :disabled="v === dev.lifecycle_status" />
      </el-select>
      <el-button size="small" type="primary" :disabled="!lcNew" @click="lcSet">记录流转</el-button>
      <el-button size="small" type="success" style="margin-left:auto" @click="evDlg=true">新增资产事件</el-button>
    </div>
    <el-table :data="assetEvents" size="small" max-height="300">
      <el-table-column label="时间" width="160">
        <template #default="{row}">{{ fmt2(row.occurred_at) }}</template>
      </el-table-column>
      <el-table-column label="事件" width="110">
        <template #default="{row}">
          <el-tag size="small" :type="EVT_TYPE[row.event_type]?.t || 'info'">
            {{ EVT_TYPE[row.event_type]?.l || row.event_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="operator" label="操作人" width="100" />
      <el-table-column prop="counterparty" label="对方/单号" width="130" />
      <el-table-column label="备注" min-width="140">
        <template #default="{row}">{{ (row.detail && row.detail.note) || "-" }}</template>
      </el-table-column>
    </el-table>
    <el-dialog v-model="evDlg" title="新增资产事件" width="460px">
      <el-form label-width="80px" size="small">
        <el-form-item label="事件类型" required>
          <el-select v-model="evf.event_type" style="width:100%">
            <el-option v-for="(x, v) in EVT_TYPE" :key="v" :label="x.l" :value="v" />
          </el-select>
        </el-form-item>
        <el-form-item label="对方/单号"><el-input v-model="evf.counterparty" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="evf.note" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="evDlg=false">取消</el-button>
        <el-button type="primary" @click="addEv">保存</el-button></template>
    </el-dialog>
  </el-card>

  <el-card style="margin-top:14px">
    <template #header>接口（{{ interfaces.length }}）</template>
    <el-table :data="interfaces" size="small" stripe max-height="420">
      <el-table-column prop="name" label="接口" min-width="140" />
      <el-table-column prop="oper_status" label="状态" width="80">
        <template #default="{row}">
          <el-tag size="small" :type="row.oper_status==='up'?'success':'info'">{{ row.oper_status || "-" }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="if_alias" label="描述" min-width="140" />
      <el-table-column label="入流量" width="110">
        <template #default="{row}">{{ fmt(row.stat?.in_bps) }}</template>
      </el-table-column>
      <el-table-column label="出流量" width="110">
        <template #default="{row}">{{ fmt(row.stat?.out_bps) }}</template>
      </el-table-column>
      <el-table-column label="错包速率" width="110">
        <template #default="{row}">{{ row.stat?.in_errors_rate || 0 }} /s</template>
      </el-table-column>
      <el-table-column label="光功率(dBm)" width="130">
        <template #default="{row}">{{ row.stat?.optical_tx_dbm ?? "-" }} / {{ row.stat?.optical_rx_dbm ?? "-" }}</template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-card style="margin-top:14px">
    <template #header>维保 / 合同 License（{{ licenses.length }}）</template>
    <div style="margin-bottom:8px"><el-button size="small" type="primary" @click="licenseDlg=true">新增</el-button></div>
    <el-table :data="licenses" size="small" stripe>
      <el-table-column prop="license_type" label="类型" width="140" />
      <el-table-column prop="seats" label="授权数" width="90" />
      <el-table-column prop="expire_at" label="到期" width="120" />
      <el-table-column prop="supplier" label="供应商" min-width="120" />
      <el-table-column prop="contract_no" label="合同号" width="140" />
      <el-table-column prop="remark" label="备注" min-width="140" />
      <el-table-column label="操作" width="80">
        <template #default="{row}">
          <el-button size="small" link type="danger" @click="delLicense(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-dialog v-model="licenseDlg" title="新增维保/合同" width="440px">
      <el-form label-width="80px" size="small">
        <el-form-item label="类型" required>
          <el-input v-model="lf.license_type" placeholder="如 OS / Firewall / WLC" />
        </el-form-item>
        <el-form-item label="授权数"><el-input-number v-model="lf.seats" :min="1" /></el-form-item>
        <el-form-item label="到期"><el-date-picker v-model="lf.expire_at" type="date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item>
        <el-form-item label="供应商"><el-input v-model="lf.supplier" /></el-form-item>
        <el-form-item label="合同号"><el-input v-model="lf.contract_no" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="lf.remark" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="licenseDlg=false">取消</el-button>
        <el-button type="primary" @click="addLicense">保存</el-button></template>
    </el-dialog>
  </el-card>

  <el-card style="margin-top:14px">
    <template #header>附件（{{ attachments.length }}）</template>
    <el-upload :show-file-list="false" :http-request="doUpload" style="margin-bottom:8px">
      <el-button size="small" type="primary">上传附件（≤25MB）</el-button>
    </el-upload>
    <el-table :data="attachments" size="small" stripe>
      <el-table-column prop="file_name" label="文件名" min-width="200" show-overflow-tooltip />
      <el-table-column prop="file_type" label="分类" width="90" />
      <el-table-column label="大小" width="90">
        <template #default="{row}">{{ (row.size / 1024).toFixed(1) }} KB</template>
      </el-table-column>
      <el-table-column prop="uploaded_by" label="上传人" width="100" />
      <el-table-column prop="created_at" label="时间" width="160">
        <template #default="{row}">{{ (row.created_at || "").replace("T", " ").slice(0, 19) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="130">
        <template #default="{row}">
          <el-button size="small" link type="primary" @click="download(row)">下载</el-button>
          <el-button size="small" link type="danger" @click="delAttachment(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-card style="margin-top:14px">
    <template #header>变更历史（{{ history.length }}）</template>
    <el-table :data="history" size="small" stripe max-height="360">
      <el-table-column prop="created_at" label="时间" width="170">
        <template #default="{row}">{{ (row.created_at || "").replace("T", " ").slice(0, 19) }}</template>
      </el-table-column>
      <el-table-column prop="action" label="动作" width="100">
        <template #default="{row}">
          <el-tag size="small" :type="{create:'success',update:'warning',delete:'danger',restore:'primary',purge:'danger'}[row.action] || 'info'">
            {{ row.action }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="username" label="操作人" width="110" />
      <el-table-column prop="source_ip" label="来源IP" width="130" />
    </el-table>
  </el-card>

  <el-card style="margin-top:14px">
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <b>技术概览（采集数据 + 扩展入口）</b>
        <el-button size="small" type="primary" @click="openParse">粘贴输出解析</el-button>
      </div>
    </template>
    <div style="display:flex;gap:12px;flex-wrap:wrap">
      <el-card shadow="never" style="flex:1;min-width:280px">
        <template #header>VLAN（{{ tech.vlans?.length || 0 }}）</template>
        <template v-if="tech.vlans && tech.vlans.length">
          <el-tag v-for="v in tech.vlans" :key="v" size="small" style="margin:2px 6px 2px 0">VLAN {{ v }}</el-tag>
        </template>
        <el-empty v-else description="暂无" :image-size="46" />
      </el-card>
      <el-card shadow="never" style="flex:1;min-width:280px">
        <template #header>路由快照（{{ tech.routes?.length || 0 }} 条）</template>
        <template v-if="tech.routes && tech.routes.length">
          <div style="color:#909399;font-size:12px;margin-bottom:6px">
            快照时间：{{ fmt2(tech.route_meta?.snapshot_at) }}
          </div>
          <pre style="max-height:220px;overflow:auto;margin:0;font-size:12px;white-space:pre-wrap">
{{ (tech.routes || []).slice(0, 120).map(r => JSON.stringify(r)).join("\n") }}</pre>
        </template>
        <el-empty v-else description="暂无（待路由采集）" :image-size="46" />
      </el-card>
    </div>
    <div style="margin-top:12px">
      <b style="font-size:13px">OSPF/BGP 邻居（{{ tech.neighbors?.length || 0 }}）</b>
      <el-table v-if="tech.neighbors && tech.neighbors.length" :data="tech.neighbors" size="small" max-height="240"
                style="margin-top:6px">
        <el-table-column prop="protocol" label="协议" width="70" />
        <el-table-column prop="vrf" label="VRF" width="90" />
        <el-table-column prop="neighbor_addr" label="邻居" width="140" />
        <el-table-column prop="state" label="状态" width="110" />
        <el-table-column label="最近在线" min-width="140">
          <template #default="{row}">{{ fmt2(row.last_seen_at) }}</template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无邻居数据" :image-size="46" />
    </div>
    <div v-if="tech.ap" style="margin-top:12px">
      <b style="font-size:13px">无线 AP 信息</b>
      <el-descriptions :column="4" border size="small" style="margin-top:6px">
        <el-descriptions-item label="AP名">{{ tech.ap.ap_name }}</el-descriptions-item>
        <el-descriptions-item label="AP IP">{{ tech.ap.ap_ip || "-" }}</el-descriptions-item>
        <el-descriptions-item label="型号">{{ tech.ap.ap_model }}</el-descriptions-item>
        <el-descriptions-item label="客户端">{{ tech.ap.client_count }}</el-descriptions-item>
        <el-descriptions-item label="2.4G信道">{{ tech.ap.channel_2g || "-" }}</el-descriptions-item>
        <el-descriptions-item label="5G信道">{{ tech.ap.channel_5g || "-" }}</el-descriptions-item>
        <el-descriptions-item label="上行交换机">#{{ tech.ap.uplink_switch_id || "-" }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ tech.ap.status }}</el-descriptions-item>
      </el-descriptions>
    </div>
    <div style="margin-top:12px">
      <b style="font-size:13px">登录会话（{{ tech.sessions?.length || 0 }}）</b>
      <el-table v-if="tech.sessions && tech.sessions.length" :data="tech.sessions" size="small" max-height="240"
                style="margin-top:6px">
        <el-table-column prop="username" label="用户" width="110" />
        <el-table-column prop="source_ip" label="来源IP" width="130" />
        <el-table-column label="登录时间" min-width="150">
          <template #default="{row}">{{ fmt2(row.login_at) }}</template>
        </el-table-column>
        <el-table-column label="登出时间" min-width="150">
          <template #default="{row}">{{ fmt2(row.logout_at) || "在线" }}</template>
        </el-table-column>
        <el-table-column prop="session_type" label="类型" width="90" />
        <el-table-column prop="result" label="结果" width="80" />
      </el-table>
      <el-empty v-else description="暂无会话记录" :image-size="46" />
    </div>
    <div style="margin-top:12px;display:flex;gap:12px;flex-wrap:wrap">
      <el-card v-for="(ext, k) in tech.extensions || {}" :key="k" shadow="never"
               style="flex:1;min-width:300px">
        <template #header>
          <b>{{ k.toUpperCase() }}</b>
          <el-tag v-if="ext.supported" size="small" type="success" style="margin-left:8px">已采集</el-tag>
          <el-tag v-else size="small" type="info" style="margin-left:8px">未接入</el-tag>
        </template>
        <template v-if="ext.supported">
          <div style="color:#909399;font-size:12px;margin-bottom:6px">
            快照时间：{{ fmt2(ext.updated_at) }}
          </div>
          <pre style="max-height:180px;overflow:auto;margin:0;font-size:12px;white-space:pre-wrap">
{{ JSON.stringify(ext.payload, null, 1).slice(0, 1600) }}</pre>
        </template>
        <el-empty v-else :description="ext.note || '待采集驱动接入'" :image-size="46" />
      </el-card>
    </div>
  </el-card>

  <el-dialog v-model="parseDlg" title="粘贴设备输出解析（tech-parse 采集驱动）" width="720px" top="5vh">
    <el-form label-width="90px" size="small">
      <el-form-item label="品类" required>
        <el-select v-model="parseKind" style="width:220px" @change="parseResult=null">
          <el-option v-for="(h, k) in PARSE_KINDS" :key="k" :label="h.label + ' — ' + h.cmd" :value="k" />
        </el-select>
      </el-form-item>
      <el-form-item label="设备输出" required>
        <el-input v-model="parseText" type="textarea" :rows="9" :placeholder="PARSE_KINDS[parseKind].hint" />
      </el-form-item>
      <el-form-item v-if="parseResult">
        <div style="width:100%">
          <div style="margin-bottom:6px">
            <el-tag type="success" size="small">解析到 {{ parseResult.count }} 条</el-tag>
            <el-tag v-for="(c, k) in parseResult.summary || {}" :key="k" size="small"
                    type="info" style="margin-left:8px">{{ k }} {{ c }}</el-tag>
            <el-tag v-if="parseResult.saved" type="success" size="small" style="margin-left:8px">
              已保存快照 #{{ parseResult.snapshot_id }}</el-tag>
          </div>
          <pre style="max-height:240px;overflow:auto;margin:0;font-size:12px;white-space:pre-wrap">
{{ JSON.stringify(parseResult.rows || [], null, 1).slice(0, 2000) }}</pre>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="parseDlg=false">关闭</el-button>
      <el-button :disabled="!parseText.trim()" @click="doParse(false)">解析预览</el-button>
      <el-button type="primary" :disabled="!(parseResult && parseResult.ok && !parseResult.saved)"
                 @click="doParse(true)">保存为快照</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "../api";

const route = useRoute();
const devId = route.params.id;
const dev = ref(null);
const interfaces = ref([]);
const LIFECYCLE = { planning: "规划", purchasing: "采购中", in_stock: "到货入库", deployed: "上架运行",
                    repairing: "维修中", spare: "备件库", retired: "报废" };
const EVT_TYPE = { purchase: { l: "采购", t: "info" }, in_stock: { l: "入库", t: "success" },
                   deploy: { l: "部署上线", t: "success" }, repair: { l: "维修", t: "warning" },
                   borrow: { l: "借出", t: "warning" }, return: { l: "归还", t: "" },
                   spare: { l: "转备件", t: "" }, retire: { l: "报废", t: "danger" } };
const lcNew = ref(null);
const evDlg = ref(false);
const assetEvents = ref([]);
const evf = reactive({ event_type: "deploy", counterparty: "", note: "" });
const warrantyDays = ref(null);
const warrantyColor = ref("#67C23A");
const calcWarranty = () => {
  if (!dev.value?.warranty_until) return;
  const d = new Date(dev.value.warranty_until + "T00:00:00");
  warrantyDays.value = Math.ceil((d - Date.now()) / 86400000);
  warrantyColor.value = warrantyDays.value < 0 ? "#F56C6C"
    : warrantyDays.value <= 90 ? "#E6A23C" : "#67C23A";
};
const lcTagType = (s) => ({ planning: "info", purchasing: "", in_stock: "success", deployed: "success",
                            repairing: "warning", spare: "info", retired: "danger" }[s] || "info");
const loadAssetEvents = async () => {
  assetEvents.value = (await api.get(`/cmdb/devices/${devId}/asset-events/`)) || [];
};
const lcSet = async () => {
  const r = await api.post(`/cmdb/devices/${devId}/lifecycle/`, { lifecycle_status: lcNew.value });
  ElMessage.success("已流转为 " + (LIFECYCLE[r.lifecycle_status] || r.lifecycle_status));
  dev.value.lifecycle_status = r.lifecycle_status;
  lcNew.value = null;
  loadAssetEvents();
};
const addEv = async () => {
  await api.post(`/cmdb/devices/${devId}/asset-events/`, {
    event_type: evf.event_type, counterparty: evf.counterparty,
    detail: evf.note ? { note: evf.note } : {},
  });
  ElMessage.success("已记录");
  evDlg.value = false;
  Object.assign(evf, { event_type: "deploy", counterparty: "", note: "" });
  loadAssetEvents();
};
const licenses = ref([]);
const attachments = ref([]);
const history = ref([]);
const tech = ref({ vlans: [], neighbors: [], sessions: [], routes: [], ap: null, extensions: {} });
const licenseDlg = ref(false);
const lf = reactive({ license_type: "", seats: 1, expire_at: null, supplier: "", contract_no: "", remark: "" });

const fmt = (bps) => {
  if (!bps) return "0";
  const units = ["b", "Kb", "Mb", "Gb"];
  let i = 0, v = bps;
  while (v >= 1000 && i < 3) { v /= 1000; i++; }
  return v.toFixed(1) + units[i];
};
const reload = () => api.get(`/cmdb/devices/${devId}/360/`);

const parseDlg = ref(false);
const parseKind = ref("acl");
const parseText = ref("");
const parseResult = ref(null);
const PARSE_KINDS = {
  acl: { label: "ACL 策略", cmd: "Cisco ASA/FTD", hint: "粘贴 show access-list 输出原文（可含页头/页脚）" },
  nat: { label: "NAT/VIP", cmd: "FortiOS", hint: "粘贴 show firewall vip 输出（config firewall vip ... end）" },
  ipsec: { label: "IPSec 隧道", cmd: "FortiOS", hint: "粘贴 get vpn ipsec tunnel status 输出（name: xxx(...) proto=... peer=... status=...）" },
};
const openParse = () => { parseDlg.value = true; parseText.value = ""; parseResult.value = null; };
const doParse = async (save) => {
  try {
    const r = await api.post(`/cmdb/devices/${devId}/tech-parse/`, {
      kind: parseKind.value, text: parseText.value, save: save || undefined,
    });
    parseResult.value = r;
    if (r.saved) { ElMessage.success("快照已保存"); loadSide(); }
  } catch (e) {
    ElMessage.error((e.response && (e.response.data?.detail || e.response.data?.hint))
      || e.message || "解析失败");
    parseResult.value = null;
  }
};

onMounted(async () => {
  const d = await api.get(`/cmdb/devices/${devId}/360/`);
  dev.value = d;
  interfaces.value = (d.interfaces || []).map((i) => ({ ...i, stat: i.stat || null }));
  calcWarranty();
  loadAssetEvents();
  loadSide();
});
const fmt2 = (s) => (s || "").replace("T", " ").slice(0, 19);
const loadSide = async () => {
  const [ls, at, hs, tk] = await Promise.all([
    api.get("/cmdb/licenses/", { params: { device_id: devId } }),
    api.get("/cmdb/attachments/", { params: { device_id: devId } }),
    api.get(`/cmdb/devices/${devId}/history/`),
    api.get(`/cmdb/devices/${devId}/tech/`).catch(() => ({})),
  ]);
  licenses.value = ls.results || (Array.isArray(ls) ? ls : []);
  attachments.value = at;
  history.value = hs || [];
  tech.value = tk || tech.value;
};

// 维保
const addLicense = async () => {
  if (!lf.license_type.trim()) { ElMessage.warning("请填写类型"); return; }
  await api.post("/cmdb/licenses/", { ...lf, device_id: devId });
  ElMessage.success("已保存");
  licenseDlg.value = false;
  Object.assign(lf, { license_type: "", seats: 1, expire_at: null, supplier: "", contract_no: "", remark: "" });
  loadSide();
};
const delLicense = async (row) => {
  await ElMessageBox.confirm("确认删除该维保/合同记录？", "提示", { type: "warning" });
  await api.delete(`/cmdb/licenses/${row.id}/`);
  ElMessage.success("已删除");
  loadSide();
};

// 附件
const doUpload = async ({ file }) => {
  const fd = new FormData();
  fd.append("device_id", devId);
  fd.append("file", file);
  fd.append("file_type", "other");
  await api.post("/cmdb/attachments/", fd);
  ElMessage.success("上传成功");
  loadSide();
};
const download = async (row) => {
  const r = await api.get(`/cmdb/attachments/${row.id}/download/`, { responseType: "blob" });
  const url = URL.createObjectURL(new Blob([r]));
  const a = document.createElement("a");
  a.href = url; a.download = row.file_name; a.click();
  URL.revokeObjectURL(url);
};
const delAttachment = async (row) => {
  await ElMessageBox.confirm(`确认删除附件「${row.file_name}」？`, "提示", { type: "warning" });
  await api.delete(`/cmdb/attachments/${row.id}/`);
  ElMessage.success("已删除");
  loadSide();
};
</script>
