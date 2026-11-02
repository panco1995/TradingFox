import { createApp } from "vue";
import { createPinia } from "pinia";
import ElementPlus from "element-plus";
import zhCn from "element-plus/es/locale/lang/zh-cn";

import "element-plus/dist/index.css";
import "element-plus/theme-chalk/dark/css-vars.css";
import "@/styles.css";

import App from "@/App.vue";
import router from "@/router";
import { useAuthStore } from "@/stores/auth";

document.documentElement.classList.add("dark");

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.use(ElementPlus, { locale: zhCn });
app.mount("#app");

// A 401 from any business endpoint means the session expired while the page
// was open. Drop local state and send the user back to the login page.
window.addEventListener("auth:expired", () => {
  const auth = useAuthStore();
  auth.clear();
  if (router.currentRoute.value.name !== "login") {
    router.replace({ name: "login", query: { redirect: router.currentRoute.value.fullPath } });
  }
});
