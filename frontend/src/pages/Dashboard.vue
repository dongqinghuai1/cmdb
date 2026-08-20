<template>
  <div style="display:flex;flex-direction:column;gap:14px">
    <!-- 顶部统计卡片 -->
    <el-row :gutter="14">
      <el-col :span="6"><el-card shadow="hover">
        <div class="stat"><span class="label">设备总数</span><span class="val">{{ s.totals?.total || 0 }}</span></div>
        <div class="sub">
          <el-tag type="success" size="small">在线 {{ s.totals?.online || 0 }}</el-tag>
          <el-tag type="info" size="small" style="margin-left:4px">离线 {{ s.totals?.offline || 0 }}</el-tag>
        </div>
        <el-progress :percentage="pct(s.totals?.online, s.totals?.total)" :stroke-width="8"
                     :color="[{color:'#f56c6c',percentage:0},{color:'#e6a23c',percentage:50},{color:'#67c23a',percentage:90}]" />
      </el-card></el-col>
      <el-col :span="6"><el-card shadow="hover">
        <div class="stat"><span class="label">活跃告警</span><span class="val" :style="{color:s.alert_total>0?'#f56c6c':'#67c23a'}">{{ s.alert_total || 0 }}</span></div>
        <div class="sub" v-if="s.alerts?.length">
          <el-tag v-for="a in s.alerts" :key="a.severity" :type="sevTag(a.severity)" size="small" style="margin-right:4px">
            {{ a.severity }} {{ a.cnt }}<template v-if="a.unacked>0"> (未确认 {{ a.unacked }})</template>
          </el-tag>
        </div>
        <div class="sub" v-else style="color:#67c23a;font-size:13px">无活跃告警 ✓</div>
      </el-card></el-col>
      <el-col :span="6"><el-card shadow="hover">
        <div class="stat"><span class="label">最新巡检健康分</span><span class="val">{{ lastInspection?.health_score_avg || '-' }}</span></div>
        <div class="sub" style="color:#909399;font-size:12px">
          {{ lastInspection ? '设备 ' + lastInspection.total_devices + ' 台，异常 ' + lastInspection.abnormal_devices + ' 台' : '暂无巡检记录' }}
        </div>
        <div class="sub" style="color:#909399;font-size:12px" v-if="lastInspection?.finished_at">
          {{ lastInspection.finished_at.replace('T',' ').slice(0,19) }}
        </div>
      </el-card></el-col>
      <el-col :span="6"><el-card shadow="hover">
        <div class="stat"><span class="label">近24h日志</span><span class="val">{{ logTotal }}</span></div>
        <div class="sub" v-if="s.logs_24h?.length" style="font-size:12px;color:#909399">
          <span v-for="l in s.logs_24h.slice(0,4)" :key="l.severity" style="margin-right:8px">
            {{ sevName(l.severity) }}: {{ l.cnt }}
          </span>
        </div>
      </el-card></el-col>
    </el-row>

    <!-- 中间图表区 -->
    <el-row :gutter="14">
      <el-col :span="12"><el-card shadow="hover">
        <template #header><b>各机房设备在线率</b></template>
        <div ref="siteChartRef" style="height:260px"></div>
      </el-card></el-col>
      <el-col :span="12"><el-card shadow="hover">
        <template #header><b>告警级别分布</b></template>
        <div ref="alertChartRef" style="height:260px"></div>
      </el-card></el-col>
    </el-row>

    <!-- 底部信息区 -->
    <el-row :gutter="14">
      <el-col :span="12"><el-card shadow="hover">
        <template #header><b>机柜容量 TOP（剩余最少）</b></template>
        <el-table :data="s.capacity || []" size="small" stripe>
          <el-table-column prop="site" label="机房" width="120" />
          <el-table-column prop="rack" label="机柜" width="80" />
          <el-table-column label="已用/总U" min-width="200">
            <template #default="{row}">
              <el-progress :percentage="Math.round(row.used_u/row.u_total*100)" :stroke-width="14"
                           :color="row.used_u/row.u_total>0.8?'#f56c6c':row.used_u/row.u_total>0.6?'#e6a23c':'#67c23a'"
                           :format="() => row.used_u + '/' + row.u_total + 'U'" />
            </template>
          </el-table-column>
        </el-table>
      </el-card></el-col>
      <el-col :span="12"><el-card shadow="hover">
        <template #header><b>最近配置变更 & 快捷操作</b></template>
        <div style="display:flex;gap:8px;margin-bottom:12px">
          <el-button type="primary" size="small" @click="doCollect">立即采集</el-button>
          <el-button type="warning" size="small" @click="doInspect">执行巡检</el-button>
          <el-button size="small" @click="load">刷新</el-button>
        </div>
        <el-table :data="s.config_changes || []" size="small" stripe>
          <el-table-column prop="device_name" label="设备" min-width="120">
            <template #default="{row}">{{ row.device_name || '#' + row.device_id }}</template>
          </el-table-column>
          <el-table-column prop="changed_lines" label="变更行数" width="90">
            <template #default="{row}"><el-tag size="small" :type="row.changed_lines>10?'danger':row.changed_lines>0?'warning':'success'">{{ row.changed_lines }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="detected_at" label="时间" width="170">
            <template #default="{row}">{{ (row.detected_at||'').replace('T',' ').slice(0,19) }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!(s.config_changes||[]).length" description="暂无配置变更记录" :image-size="40" />
      </el-card></el-col>
    </el-row>
  </div>
</template>

<script setup>
import * as echarts from "echarts";
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import api from "../api";

const s = ref({});
const siteChartRef = ref(null);
const alertChartRef = ref(null);
let siteChart, alertChart;

const lastInspection = computed(() => (s.value.inspections || [])[0]);
const logTotal = computed(() => (s.value.logs_24h || []).reduce((a, l) => a + l.cnt, 0));
const pct = (a, b) => b ? Math.round((a / b) * 100) : 0;
const sevName = (v) => ["emerg","alert","crit","error","warning","notice","info","debug"][v] || v;
const sevTag = (sv) => sv === "critical" ? "danger" : sv === "major" ? "warning" : "info";

const load = async () => {
  s.value = await api.get("/system/dashboard/summary/");
  await nextTick();
  renderCharts();
};

const renderCharts = () => {
  if (siteChartRef.value) {
    if (siteChart) siteChart.dispose();
    siteChart = echarts.init(siteChartRef.value);
    const sites = s.value.sites || [];
    siteChart.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: ["在线", "离线"] },
      xAxis: { type: "category", data: sites.map((x) => x.site), axisLabel: { rotate: 20 } },
      yAxis: { type: "value", minInterval: 1 },
      series: [
        { name: "在线", type: "bar", stack: "total", data: sites.map((x) => x.online || 0),
          itemStyle: { color: "#67c23a" } },
        { name: "离线", type: "bar", stack: "total", data: sites.map((x) => x.offline || 0),
          itemStyle: { color: "#f56c6c" } },
      ],
    });
  }
  if (alertChartRef.value) {
    if (alertChart) alertChart.dispose();
    alertChart = echarts.init(alertChartRef.value);
    const colors = { critical: "#f56c6c", major: "#e6a23c", warning: "#e6a23c", info: "#909399" };
    const data = (s.value.alerts || []).map((a) => ({
      name: a.severity + " (" + a.cnt + ")", value: a.cnt,
      itemStyle: { color: colors[a.severity] || "#909399" },
    }));
    alertChart.setOption({
      tooltip: { trigger: "item" },
      series: [{ type: "pie", radius: ["40%", "70%"], data,
        label: { show: true, formatter: "{b}" },
        emphasis: { label: { show: true, fontSize: 14, fontWeight: "bold" } } }],
    });
  }
};

const doCollect = async () => {
  await api.post("/monitor/collect/", {});
  ElMessage.success("采集已下发，稍后刷新查看");
};
const doInspect = async () => {
  const tpl = await api.get("/inspects/templates/", { params: { page_size: 5 } });
  if (!tpl.results?.length) { ElMessage.warning("请先创建巡检模板"); return; }
  const task = await api.post("/inspects/tasks/", { name: "手动巡检", template: tpl.results[0].id, cron: "" });
  await api.post("/inspects/tasks/" + task.id + "/run/");
  ElMessage.success("巡检已下发");
};

onMounted(load);
onBeforeUnmount(() => { if (siteChart) siteChart.dispose(); if (alertChart) alertChart.dispose(); });
</script>

<style scoped>
.stat { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }
.stat .label { color: #909399; font-size: 13px; }
.stat .val { font-size: 32px; font-weight: 700; }
.sub { margin-bottom: 8px; font-size: 13px; }
</style>
