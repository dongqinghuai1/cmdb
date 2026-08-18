<template>
  <el-tabs v-model="tab">
    <el-tab-pane label="凭据管理" name="cred">
      <el-button @click="createCred">新增凭据</el-button>
      <el-table :data="creds" size="small" stripe style="margin-top:10px">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="cred_type" label="类型" width="130" />
        <el-table-column prop="username" label="用户" width="120" />
        <el-table-column prop="secret_masked" label="密钥" width="100" />
        <el-table-column prop="remark" label="备注" />
        <el-table-column label="操作" width="80">
          <template #default="{row}">
            <el-button size="small" link type="danger" @click.stop="remove(row, 'credentials')">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-tab-pane>
    <el-tab-pane label="通知渠道" name="ch">
      <el-button @click="createChannel">新增渠道</el-button>
      <el-table :data="channels" size="small" stripe style="margin-top:10px">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="channel_type" label="类型" width="120" />
        <el-table-column prop="enabled" label="启用" width="80">
          <template #default="{row}">
            <el-tag :type="row.enabled?'success':'info'">{{ row.enabled ? "是" : "否" }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{row}">
            <el-button size="small" @click="test(row.id)">测试</el-button>
            <el-button size="small" link type="danger" @click.stop="remove(row, 'notify-channels')">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-tab-pane>
    <el-tab-pane label="用户" name="users">
      <el-table :data="users" size="small" stripe>
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="email" label="邮箱" />
        <el-table-column prop="dept_name" label="部门" />
        <el-table-column prop="is_active" label="启用" width="80">
          <template #default="{row}">{{ row.is_active ? "是" : "否" }}</template>
        </el-table-column>
      </el-table>
    </el-tab-pane>
    <el-tab-pane label="审计日志" name="audit">
      <el-table :data="audits" size="small" stripe>
        <el-table-column prop="created_at" label="时间" width="170">
          <template #default="{row}">{{ (row.created_at||'').replace('T',' ').slice(0,19) }}</template>
        </el-table-column>
        <el-table-column prop="username" label="用户" width="110" />
        <el-table-column prop="action" label="动作" width="110" />
        <el-table-column prop="resource_type" label="对象" width="140" />
        <el-table-column prop="resource_id" label="ID" width="90" />
      </el-table>
    </el-tab-pane>
  </el-tabs>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "../api";

const tab = ref("cred");
const creds = ref([]); const channels = ref([]); const users = ref([]); const audits = ref([]);

const load = async () => {
  const [c, ch, u, a] = await Promise.all([
    api.get("/system/credentials/", { params: { page_size: 50 } }),
    api.get("/system/notify-channels/", { params: { page_size: 50 } }),
    api.get("/system/users/", { params: { page_size: 50 } }),
    api.get("/system/audit-logs/", { params: { page_size: 50 } }),
  ]);
  creds.value = c.results || []; channels.value = ch.results || [];
  users.value = u.results || []; audits.value = a.results || [];
};
onMounted(load);

const createCred = async () => {
  const { value: name } = await ElMessageBox.prompt("凭据名称", "新增凭据");
  const { value: secret } = await ElMessageBox.prompt("密钥内容（community/密码/token）", "新增凭据");
  await api.post("/system/credentials/", { name, cred_type: "snmp_v2c", secret, remark: "" });
  ElMessage.success("已创建"); load();
};

const createChannel = async () => {
  const { value: name } = await ElMessageBox.prompt("渠道名称", "新增渠道");
  const { value: url } = await ElMessageBox.prompt("飞书机器人 Webhook 地址", "新增渠道");
  await api.post("/system/notify-channels/", { name, channel_type: "feishu", config: { webhook_url: url } });
  ElMessage.success("已创建"); load();
};

const test = async (id) => {
  const r = await api.post("/system/notify-channels/" + id + "/test/");
  ElMessage[r.ok ? "success" : "error"](r.ok ? "发送成功" : "发送失败，检查 webhook 配置");
};

const remove = async (row, res) => {
  try {
    await ElMessageBox.confirm("确认删除「" + row.name + "」？", "删除确认", { type: "warning" });
    await api.delete("/system/" + res + "/" + row.id + "/");
    ElMessage.success("已删除");
    load();
  } catch (e) { /* 取消或后端提示 */ }
};
</script>
