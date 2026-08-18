import axios from "axios";
import { ElMessage } from "element-plus";

const api = axios.create({ baseURL: "/api/v1" });

api.interceptors.request.use((cfg) => {
  const t = localStorage.getItem("token");
  if (t) cfg.headers.Authorization = "Bearer " + t;
  return cfg;
});

api.interceptors.response.use(
  (r) => r.data,
  (err) => {
    const detail = err.response?.data?.detail || err.message;
    if (err.response?.status === 401 && location.pathname !== "/login") {
      localStorage.removeItem("token");
      location.href = "/login";
    } else {
      ElMessage.error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return Promise.reject(err);
  }
);

export default api;
