<template>
  <el-tabs v-model="tab">
    <el-tab-pane label="巡检任务" name="tasks">
      <el-button type="primary" @click="createTask">新建巡检任务</el-button>
      <el-table :data="tasks" size="small" stripe style="margin-top:10px">
        <el-table-column prop="name" label="任务" />
        <el-table-column prop="cron" label="cron" width="120" />
        <el-table-column prop="template" label="模板ID" width="90" />
        <el-table-column prop="last_run_at" label="上次执行" width="170">
          <template #default="{row}">{{ (row.last_run_at||'-').replace('T',' ').slice(0,19) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{row}">
            <el-button size="small" type="primary" @click="run(row.id)">执行</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-tab-pane>
    <el-tab-pane label="执行记录" name="runs">
      <el-table :data="runs" size="small" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="trigger_type" label="触发" width="80" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{row}">
            <el-tag :type="row.status==='success'?'success':row.status==='running'?'warning':'danger'">
              {{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="total_devices" label="设备数" width="90" />
        <el-table-column prop="abnormal_devices" label="异常数" width="90" />
        <el-table-column prop="health_score_avg" label="平均健康分" width="110" />
        <el-table-column prop="finished_at" label="完成时间" width="170">
          <template #default="{row}">{{ (row.finished_at||'-').replace('T',' ').slice(0,19) }}</template>
        </el-table-column>
      </el-table>
    </el-tab-pane>
  </el-tabs>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "../api";

const tab = ref("tasks");
const tasks = ref([]); const runs = ref([]);

const load = async () => {
  const [t, r] = await Promise.all([
    api.get("/inspects/tasks/", { params: { page_size: 50 } }),
    api.get("/inspects/runs/", { params: { page_size: 50 } }),
  ]);
  tasks.value = t.results || []; runs.value = r.results || [];
};
onMounted(load);

const createTask = async () => {
  const tpl = await api.get("/inspects/templates/", { params: { page_size: 50 } });
  if (!tpl.results?.length) {
    ElMessage.warning("请先创建巡检模板"); return;
  }
  const { value: name } = await ElMessageBox.prompt("任务名称", "新建巡检任务");
  await api.post("/inspects/tasks/", { name, template: tpl.results[0].id, cron: "" });
  ElMessage.success("已创建"); load();
};

const run = async (id) => {
  await api.post("/inspects/tasks/" + id + "/run/");
  ElMessage.success("已下发到后台执行（结果见执行记录）");
};
</script>
