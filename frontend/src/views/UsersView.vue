<script setup lang="ts">
import { Plus, Refresh } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { onMounted, reactive, ref } from "vue";

import { createUser, listUsers } from "@/api";
import type { User } from "@/types";

const users = ref<User[]>([]);
const loading = ref(true);
const errorMessage = ref("");
const dialogVisible = ref(false);
const saving = ref(false);

const form = reactive({
  email: "",
  password: "",
  role: "user" as "admin" | "user",
});

onMounted(load);

async function load() {
  loading.value = true;
  errorMessage.value = "";
  try {
    users.value = await listUsers();
  } catch (error) {
    errorMessage.value = (error as Error).message;
  } finally {
    loading.value = false;
  }
}

function openDialog() {
  form.email = "";
  form.password = "";
  form.role = "user";
  dialogVisible.value = true;
}

async function submit() {
  if (!form.email.trim()) {
    ElMessage.warning("请输入邮箱");
    return;
  }
  if (form.password.length < 8) {
    ElMessage.warning("密码至少 8 位");
    return;
  }
  saving.value = true;
  try {
    await createUser(form.email.trim(), form.password, form.role);
    ElMessage.success("用户已创建");
    dialogVisible.value = false;
    await load();
  } catch (error) {
    ElMessage.error((error as Error).message);
  } finally {
    saving.value = false;
  }
}

function fmtTime(iso: string): string {
  return new Date(iso).toISOString().slice(0, 16).replace("T", " ");
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>用户管理</h1>
        <p>每个用户独立绑定 Binance API Key、独立拥有回测历史和策略配置。</p>
      </div>
      <div class="head-extra">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openDialog">新建用户</el-button>
      </div>
    </div>

    <el-alert
      v-if="errorMessage"
      :title="errorMessage"
      type="error"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <el-card class="panel" shadow="never">
      <el-table v-loading="loading" :data="users" size="default">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="email" label="邮箱" min-width="220" />
        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.role === 'admin' ? 'success' : 'info'">
              {{ row.role === "admin" ? "管理员" : "用户" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <span :class="row.status === 'active' ? 'green' : 'red'">
              {{ row.status === "active" ? "正常" : "禁用" }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间 (UTC)" width="180">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="新建用户" width="420px">
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="邮箱">
          <el-input v-model="form.email" type="email" placeholder="user@example.com" />
        </el-form-item>
        <el-form-item label="初始密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="至少 8 位"
          />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%">
            <el-option label="普通用户" value="user" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>
