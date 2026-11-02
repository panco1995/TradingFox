import { createRouter, createWebHistory } from "vue-router";

import AdminLayout from "@/layout/AdminLayout.vue";
import { useAuthStore } from "@/stores/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("@/views/LoginView.vue"),
      meta: { title: "登录", publicPage: true },
    },
    {
      path: "/",
      component: AdminLayout,
      children: [
        {
          path: "",
          name: "backtest",
          component: () => import("@/views/BacktestView.vue"),
          meta: { title: "策略回测" },
        },
        {
          path: "klines",
          name: "klines",
          component: () => import("@/views/KlineView.vue"),
          meta: { title: "K 线" },
        },
        {
          path: "strategies",
          name: "strategies",
          component: () => import("@/views/StrategiesView.vue"),
          meta: { title: "策略库" },
        },
        {
          path: "account",
          name: "account",
          component: () => import("@/views/AccountView.vue"),
          meta: { title: "账户设置" },
        },
        {
          path: "users",
          name: "users",
          component: () => import("@/views/UsersView.vue"),
          meta: { title: "用户管理", roles: ["admin"] },
        },
      ],
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (!auth.ready) {
    await auth.load();
  }

  if (to.meta.publicPage) {
    if (auth.user && to.name === "login") {
      return { name: "backtest" };
    }
    return true;
  }

  if (!auth.user) {
    return { name: "login", query: { redirect: to.fullPath } };
  }

  const roles = to.meta.roles as string[] | undefined;
  if (roles && !roles.includes(auth.user.role)) {
    return { name: "backtest" };
  }
  return true;
});

export default router;
