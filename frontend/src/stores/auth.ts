import { defineStore } from "pinia";
import { computed, ref } from "vue";

import {
  bootstrap as apiBootstrap,
  getMe,
  login as apiLogin,
  logout as apiLogout,
} from "@/api";
import type { User } from "@/types";

export const useAuthStore = defineStore("auth", () => {
  const user = ref<User | null>(null);
  const ready = ref(false);
  const loading = ref(false);
  const isAdmin = computed(() => user.value?.role === "admin");

  async function load() {
    if (ready.value) return;
    try {
      user.value = (await getMe()).user;
    } catch {
      user.value = null;
    } finally {
      ready.value = true;
    }
  }

  async function signIn(email: string, password: string) {
    loading.value = true;
    try {
      user.value = (await apiLogin(email, password)).user;
      ready.value = true;
    } finally {
      loading.value = false;
    }
  }

  async function signUpAdmin(email: string, password: string) {
    loading.value = true;
    try {
      user.value = (await apiBootstrap(email, password)).user;
      ready.value = true;
    } finally {
      loading.value = false;
    }
  }

  async function signOut() {
    try {
      await apiLogout();
    } catch {
      // The cookie may already be gone; clearing local state is enough.
    }
    clear();
  }

  function clear() {
    user.value = null;
    ready.value = true;
  }

  return { user, ready, loading, isAdmin, load, signIn, signUpAdmin, signOut, clear };
});
