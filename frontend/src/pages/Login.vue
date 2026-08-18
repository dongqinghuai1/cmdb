<template>
  <div class="login-bg">
    <el-card class="card">
      <h2 style="text-align:center">nops 智能运维 CMDB 平台</h2>
      <el-form :model="form" label-position="top" @keyup.enter="submit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="admin" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password />
        </el-form-item>
        <el-button type="primary" style="width:100%" :loading="loading" @click="submit">登 录</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import api from "../api";

const form = reactive({ username: "admin", password: "" });
const loading = ref(false);

const submit = async () => {
  loading.value = true;
  try {
    const r = await api.post("/auth/login/", form);
    localStorage.setItem("token", r.access);
    ElMessage.success("登录成功");
    location.href = "/";
  } finally {
    loading.value = false;
  }
};
</script>

<style scoped>
.login-bg { height: 100vh; display: flex; align-items: center; justify-content: center;
            background: linear-gradient(135deg, #001529 0%, #003a70 100%); }
.card { width: 380px; }
</style>
