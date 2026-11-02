<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { getAuthStatus } from "@/api";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const email = ref("");
const password = ref("");
const confirm = ref("");
const needsSetup = ref(false);
const checking = ref(true);
const errorMessage = ref("");
const statusError = ref("");

const title = computed(() => (needsSetup.value ? "创建管理员" : "登录"));
const description = computed(() =>
  needsSetup.value
    ? "首次部署。这个账号将成为管理员，之后由它创建其他用户。"
    : "使用管理员分配的账号登录，查看策略、回测和账户配置。"
);

onMounted(async () => {
  try {
    needsSetup.value = (await getAuthStatus()).needs_setup;
  } catch (error) {
    statusError.value = (error as Error).message;
  } finally {
    checking.value = false;
  }
});

async function submit() {
  errorMessage.value = "";
  if (!email.value.trim()) {
    errorMessage.value = "请输入邮箱";
    return;
  }
  if (password.value.length < 8) {
    errorMessage.value = "密码至少 8 位";
    return;
  }
  if (needsSetup.value && password.value !== confirm.value) {
    errorMessage.value = "两次输入的密码不一致";
    return;
  }

  try {
    if (needsSetup.value) {
      await auth.signUpAdmin(email.value.trim(), password.value);
    } else {
      await auth.signIn(email.value.trim(), password.value);
    }
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/";
    await router.replace(redirect);
  } catch (error) {
    errorMessage.value = (error as Error).message;
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-glow" />
    <div class="login-card">
      <div class="login-brand">
        <span class="brand-dot" />
        <span>量化交易后台</span>
        <span class="brand-sub">LAB</span>
      </div>

      <h1>{{ title }}</h1>
      <p class="login-desc">{{ description }}</p>

      <el-alert
        v-if="statusError"
        :title="`后端状态不可用：${statusError}`"
        type="error"
        show-icon
        :closable="false"
        style="margin-bottom: 14px"
      />
      <el-alert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        show-icon
        :closable="false"
        style="margin-bottom: 14px"
      />

      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="邮箱">
          <el-input
            v-model="email"
            type="email"
            autocomplete="username"
            placeholder="you@example.com"
            :disabled="checking || auth.loading"
            @keyup.enter="submit"
          />
        </el-form-item>

        <el-form-item label="密码">
          <el-input
            v-model="password"
            type="password"
            show-password
            autocomplete="current-password"
            placeholder="至少 8 位"
            :disabled="checking || auth.loading"
            @keyup.enter="submit"
          />
        </el-form-item>

        <el-form-item v-if="needsSetup" label="确认密码">
          <el-input
            v-model="confirm"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="再输入一次"
            :disabled="checking || auth.loading"
            @keyup.enter="submit"
          />
        </el-form-item>

        <el-button
          native-type="submit"
          type="primary"
          size="large"
          class="login-button"
          :loading="auth.loading"
          :disabled="checking || Boolean(statusError)"
        >
          {{ needsSetup ? "创建并进入" : "登录" }}
        </el-button>
      </el-form>

      <div class="login-foot">
        <span>UTC only · Binance spot</span>
        <span>v0.1</span>
      </div>
    </div>
  </div>
</template>
