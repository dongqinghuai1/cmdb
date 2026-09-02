<template>
  <div>
    <el-row :gutter="12" style="margin-bottom:12px">
      <el-col :span="8"><el-card shadow="never"><div class="stat">我的报障 <b>{{ stats.reported }}</b></div></el-card></el-col>
      <el-col :span="8"><el-card shadow="never"><div class="stat">待我处理 <b>{{ stats.handled }}</b></div></el-card></el-col>
      <el-col :span="8"><el-card shadow="never"><div class="stat">全部超时 <b style="color:#f56c6c">{{ stats.overdue }}</b></div></el-card></el-col>
    </el-row>

    <el-card shadow="never">
      <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;align-items:center">
        <el-input v-model="f.keyword" placeholder="单号/标题/描述" clearable style="width:200px" @keyup.enter="load(1)" />
        <el-select v-model="f.status" placeholder="状态" clearable style="width:130px" @change="load(1)">
          <el-option v-for="s in STATUS" :key="s.v" :label="s.t" :value="s.v" />
        </el-select>
        <el-select v-model="f.priority" placeholder="优先级" clearable style="width:120px" @change="load(1)">
          <el-option v-for="s in PRIORITY" :key="s.v" :label="s.t" :value="s.v" />
        </el-select>
        <el-select v-model="f.source" placeholder="来源" clearable style="width:120px" @change="load(1)">
          <el-option v-for="s in SOURCE" :key="s.v" :label="s.t" :value="s.v" />
        </el-select>
        <el-checkbox v-model="f.overdue" @change="load(1)">仅看超时</el-checkbox>
        <el-button type="primary" @click="load(1)">查询</el-button>
        <el-button type="success" style="margin-left:auto" @click="openReport">报障</el-button>
      </div>

      <el-table :data="rows" size="small" stripe>
        <el-table-column prop="ticket_no" label="单号" width="150" />
        <el-table-column label="标题" min-width="220" show-overflow-tooltip>
          <template #default="{row}">{{ row.title }}</template>
        </el-table-column>
        <el-table-column label="优先级" width="90">
          <template #default="{row}">
            <el-tag :type="{urgent:'danger',high:'danger',mid:'warning',low:'info'}[row.priority] || 'info'" size="small">
              {{ row.priority_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="90">
          <template #default="{row}">
            <el-tag v-if="row.source!=='manual'" type="warning" size="small">{{ row.source_label }}</el-tag>
            <span v-else>{{ row.source_label }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="device_name" label="关联设备" width="130">
          <template #default="{row}">{{ row.device_name || '-' }}</template>
        </el-table-column>
        <el-table-column prop="reporter_name" label="报障人" width="110" />
        <el-table-column prop="handler_name" label="处理人" width="110">
          <template #default="{row}">{{ row.handler_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{row}">
            <el-tag :type="tagOf(row.status)" size="small">{{ row.status_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="SLA 截止" width="160">
          <template #default="{row}">
            <span :style="{color: row.overdue ? '#f56c6c' : '#606266', fontWeight: row.overdue ? 600 : 400}">
              {{ fmt(row.sla_deadline) }}<el-tag v-if="row.overdue" type="danger" size="small" style="margin-left:4px">超时</el-tag>
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="报障时间" width="160">
          <template #default="{row}">{{ fmt(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{row}">
            <el-button size="small" link type="primary" @click="openDetail(row.id)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="count"
                     :page-size="20" :current-page="page" @current-change="load" />
    </el-card>

    <!-- 报障对话框 -->
    <el-dialog v-model="reportVisible" title="新建事件单（报障）" width="560px">
      <el-form label-width="90px">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" maxlength="200" placeholder="一句话描述问题" />
        </el-form-item>
        <el-form-item label="优先级">
          <el-select v-model="form.priority" style="width:100%">
            <el-option v-for="s in PRIORITY" :key="s.v" :label="s.t + '（SLA ' + SLA_HOURS[s.v] + 'h）'" :value="s.v" />
          </el-select>
        </el-form-item>
        <el-form-item label="关联设备">
          <el-select v-model="form.device_id" filterable clearable placeholder="可选，按名称/SN 检索" style="width:100%">
            <el-option v-for="d in devices" :key="d.id" :label="`${d.name}${d.manage_ip ? ' ('+d.manage_ip+')' : ''}`" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源">
          <el-radio-group v-model="form.source">
            <el-radio label="manual">人工</el-radio>
            <el-radio label="inspect">巡检异常</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="问题描述">
          <el-input v-model="form.description" type="textarea" :rows="4" placeholder="影响范围、复现步骤等" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reportVisible=false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitReport">提交</el-button>
      </template>
    </el-dialog>

    <!-- 详情抽屉 -->
    <el-drawer v-model="detailVisible" size="640px" :title="detail ? detail.ticket_no + ' · ' + detail.title : ''">
      <template v-if="detail">
        <el-descriptions :column="2" size="small" border style="margin-bottom:12px">
          <el-descriptions-item label="状态">
            <el-tag :type="tagOf(detail.status)" size="small">{{ detail.status_label }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="优先级">
            <el-tag :type="{urgent:'danger',high:'danger',mid:'warning',low:'info'}[detail.priority]" size="small">
              {{ detail.priority_label }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="报障人">{{ detail.reporter_name }}</el-descriptions-item>
          <el-descriptions-item label="处理人">{{ detail.handler_name || '未分派' }}</el-descriptions-item>
          <el-descriptions-item label="关联设备">{{ detail.device_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="SLA 截止">
            <span :style="{color: detail.overdue ? '#f56c6c' : ''}">{{ fmt(detail.sla_deadline) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="来源" :span="2">{{ detail.source_label }}
            <span v-if="detail.related_alert_event_id"> · 关联告警 #{{ detail.related_alert_event_id }}：{{ detail.alert_title }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="问题描述" :span="2">{{ detail.description || '-' }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.resolution" label="处理结果" :span="2">{{ detail.resolution }}</el-descriptions-item>
        </el-descriptions>

        <!-- 状态流转操作 -->
        <div style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap">
          <template v-if="detail.status !== 'closed'">
            <el-button v-if="['new','assigned','processing','feedback'].includes(detail.status)" size="small"
                       type="primary" @click="assignVisible=true">分派/改派</el-button>
            <el-button v-if="['new','assigned'].includes(detail.status)" size="small" type="warning"
                       @click="act('start','开始处理')">开始处理</el-button>
            <el-button v-if="detail.status==='processing'" size="small" type="success"
                       @click="fbVisible=true">提交处理结果</el-button>
            <el-button v-if="['processing','feedback'].includes(detail.status)" size="small" type="danger"
                       @click="closeVisible=true">关闭</el-button>
          </template>
          <el-button size="small" @click="commentVisible=true">评论</el-button>
        </div>

        <!-- 时间线 -->
        <el-timeline v-if="detail.events && detail.events.length">
          <el-timeline-item v-for="ev in detail.events" :key="ev.id"
                            :type="{comment:'primary',assign:'warning',status_change:'success',sla_warning:'danger'}[ev.event_type]">
            <div style="display:flex;gap:8px;align-items:center">
              <b>{{ ev.actor_name }}</b>
              <el-tag size="small" effect="plain">{{ ev.event_type_label }}</el-tag>
              <span style="color:#909399;font-size:12px">{{ fmt(ev.created_at) }}</span>
            </div>
            <div style="white-space:pre-wrap;margin-top:4px">{{ ev.content || '-' }}</div>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="暂无时间线记录" :image-size="60" />
      </template>
    </el-drawer>

    <!-- 子对话框 -->
    <el-dialog v-model="assignVisible" title="分派 / 改派" width="440px">
      <el-select v-model="assignForm.handler_id" filterable placeholder="选择处理人" style="width:100%">
        <el-option v-for="u in users" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
      </el-select>
      <el-input v-model="assignForm.comment" placeholder="分派说明（可选）" style="margin-top:10px" />
      <template #footer><el-button @click="assignVisible=false">取消</el-button>
        <el-button type="primary" @click="doAssign">确认分派</el-button></template>
    </el-dialog>

    <el-dialog v-model="fbVisible" title="提交处理结果" width="480px">
      <el-input v-model="fbForm.resolution" type="textarea" :rows="4" placeholder="处理过程与结论（必填）" />
      <template #footer><el-button @click="fbVisible=false">取消</el-button>
        <el-button type="primary" @click="doFeedback">提交</el-button></template>
    </el-dialog>

    <el-dialog v-model="closeVisible" title="关闭事件单" width="440px">
      <el-input v-model="closeForm.comment" type="textarea" :rows="3"
                :placeholder="detail && detail.resolution ? '关闭说明（可选）' : '未提交过处理结果，请填写关闭说明（必填）'" />
      <template #footer><el-button @click="closeVisible=false">取消</el-button>
        <el-button type="danger" @click="doClose">确认关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="commentVisible" title="评论" width="440px">
      <el-input v-model="commentForm.content" type="textarea" :rows="3" placeholder="补充说明（必填）" />
      <template #footer><el-button @click="commentVisible=false">取消</el-button>
        <el-button type="primary" @click="doComment">发表</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import api from "../api";

const STATUS = [
  { v: "new", t: "待分派" }, { v: "assigned", t: "已分派" }, { v: "processing", t: "处理中" },
  { v: "feedback", t: "待反馈确认" }, { v: "closed", t: "已关闭" },
];
const PRIORITY = [
  { v: "urgent", t: "紧急" }, { v: "high", t: "高" }, { v: "mid", t: "中" }, { v: "low", t: "低" },
];
const SOURCE = [{ v: "manual", t: "人工报障" }, { v: "alert", t: "告警联动" }, { v: "inspect", t: "巡检异常" }];
const SLA_HOURS = { urgent: 2, high: 4, mid: 8, low: 24 };

const tagOf = (s) => ({ new: "info", assigned: "", processing: "warning", feedback: "primary", closed: "success" }[s] || "");
const fmt = (s) => (s || "").replace("T", " ").slice(0, 16);

const stats = reactive({ reported: 0, handled: 0, overdue: 0 });
const rows = ref([]); const count = ref(0); const page = ref(1);
const f = reactive({ keyword: "", status: null, priority: null, source: null, overdue: false });
const devices = ref([]); const users = ref([]);

const load = async (p = 1) => {
  page.value = p;
  const params = { page: p, page_size: 20 };
  if (f.status) params.status = f.status;
  if (f.priority) params.priority = f.priority;
  if (f.source) params.source = f.source;
  if (f.overdue) params.overdue = 1;
  if (f.keyword) params.search = f.keyword;
  const r = await api.get("/changes/incidents/", { params });
  rows.value = r.results || []; count.value = r.count;
};
const loadStats = async () => {
  try {
    const r = await api.get("/changes/incidents/my-stats/");
    Object.assign(stats, r);
  } catch (e) { /* 无权限时忽略 */ }
};

onMounted(async () => {
  load(); loadStats();
  const [d, u] = await Promise.all([
    api.get("/cmdb/devices/", { params: { page_size: 500 } }),
    api.get("/system/users/", { params: { page_size: 200 } }),
  ]);
  devices.value = d.results || [];
  users.value = u.results || [];
});

// 报障
const reportVisible = ref(false);
const form = reactive({ title: "", priority: "mid", device_id: null, source: "manual", description: "" });
const submitting = ref(false);
const openReport = () => {
  Object.assign(form, { title: "", priority: "mid", device_id: null, source: "manual", description: "" });
  reportVisible.value = true;
};
const submitReport = async () => {
  if (!form.title.trim()) { ElMessage.warning("请填写标题"); return; }
  submitting.value = true;
  try {
    await api.post("/changes/incidents/", {
      title: form.title, priority: form.priority, device_id: form.device_id || null,
      source: form.source, description: form.description,
    });
    ElMessage.success("报障成功");
    reportVisible.value = false;
    load(1); loadStats();
  } finally { submitting.value = false; }
};

// 详情
const detailVisible = ref(false);
const detail = ref(null);
const openDetail = async (id) => {
  detailVisible.value = true;
  await refreshDetail(id);
};
const refreshDetail = async (id) => {
  detail.value = await api.get("/changes/incidents/" + id + "/");
};

// 动作
const assignVisible = ref(false);
const assignForm = reactive({ handler_id: null, comment: "" });
const doAssign = async () => {
  if (!assignForm.handler_id) { ElMessage.warning("请选择处理人"); return; }
  await api.post(`/changes/incidents/${detail.value.id}/assign/`, assignForm);
  ElMessage.success("已分派");
  assignVisible.value = false;
  refreshDetail(detail.value.id); load(page.value); loadStats();
};
const act = async (action, label) => {
  await api.post(`/changes/incidents/${detail.value.id}/${action}/`, {});
  ElMessage.success(label + "成功");
  refreshDetail(detail.value.id); load(page.value); loadStats();
};
const fbVisible = ref(false);
const fbForm = reactive({ resolution: "" });
const doFeedback = async () => {
  if (!fbForm.resolution.trim()) { ElMessage.warning("请填写处理结果"); return; }
  await api.post(`/changes/incidents/${detail.value.id}/feedback/`, fbForm);
  ElMessage.success("已提交处理结果");
  fbVisible.value = false;
  refreshDetail(detail.value.id); load(page.value); loadStats();
};
const closeVisible = ref(false);
const closeForm = reactive({ comment: "" });
const doClose = async () => {
  await api.post(`/changes/incidents/${detail.value.id}/close/`, { comment: closeForm.comment });
  ElMessage.success("事件单已关闭");
  closeVisible.value = false;
  refreshDetail(detail.value.id); load(page.value); loadStats();
};
const commentVisible = ref(false);
const commentForm = reactive({ content: "" });
const doComment = async () => {
  if (!commentForm.content.trim()) { ElMessage.warning("请输入内容"); return; }
  await api.post(`/changes/incidents/${detail.value.id}/comment/`, commentForm);
  ElMessage.success("评论已发表");
  commentVisible.value = false;
  refreshDetail(detail.value.id);
};
</script>

<style scoped>
.stat { color: #606266; font-size: 14px; }
.stat b { font-size: 22px; margin-left: 8px; color: #303133; }
</style>
