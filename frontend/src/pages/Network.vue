<template>
  <div>
    <el-row :gutter="12">
      <el-col :span="6"><el-card shadow="never"><div class="stat">
        <div class="n">{{ meta.devices_covered ?? 0 }}</div><div class="l">覆盖设备（区域/站点过滤预留）</div>
      </div></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><div class="stat">
        <div class="n">{{ nb.total }}</div><div class="l">路由邻居 · full {{ nb.full }} / down {{ nb.down }}</div>
      </div></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><div class="stat">
        <div class="n">{{ L.summary.down ?? 0 }} / {{ L.summary.high_error ?? 0 }}</div><div class="l">接口 下行 / 高错包</div>
      </div></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><div class="stat">
        <div class="n">{{ AP.online }} / {{ AP.rows.length }}</div><div class="l">AP 在线/总数 · VLAN {{ V.rows.length }} 个</div>
      </div></el-card></el-col>
    </el-row>

    <el-row :gutter="12" style="margin-top:12px">
      <el-col :span="14">
        <el-card shadow="never">
          <template #header><b>路由与邻居（OSPF/BGP）</b>
            <el-tag v-if="nb.full" size="small" type="success" style="margin-left:8px">full {{ nb.full }}</el-tag>
            <el-tag v-if="nb.down" size="small" type="danger" style="margin-left:8px">down {{ nb.down }}</el-tag>
            <el-tag v-if="nb.other" size="small" type="info" style="margin-left:8px">other {{ nb.other }}</el-tag>
          </template>
          <el-table :data="N.rows" size="small" max-height="330" @row-click="openDev">
            <el-table-column prop="name" label="设备" min-width="110" />
            <el-table-column prop="site" label="站点" width="90" />
            <el-table-column prop="protocol" label="协议" width="60" />
            <el-table-column prop="neighbor_addr" label="邻居地址" width="130" />
            <el-table-column label="状态" width="80">
              <template #default="{row}">
                <el-tag size="small" :type="row.state === 'full' ? 'success' : row.state === 'down' ? 'danger' : 'info'">
                  {{ row.state || "unknown" }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="最后见到" width="150">
              <template #default="{row}">{{ fmt2(row.last_seen_at) || "-" }}</template>
            </el-table-column>
          </el-table>
          <div class="empty" v-if="!N.rows.length">暂无邻居数据——对设备开启路由协议采集后（cmdb_routingneighbor）自动出现。</div>
        </el-card>
        <el-card shadow="never" style="margin-top:12px">
          <template #header><b>路由快照</b>
            <el-tag size="small" type="info">{{ R.rows.length }} 台设备 · {{ R.total_prefixes }} 条前缀</el-tag>
          </template>
          <el-table :data="R.rows" size="small" max-height="300" @row-click="openDev">
            <el-table-column prop="name" label="设备" min-width="110" />
            <el-table-column prop="site" label="站点" width="90" />
            <el-table-column prop="count" label="前缀数" width="80" />
            <el-table-column label="快照时间" width="160">
              <template #default="{row}">{{ fmt2(row.snapshot_at) }}</template>
            </el-table-column>
            <el-table-column label="新鲜度" width="90">
              <template #default="{row}">
                <el-tag size="small" :type="row.age_days > 7 ? 'warning' : 'success'">{{ row.age_days }} 天前</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="route_hash" label="hash" width="90" />
          </el-table>
          <div class="empty" v-if="!R.rows.length">暂无路由快照——NCM 路由采集（RouteTableSnapshot）写入后自动出现。</div>
        </el-card>
      </el-col>

      <el-col :span="10">
        <el-card shadow="never">
          <template #header><b>链路状态（下行 / 高错包，含光功率）</b></template>
          <el-table :data="L.rows" size="small" max-height="330" @row-click="openDev">
            <el-table-column prop="name" label="设备" width="96" />
            <el-table-column prop="if_name" label="接口" width="86" />
            <el-table-column label="状态" width="66">
              <template #default="{row}">
                <el-tag size="small" :type="row.oper_status === 'up' ? 'success' : 'danger'">
                  {{ row.oper_status }}</el-tag></template>
            </el-table-column>
            <el-table-column label="错包‰ 入/出" width="100">
              <template #default="{row}">
                {{ row.stat ? row.stat.in_errors_rate + "/" + row.stat.out_errors_rate : "-" }}</template>
            </el-table-column>
            <el-table-column label="光功率 收/发(dBm)" width="120">
              <template #default="{row}">
                {{ row.stat && row.stat.optical_rx_dbm ? row.stat.optical_rx_dbm + " / " + (row.stat.optical_tx_dbm || "-") : "-" }}</template>
            </el-table-column>
          </el-table>
          <div class="empty" v-if="!L.rows.length">当前无下行/高错包接口（统计范围：admin=up 且已采集 stat 的接口）。</div>
        </el-card>
        <el-card shadow="never" style="margin-top:12px">
          <template #header><b>无线 AP（{{ AP.rows.length }}）</b></template>
          <el-table :data="AP.rows" size="small" max-height="210" @row-click="openDev">
            <el-table-column prop="name" label="设备" width="104" />
            <el-table-column prop="ap_name" label="AP 名" width="104" />
            <el-table-column prop="ap_model" label="型号" width="84" />
            <el-table-column prop="client_count" label="客户端" width="64" />
            <el-table-column prop="channel_5g" label="5G" width="56" />
          </el-table>
          <div class="empty" v-if="!AP.rows.length">无 AP——系统管理→AP 同步（WLC show ap summary）后自动出现。</div>
        </el-card>
        <el-card shadow="never" style="margin-top:12px">
          <template #header><b>扩展采集位（已预留建模，接入即展示）</b></template>
          <div v-for="e in EXT" :key="e.key" class="extrow">
            <el-tag size="small" type="info">{{ e.label }}</el-tag>
            <span style="color:#909399">{{ e.note }}</span>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import api from "../api";

const router = useRouter();
const data = ref(null);
const meta = computed(() => data.value?.meta || {});
const nb = computed(() => {
  const bs = data.value?.neighbors?.by_state || {};
  const rows = data.value?.neighbors?.rows || [];
  return { total: rows.length, full: bs.full || 0, down: bs.down || 0,
           other: (bs.total || 0) - (bs.full || 0) - (bs.down || 0) };
});
const N = computed(() => data.value?.neighbors || { rows: [] });
const R = computed(() => data.value?.routes || { rows: [], total_prefixes: 0 });
const L = computed(() => data.value?.links || { summary: {}, rows: [] });
const AP = computed(() => {
  const rows = data.value?.ap?.rows || [];
  return { rows, online: rows.filter((a) => a.status === "online").length };
});
const V = computed(() => data.value?.vlans || { rows: [] });
const EXT = computed(() => data.value?.extensions || []);

const fmt2 = (s) => (s || "").replace("T", " ").slice(0, 19);
const openDev = (row) => { if (row.device_id) router.push("/devices/" + row.device_id); };
onMounted(async () => { data.value = await api.get("/cmdb/devices/network-overview/"); });
</script>

<style scoped>
.stat { text-align: center; padding: 6px 0; }
.stat .n { font-size: 24px; font-weight: 700; }
.stat .l { color: #909399; font-size: 12px; margin-top: 2px; }
.empty { color: #909399; font-size: 12px; padding: 10px 0; }
.extrow { display: flex; gap: 8px; align-items: baseline; font-size: 13px; margin-bottom: 7px; }
:deep(.el-table__row) { cursor: pointer; }
</style>
