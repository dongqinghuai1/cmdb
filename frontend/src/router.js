import { createRouter, createWebHistory } from "vue-router";

const routes = [
  { path: "/login", component: () => import("./pages/Login.vue") },
  {
    path: "/",
    component: () => import("./layout.vue"),
    redirect: "/dashboard",
    children: [
      { path: "dashboard", component: () => import("./pages/Dashboard.vue"), meta: { title: "工作台" } },
      { path: "dcim", component: () => import("./pages/Dcim.vue"), meta: { title: "机房管理" } },
      { path: "topo", component: () => import("./pages/Topo.vue"), meta: { title: "拓扑管理" } },
      { path: "ncm", component: () => import("./pages/Ncm.vue"), meta: { title: "配置管理" } },
      { path: "devices", component: () => import("./pages/Devices.vue"), meta: { title: "设备台账" } },
      { path: "devices/:id", component: () => import("./pages/Device360.vue"), meta: { title: "设备 360°" } },
      { path: "alerts", component: () => import("./pages/Alerts.vue"), meta: { title: "告警中心" } },
      { path: "inspects", component: () => import("./pages/Inspects.vue"), meta: { title: "巡检中心" } },
      { path: "system", component: () => import("./pages/System.vue"), meta: { title: "系统管理" } },
    ],
  },
];

const router = createRouter({ history: createWebHistory(), routes });

router.beforeEach((to) => {
  if (to.path !== "/login" && !localStorage.getItem("token")) return "/login";
});

export default router;
