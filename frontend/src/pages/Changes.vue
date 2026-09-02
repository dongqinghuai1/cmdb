<template>
  <div>
    <el-card shadow="never">
      <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;align-items:center">
        <el-input v-model="f.keyword" placeholder="单号/标题" clearable style="width:190px" @keyup.enter="load(1)" />
        <el-select v-model="f.status" placeholder="状态" clearable style="width:130px" @change="load(1)">
          <el-option v-for="s in STATUS" :key="s.v" :label="s.t" :value="s.v" />
        </el-select>
        <el-select v-model="f.risk_level" placeholder="风险" clearable style="width:110px" @change="load(1)">
          <el-option v-for="s in RISK" :key="s.v" :label="s.t" :value="s.v" />
        </el-select>
        <el-select v-model="mine" placeholder="我的" clearable style="width:120px" @change="load(1)">
          <el-option value="applicant" label="我申请的" />
          <el-option value="implement" label="我实施的" />
          <el-option value="verify" label="我验证的" />
        </el-select>
        <el-button type="primary" @click="load(1)">查询</el-button>
        <el-button type="success" style="margin-left:auto" @click="createVisible=true">发起变更</el-button>
      </div>

      <el-table :data="rows" size="small" stripe>
        <el-table-column prop="ticket_no" label="单号" width="150" />
        <el-table-column label="标题" min-width="200" show-overflow-tooltip />
        <el-table-column label="类型" width="100">
          <template #default="{row}">{{ row.change_type_label }}</template>
        </el-table-column>
        <el-table-column label="风险" width="80">
          <template #default="{row}">
            <el-tag :type="{high:'danger',mid:'warning',low:'info'}[row.risk_level]" size="small">
              {{ row.risk_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="申请人" prop="applicant_name" width="100" />
        <el-table-column label="实施人" width="110">
          <template #default="{row}">{{ row.implementer_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="审批人" width="110">
          <template #default="{row}">{{ row.approver_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="变更窗口" width="180">
          <template #default="{row}">{{ fmt(row.plan_start) }} ~ {{ fmt(row.plan_end) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{row}">
            <el-tag :type="tagOf(row.status)" size="small">{{ row.status_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="申请时间" width="160">
          <template #default="{row}">{{ fmt(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{row}">
            <el-button size="small" link type="primary" @click="openDetail(row.id)">详情/处理</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="count"
                     :page-size="20" :current-page="page" @current-change="load" />
    </el-card>

    <!-- 发起变更（草稿） -->
    <el-dialog v-model="createVisible" title="发起变更（草稿）" width="620px">
      <el-form label-width="90px">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" maxlength="255" placeholder="如：核心交换机版本升级" />
        </el-form-item>
        <el-form-item label="变更类型">
          <el-select v-model="form.change_type" style="width:100%">
            <el-option v-for="s in TYPES" :key="s.v" :label="s.t" :value="s.v" />
          </el-select>
        </el-form-item>
        <el-form-item label="风险级别">
          <el-radio-group v-model="form.risk_level">
            <el-radio-button label="low">低危</el-radio-button>
            <el-radio-button label="mid">中危</el-radio-button>
            <el-radio-button label="high">高危</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="变更摘要" required>
          <el-input v-model="form.summary" placeholder="一句话说明变更内容" />
        </el-form-item>
        <el-form-item label="影响面">
          <el-input v-model="form.impact" type="textarea" :rows="2" placeholder="影响范围/风险/回退要点" />
        </el-form-item>
        <el-form-item label="操作步骤">
          <el-input v-model="form.steps" type="textarea" :rows="4" placeholder="每行一步：1) 备份配置 2) ..." />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible=false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="doCreate">创建草稿</el-button>
      </template>
    </el-dialog>

    <!-- 详情抽屉 -->
    <el-drawer v-model="detailVisible" size="680px" :title="detail ? detail.ticket_no + ' · ' + detail.title : ''">
      <template v-if="detail">
        <el-descriptions :column="2" size="small" border style="margin-bottom:12px">
          <el-descriptions-item label="状态">
            <el-tag :type="tagOf(detail.status)" size="small">{{ detail.status_label }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="风险">
            <el-tag :type="{high:'danger',mid:'warning',low:'info'}[detail.risk_level]" size="small">
              {{ detail.risk_label }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="类型">{{ detail.change_type_label }}</el-descriptions-item>
          <el-descriptions-item label="审批状态">
            <el-tag v-if="detail.approval_status" size="small"
                    :type="{approved:'success',rejected:'danger',pending:'warning'}[detail.approval_status]">
              {{ {approved:'已通过',rejected:'已驳回',pending:'待审批'}[detail.approval_status] || detail.approval_status }}
            </el-tag>
            <span v-else>-</span>
          </el-descriptions-item>
          <el-descriptions-item label="申请人">{{ detail.applicant_name }}</el-descriptions-item>
          <el-descriptions-item label="审批人">{{ detail.approver_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="实施人">{{ detail.implementer_name || '未指定' }}</el-descriptions-item>
          <el-descriptions-item label="验证人">{{ detail.verifier_name || '未指定' }}</el-descriptions-item>
          <el-descriptions-item label="计划窗口" :span="2">
            {{ fmt(detail.plan_start) }} ~ {{ fmt(detail.plan_end) }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.actual_start" label="实际开始">{{ fmt(detail.actual_start) }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.actual_end" label="实际结束">{{ fmt(detail.actual_end) }}</el-descriptions-item>
        </el-descriptions>

        <el-divider content-position="left">变更内容</el-divider>
        <el-descriptions :column="1" size="small" border style="margin-bottom:12px">
          <el-descriptions-item label="摘要">{{ (detail.content||{}).summary || '-' }}</el-descriptions-item>
          <el-descriptions-item v-if="(detail.content||{}).impact" label="影响面">{{ (detail.content||{}).impact }}</el-descriptions-item>
          <el-descriptions-item v-if="(detail.content||{}).steps" label="操作步骤">
            <pre style="white-space:pre-wrap;margin:0">{{ (detail.content||{}).steps }}</pre>
          </el-descriptions-item>
        </el-descriptions>

        <el-alert v-if="detail.approval_comment" type="info" :closable="false" style="margin-bottom:12px"
                  :title="'审批意见：' + detail.approval_comment" />
        <el-alert v-if="detail.rollback_plan" type="warning" :closable="false" style="margin-bottom:12px"
                  :title="'回滚方案：' + detail.rollback_plan" />
        <el-alert v-if="detail.result_desc" type="success" :closable="false" style="margin-bottom:12px"
                  :title="'验证结果：' + detail.result_desc" />

        <!-- 流转操作 -->
        <div style="margin-bottom:8px;display:flex;gap:8px;flex-wrap:wrap">
          <el-button v-if="detail.status==='draft'" type="primary" size="small" @click="submitVisible=true">提交审批</el-button>
          <template v-if="detail.status==='approving' && isApprover">
            <el-button type="success" size="small" @click="decide('approve')">通过</el-button>
            <el-button type="danger" size="small" @click="decide('reject')">驳回</el-button>
          </template>
          <el-button v-if="detail.status==='approved'" type="warning" size="small" @click="act('start','开始实施')">开始实施</el-button>
          <el-button v-if="detail.status==='implementing'" type="primary" size="small" @click="verifyVisible=true">提交验证</el-button>
          <el-button v-if="['implementing','verifying'].includes(detail.status)" type="danger" size="small"
                     @click="rollbackVisible=true">回滚</el-button>
          <el-button v-if="detail.status==='verifying'" type="success" size="small" @click="act('close','关闭变更')">关闭</el-button>
        </div>
      </template>
    </el-drawer>

    <!-- 提交审批 -->
    <el-dialog v-model="submitVisible" title="提交审批" width="560px">
      <el-form label-width="100px">
        <el-form-item label="审批人" required>
          <el-select v-model="sform.approver_id" filterable style="width:100%" placeholder="选择审批人">
            <el-option v-for="u in users" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="实施人">
          <el-select v-model="sform.implementer_id" filterable style="width:100%">
            <el-option v-for="u in users" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="验证人">
          <el-select v-model="sform.verifier_id" filterable style="width:100%">
            <el-option v-for="u in users" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="计划开始" required>
          <el-date-picker v-model="sform.plan_start" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" style="width:100%" />
        </el-form-item>
        <el-form-item label="计划结束" required>
          <el-date-picker v-model="sform.plan_end" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" style="width:100%" />
        </el-form-item>
        <el-form-item label="回滚预案">
          <el-input v-model="sform.rollback_plan" type="textarea" :rows="2" placeholder="可选：如失败如何回退" />
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="submitVisible=false">取消</el-button>
        <el-button type="primary" @click="doSubmit">提交</el-button></template>
    </el-dialog>

    <el-dialog v-model="decideVisible" :title="decideKind==='approve' ? '审批通过' : '驳回变更'" width="460px">
      <el-input v-model="decideForm.comment" type="textarea" :rows="3"
                :placeholder="decideKind==='reject' ? '驳回原因（必填）' : '审批意见（可选）'" />
      <template #footer><el-button @click="decideVisible=false">取消</el-button>
        <el-button :type="decideKind==='approve' ? 'success' : 'danger'" @click="doDecide">确认</el-button></template>
    </el-dialog>

    <el-dialog v-model="verifyVisible" title="提交验证结果" width="480px">
      <el-input v-model="verifyForm.result_desc" type="textarea" :rows="4" placeholder="验证过程与结论（必填）" />
      <template #footer><el-button @click="verifyVisible=false">取消</el-button>
        <el-button type="primary" @click="doVerify">提交</el-button></template>
    </el-dialog>

    <el-dialog v-model="rollbackVisible" title="回滚变更" width="480px">
      <el-input v-model="rollbackForm.rollback_plan" type="textarea" :rows="3" placeholder="实际回滚方案（必填）" />
      <template #footer><el-button @click="rollbackVisible=false">取消</el-button>
        <el-button type="danger" @click="doRollback">确认回滚</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "../api";

const STATUS = [
  { v: "draft", t: "草稿" }, { v: "approving", t: "待审批" }, { v: "approved", t: "已批准" },
  { v: "implementing", t: "实施中" }, { v: "verifying", t: "验证中" }, { v: "closed", t: "已关闭" },
  { v: "rejected", t: "已驳回" }, { v: "rolledback", t: "已回滚" },
];
const TYPES = [
  { v: "config", t: "配置变更" }, { v: "device", t: "设备变更" },
  { v: "sw_upgrade", t: "软件升级" }, { v: "network", t: "网络变更" },
];
const RISK = [{ v: "high", t: "高危" }, { v: "mid", t: "中危" }, { v: "low", t: "低危" }];

const tagOf = (s) => ({
  draft: "info", approving: "warning", approved: "", implementing: "warning",
  verifying: "primary", closed: "success", rejected: "danger", rolledback: "danger",
}[s] || "");
const fmt = (s) => (s || "").replace("T", " ").slice(0, 16);

const rows = ref([]); const count = ref(0); const page = ref(1);
const f = reactive({ keyword: "", status: null, risk_level: null });
const mine = ref(null);
const users = ref([]); const me = ref({});

const isApprover = computed(() => detail.value && me.value.id === detail.value.approver_id);

const load = async (p = 1) => {
  page.value = p;
  const params = { page: p, page_size: 20 };
  if (f.status) params.status = f.status;
  if (f.risk_level) params.risk_level = f.risk_level;
  if (mine.value) params.mine = mine.value;
  if (f.keyword) params.search = f.keyword;
  const r = await api.get("/changes/change-tickets/", { params });
  rows.value = r.results || []; count.value = r.count;
};
onMounted(async () => {
  load();
  try { me.value = await api.get("/auth/me/"); } catch (e) { /* 忽略 */ }
  const [u, d] = await Promise.all([
    api.get("/system/users/", { params: { page_size: 200 } }),
    api.get("/cmdb/devices/", { params: { page_size: 5 } }),
  ]);
  users.value = u.results || [];
});

// 发起
const createVisible = ref(false);
const form = reactive({ title: "", change_type: "config", risk_level: "mid", summary: "", impact: "", steps: "" });
const submitting = ref(false);
const doCreate = async () => {
  if (!form.title.trim() || !form.summary.trim()) { ElMessage.warning("请填写标题与变更摘要"); return; }
  submitting.value = true;
  try {
    await api.post("/changes/change-tickets/", {
      title: form.title, change_type: form.change_type, risk_level: form.risk_level,
      content: { summary: form.summary, impact: form.impact, steps: form.steps },
    });
    ElMessage.success("草稿已创建，请提交审批");
    createVisible.value = false;
    load(1);
  } finally { submitting.value = false; }
};

// 详情
const detailVisible = ref(false);
const detail = ref(null);
const openDetail = async (id) => {
  detailVisible.value = true;
  detail.value = await api.get("/changes/change-tickets/" + id + "/");
};
const refresh = async () => {
  detail.value = await api.get("/changes/change-tickets/" + detail.value.id + "/");
  load(page.value);
};

const act = async (action, label) => {
  await ElMessageBox.confirm(`确认${label}？`, "提示", { type: "warning" }).catch(() => { throw "cancel"; });
  await api.post(`/changes/change-tickets/${detail.value.id}/${action}/`, {});
  ElMessage.success(label + "成功");
  refresh();
};

// 提交审批
const submitVisible = ref(false);
const sform = reactive({ approver_id: null, implementer_id: null, verifier_id: null, plan_start: null, plan_end: null, rollback_plan: "" });
const doSubmit = async () => {
  if (!sform.approver_id || !sform.plan_start || !sform.plan_end) { ElMessage.warning("请填写审批人与变更窗口"); return; }
  if (sform.verifier_id === sform.implementer_id) { ElMessage.warning("验证人不能与实施人为同一人"); return; }
  await api.post(`/changes/change-tickets/${detail.value.id}/submit/`, { ...sform });
  ElMessage.success("已提交审批");
  submitVisible.value = false;
  refresh();
};

// 审批
const decideVisible = ref(false);
const decideKind = ref("approve");
const decideForm = reactive({ comment: "" });
const decide = (kind) => {
  decideKind.value = kind;
  decideForm.comment = "";
  decideVisible.value = true;
};
const doDecide = async () => {
  if (decideKind.value === "reject" && !decideForm.comment.trim()) { ElMessage.warning("驳回请填写原因"); return; }
  await api.post(`/changes/change-tickets/${detail.value.id}/${decideKind.value}/`, { comment: decideForm.comment });
  ElMessage.success(decideKind.value === "approve" ? "已通过" : "已驳回");
  decideVisible.value = false;
  refresh();
};

// 验证/回滚
const verifyVisible = ref(false);
const verifyForm = reactive({ result_desc: "" });
const doVerify = async () => {
  if (!verifyForm.result_desc.trim()) { ElMessage.warning("请填写验证结果"); return; }
  await api.post(`/changes/change-tickets/${detail.value.id}/verify/`, verifyForm);
  ElMessage.success("验证结果已提交");
  verifyVisible.value = false;
  refresh();
};
const rollbackVisible = ref(false);
const rollbackForm = reactive({ rollback_plan: "" });
const doRollback = async () => {
  if (!rollbackForm.rollback_plan.trim()) { ElMessage.warning("请填写回滚方案"); return; }
  await api.post(`/changes/change-tickets/${detail.value.id}/rollback/`, rollbackForm);
  ElMessage.success("已回滚");
  rollbackVisible.value = false;
  refresh();
};
</script>
