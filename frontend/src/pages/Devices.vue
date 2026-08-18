<template>
  <el-card>
    <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
      <el-input v-model="q" placeholder="搜索 名称/SN/IP/资产编号" style="width:240px" clearable
                @keyup.enter="load(1)" />
      <el-select v-model="f.region" placeholder="地区" clearable style="width:140px" @change="load(1)">
        <el-option v-for="r in regions" :key="r.id" :label="r.name" :value="r.id" />
      </el-select>
      <el-select v-model="f.model" placeholder="类型" clearable style="width:140px" @change="load(1)">
        <el-option v-for="m in models" :key="m.id" :label="m.name" :value="m.id" />
      </el-select>
      <el-select v-model="f.online_status" placeholder="在线状态" clearable style="width:130px" @change="load(1)">
        <el-option label="在线" value="online" /><el-option label="离线" value="offline" />
        <el-option label="采集异常" value="collect_error" />
      </el-select>
      <el-button type="primary" @click="load(1)">查询</el-button>
      <el-button @click="openCreate">新增设备</el-button>
      <el-button @click="exportXlsx">导出 Excel</el-button>
      <el-upload :show-file-list="false" :http-request="importXlsx" accept=".xlsx"
                 style="display:inline-block">
        <el-button>导入 Excel</el-button>
      </el-upload>
    </div>

    <el-table :data="rows" size="small" stripe @row-click="(r) => $router.push(`/devices/${r.id}`)"
              style="cursor:pointer">
      <el-table-column prop="name" label="名称" min-width="120" />
      <el-table-column prop="model_name" label="类型" width="110" />
      <el-table-column prop="vendor" label="品牌" width="90" />
      <el-table-column prop="hw_model" label="型号" min-width="110" />
      <el-table-column prop="manage_ip" label="管理IP" width="130" />
      <el-table-column label="位置" min-width="150">
        <template #default="{row}">
          {{ row.region_name }} / {{ row.site_name }} {{ row.rack_name ? " · " + row.rack_name + " U" + row.rack_start_u : "" }}
        </template>
      </el-table-column>
      <el-table-column prop="online_status" label="状态" width="100">
        <template #default="{row}">
          <el-tag :type="row.online_status==='online'?'success':row.online_status==='offline'?'info':'warning'">
            {{ row.online_status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="usage_tag" label="用途" width="80" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{row}">
          <el-button size="small" link type="primary" @click.stop="$router.push('/devices/' + row.id)">详情</el-button>
          <el-button size="small" link type="warning" @click.stop="edit(row)">编辑</el-button>
          <el-button size="small" link type="danger" @click.stop="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="count"
                   :page-size="20" :current-page="page" @current-change="load" />
  </el-card>

  <el-dialog v-model="dlg" :title="form.id ? '编辑设备' : '新增设备'" width="560">
    <el-form :model="form" label-width="90px">
      <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
      <el-form-item label="类型">
        <el-select v-model="form.model">
          <el-option v-for="m in models" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="品牌"><el-input v-model="form.vendor" placeholder="H3C / Cisco / Fortinet..." /></el-form-item>
      <el-form-item label="SN"><el-input v-model="form.sn" /></el-form-item>
      <el-form-item label="管理IP"><el-input v-model="form.manage_ip" /></el-form-item>
      <el-form-item label="机房">
        <el-select v-model="form.site" @change="onSite">
          <el-option v-for="s in sites" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="机柜">
        <el-select v-model="form.rack" clearable placeholder="清空即下架（脱离机柜）">
          <el-option v-for="r in rackOptions" :key="r.id" :label="r.name" :value="r.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="起始U"><el-input-number v-model="form.rack_start_u" :min="1" :max="50" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dlg=false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import api from "../api";

const q = ref(""); const f = reactive({ region: null, model: null, online_status: null });
const rows = ref([]); const count = ref(0); const page = ref(1);
const models = ref([]); const regions = ref([]); const sites = ref([]); const rackOptions = ref([]);
const dlg = ref(false);
const form = reactive({ id: null, name: "", model: null, vendor: "", sn: "", manage_ip: "",
                        site: null, rack: null, rack_start_u: 1 });

const load = async (p = 1) => {
  page.value = p;
  const r = await api.get("/cmdb/devices/", { params: { page: p, search: q.value || undefined, ...f } });
  rows.value = r.results || []; count.value = r.count;
};
onMounted(async () => {
  await load();
  const [m, rg, st] = await Promise.all([
    api.get("/cmdb/models/", { params: { page_size: 100 } }),
    api.get("/dcim/regions/", { params: { page_size: 100 } }),
    api.get("/dcim/sites/", { params: { page_size: 100 } }),
  ]);
  models.value = m.results || []; regions.value = rg.results || []; sites.value = st.results || [];
});

const onSite = async (sid) => {
  form.rack = null;
  if (!sid) { rackOptions.value = []; return; }
  const r = await api.get("/dcim/racks/", { params: { site: sid, page_size: 100 } });
  rackOptions.value = r.results || [];
};

const save = async () => {
  const site = sites.value.find((s) => s.id === form.site);
  const payload = { ...form, region: site?.region ?? null };
  if (!form.rack) { payload.rack = null; payload.rack_start_u = null; }
  if (form.id) {
    await api.patch("/cmdb/devices/" + form.id + "/", payload);
    ElMessage.success("已更新");
  } else {
    await api.post("/cmdb/devices/", payload);
    ElMessage.success("已创建");
  }
  dlg.value = false;
  load(page.value);
};

const openCreate = () => {
  Object.assign(form, { id: null, name: "", model: null, vendor: "", sn: "", manage_ip: "",
                        site: null, rack: null, rack_start_u: 1 });
  rackOptions.value = [];
  dlg.value = true;
};

const edit = async (row) => {  Object.assign(form, {
    id: row.id, name: row.name, model: row.model, vendor: row.vendor, sn: row.sn,
    manage_ip: row.manage_ip, site: row.site, rack: row.rack || null,
    rack_start_u: row.rack_start_u || 1,
  });
  if (row.site) await onSite(row.site);
  if (row.rack) {
    const r = await api.get("/dcim/racks/", { params: { site: row.site, page_size: 100 } });
    rackOptions.value = r.results || [];
  }
  dlg.value = true;
};

const exportXlsx = () => { window.open("/api/v1/cmdb/devices/export-excel/", "_blank"); };

const importXlsx = async ({ file }) => {
  const fd = new FormData(); fd.append("file", file);
  const r = await api.post("/cmdb/devices/import-excel/", fd);
  ElMessage[resultSummary(r)](`成功 ${r.success}，失败 ${r.failed}`);
  load();
};
const resultSummary = (r) => (r.failed ? "warning" : "success");

const remove = async (row) => {
  try {
    await ElMessageBox.confirm("确认删除设备「" + row.name + "」？（仅超管可用 ?hard=1 物理删除）", "删除确认",
                               { type: "warning" });
    const hard = row.deleted ? "" : "";
    await api.delete("/cmdb/devices/" + row.id + "/");
    ElMessage.success("已删除（软删除，可恢复）");
    load(page.value);
  } catch (e) { /* 取消或后端提示 */ }
};
import { ElMessageBox } from "element-plus";
</script>
