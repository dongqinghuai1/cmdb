<template>
  <div>
    <el-card shadow="never">
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
        <el-radio-group v-model="f.status" size="small" @change="load">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button label="planned">待处理</el-radio-button>
          <el-radio-button label="doing">进行中</el-radio-button>
          <el-radio-button label="done">已完成</el-radio-button>
          <el-radio-button label="cancelled">已取消</el-radio-button>
        </el-radio-group>
        <el-button size="small" type="primary" style="margin-left:auto" @click="openCreate">
          新建作业工单</el-button>
      </div>
      <el-table :data="rows" size="small" max-height="520">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="title" label="作业" min-width="130" />
        <el-table-column label="类型" width="90">
          <template #default="{row}">
            <el-tag size="small" :type="KIND_TAG[row.kind] || 'info'">{{ row.kind_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="rack_name" label="机柜" width="100" />
        <el-table-column label="设备(U)" width="150">
          <template #default="{row}">
            <span>{{ row.device_name || "-" }}</span>
            <span v-if="row.u_from || row.u_to" style="color:#909399"> {{ row.u_from || "?" }}-{{ row.u_to || "?" }}U</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{row}">
            <el-tag size="small" :type="STS_TAG[row.status] || 'info'">{{ row.status_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="assignee" label="执行人" width="90" />
        <el-table-column label="计划时间" width="160">
          <template #default="{row}">{{ fmtD(row.planned_at) }}</template>
        </el-table-column>
        <el-table-column prop="note" label="说明" min-width="110" />
        <el-table-column label="操作" width="170" fixed="right" align="center">
          <template #default="{row}">
            <template v-if="row.status === 'planned'">
              <el-button link type="primary" @click="actStart(row)">开工</el-button>
              <el-button link type="danger" @click="actCancel(row)">取消</el-button>
            </template>
            <template v-else-if="row.status === 'doing'">
              <el-button link type="success" @click="openFinish(row)">完成</el-button>
            </template>
            <el-button v-if="row.status !== 'done' && row.status !== 'cancelled'"
                       link type="warning" @click="rowEdit(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dlg" :title="editing ? '编辑作业工单' : '新建机房作业工单'" width="560px">
      <el-form label-width="90px" size="small">
        <el-form-item label="类型" required>
          <el-select v-model="form.kind" style="width:100%">
            <el-option label="设备上架" value="rack_in" />
            <el-option label="设备下架" value="rack_out" />
            <el-option label="设备迁移" value="move" />
            <el-option label="检修/维修" value="repair" />
            <el-option label="布线调整" value="cable" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题" required>
          <el-input v-model="form.title" placeholder="如：核心交换机 上架 / 某服务器 迁移" />
        </el-form-item>
        <el-form-item label="机柜">
          <el-select v-model="form.rack" filterable clearable style="width:100%" placeholder="选择机柜">
            <el-option v-for="rk in racks" :key="rk.id" :label="rk.site_name + ' / ' + rk.name"
                       :value="rk.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="设备">
          <el-select v-model="form.device_id" filterable clearable style="width:100%"
                     placeholder="关联设备（可选）" @change="deviceChanged">
            <el-option v-for="d in devs" :key="d.id" :label="d.name + '（' + (d.manage_ip || '-') + '）'"
                       :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标U位">
          <el-input-number v-model="form.u_from" :min="1" :max="60" placeholder="起" style="width:100px" />
          <span style="margin:0 6px">至</span>
          <el-input-number v-model="form.u_to" :min="1" :max="60" placeholder="止" style="width:100px" />
        </el-form-item>
        <el-form-item label="执行人"><el-input v-model="form.assignee" placeholder="人/班组" /></el-form-item>
        <el-form-item label="计划时间">
          <el-date-picker v-model="form.planned_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss"
                          placeholder="选择时间" style="width:100%" />
        </el-form-item>
        <el-form-item label="说明"><el-input v-model="form.note" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg=false">取消</el-button>
        <el-button type="primary" :disabled="!form.kind || !form.title.trim()" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="finDlg" title="完成工单（填写结果）" width="440px">
      <el-input v-model="finResult" type="textarea" :rows="3" placeholder="作业结果/变更说明" />
      <template #footer><el-button @click="finDlg=false">取消</el-button>
        <el-button type="success" @click="actFinish">确认完成</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "../api";

const KIND_TAG = { rack_in: "success", rack_out: "danger", move: "warning", repair: "danger", cable: "info" };
const STS_TAG = { planned: "info", doing: "warning", done: "success", cancelled: "danger" };
const f = reactive({ status: "" });
const rows = ref([]);
const racks = ref([]);
const devs = ref([]);
const dlg = ref(false);
const editing = ref(null);
const finDlg = ref(false);
const finTarget = ref(null);
const finResult = ref("");
const form = reactive({ kind: "rack_in", title: "", rack: null, device_id: null,
                        u_from: null, u_to: null, assignee: "", planned_at: null, note: "" });

const load = async () => {
  const r = await api.get("/dcim/op-tickets/", { params: { status: f.status || undefined, page_size: 300 } });
  rows.value = r.results || [];
};
const openCreate = () => {
  editing.value = null;
  Object.assign(form, { kind: "rack_in", title: "", rack: null, device_id: null,
                        u_from: null, u_to: null, assignee: "", planned_at: null, note: "" });
  dlg.value = true;
};
const rowEdit = (row) => {
  editing.value = row;
  Object.assign(form, { kind: row.kind, title: row.title, rack: row.rack, device_id: row.device_id,
                        u_from: row.u_from, u_to: row.u_to, assignee: row.assignee,
                        planned_at: row.planned_at, note: row.note });
  dlg.value = true;
};
const deviceChanged = (id) => {
  if (id && !form.title.trim()) {
    const d = devs.value.find((x) => x.id === id);
    if (d) form.title = d.name + " " + KIND_NAME[form.kind] + "作业";
  }
};
const KIND_NAME = { rack_in: "上架", rack_out: "下架", move: "迁移", repair: "维修", cable: "布线" };
const save = async () => {
  const body = { ...form };
  if (editing.value) await api.patch(`/dcim/op-tickets/${editing.value.id}/`, body);
  else await api.post("/dcim/op-tickets/", body);
  ElMessage.success("已保存");
  dlg.value = false;
  load();
};
const actStart = async (row) => {
  await api.post(`/dcim/op-tickets/${row.id}/start/`);
  ElMessage.success("已开工");
  load();
};
const openFinish = (row) => { finTarget.value = row; finResult.value = ""; finDlg.value = true; };
const actFinish = async () => {
  await api.post(`/dcim/op-tickets/${finTarget.value.id}/finish/`, { result: finResult.value });
  ElMessage.success("已完成");
  finDlg.value = false;
  load();
};
const actCancel = async (row) => {
  const { value } = await ElMessageBox.prompt("取消原因", "取消工单",
    { inputPattern: /.+/, inputErrorMessage: "必填" });
  await api.post(`/dcim/op-tickets/${row.id}/cancel/`, { reason: value });
  ElMessage.info("已取消");
  load();
};
const fmtD = (s) => (s ? String(s).replace("T", " ").slice(0, 16) : "-");

onMounted(async () => {
  load();
  const [rk, dv] = await Promise.all([
    api.get("/dcim/racks/", { params: { page_size: 200 } }),
    api.get("/cmdb/devices/", { params: { page_size: 300 } }),
  ]);
  racks.value = rk.results || [];
  devs.value = dv.results || [];
});
</script>
