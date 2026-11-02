<script setup lang="ts">
import {
  Collection,
  DataAnalysis,
  Key,
  Monitor,
  SwitchButton,
  TrendCharts,
  User,
} from "@element-plus/icons-vue";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const now = ref(new Date());
let timer: number | undefined;

onMounted(() => {
  timer = window.setInterval(() => {
    now.value = new Date();
  }, 1000);
});

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer);
});

const title = computed(() => (route.meta.title as string | undefined) ?? "控制台");
const clock = computed(() => {
  const iso = now.value.toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 19)} UTC`;
});
const roleLabel = computed(() => (auth.isAdmin ? "管理员" : "用户"));

type Command = "account" | "users" | "logout";

async function onCommand(command: Command) {
  if (command === "account") {
    await router.push({ name: "account" });
    return;
  }
  if (command === "users") {
    await router.push({ name: "users" });
    return;
  }
  await auth.signOut();
  await router.replace({ name: "login" });
}
</script>

<template>
  <el-container class="shell">
    <el-aside class="sidebar" width="var(--app-sidebar)">
      <div class="brand">
        <span class="brand-dot" />
        <span class="brand-text">量化交易后台</span>
        <span class="brand-sub">LAB</span>
      </div>

      <el-menu :default-active="route.path" router>
        <el-menu-item index="/">
          <el-icon><DataAnalysis /></el-icon>
          <span>策略回测</span>
        </el-menu-item>
        <el-menu-item index="/klines">
          <el-icon><TrendCharts /></el-icon>
          <span>K 线</span>
        </el-menu-item>
        <el-menu-item index="/collector">
          <el-icon><Monitor /></el-icon>
          <span>数据采集</span>
        </el-menu-item>
        <el-menu-item index="/strategies">
          <el-icon><Collection /></el-icon>
          <span>策略库</span>
        </el-menu-item>
        <el-menu-item index="/account">
          <el-icon><Key /></el-icon>
          <span>账户设置</span>
        </el-menu-item>
        <el-menu-item v-if="auth.isAdmin" index="/users">
          <el-icon><User /></el-icon>
          <span>用户管理</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-foot">v0.1 · LOCAL</div>
    </el-aside>

    <el-container class="main">
      <el-header class="header" height="64px">
        <span class="header-crumb">量化交易</span>
        <span class="header-title">{{ title }}</span>
        <div class="header-right">
          <el-tag size="small" type="success" effect="plain" round>TESTNET</el-tag>
          <span class="clock">{{ clock }}</span>

          <el-dropdown trigger="click" @command="onCommand">
            <span class="user-menu">
              <span class="user-avatar">{{ (auth.user?.email ?? "?").slice(0, 1).toUpperCase() }}</span>
              <span class="user-email">{{ auth.user?.email }}</span>
              <el-tag size="small" effect="plain" :type="auth.isAdmin ? 'success' : 'info'">
                {{ roleLabel }}
              </el-tag>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="account">
                  <el-icon><Key /></el-icon>
                  账户设置
                </el-dropdown-item>
                <el-dropdown-item v-if="auth.isAdmin" command="users">
                  <el-icon><User /></el-icon>
                  用户管理
                </el-dropdown-item>
                <el-dropdown-item command="logout" divided>
                  <el-icon><SwitchButton /></el-icon>
                  退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="content">
        <RouterView />
      </el-main>
    </el-container>
  </el-container>
</template>
