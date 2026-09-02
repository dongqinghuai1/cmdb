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
const licenses = ref([]);
const attachments = ref([]);
const history = ref([]);
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

onMounted(async () => {
  const d = await api.get(`/cmdb/devices/${devId}/360/`);
  dev.value = d;
  interfaces.value = (d.interfaces || []).map((i) => ({ ...i, stat: i.stat || null }));
  loadSide();
});
const loadSide = async () => {
  const [ls, at, hs] = await Promise.all([
    api.get("/cmdb/licenses/", { params: { device_id: devId } }),
    api.get("/cmdb/attachments/", { params: { device_id: devId } }),
    api.get(`/cmdb/devices/${devId}/history/`),
  ]);
  licenses.value = ls.results || (Array.isArray(ls) ? ls : []);
  attachments.value = at;
  history.value = hs || [];
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
