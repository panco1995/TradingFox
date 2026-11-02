<script setup lang="ts">
import { Delete, Key, Refresh } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { onMounted, reactive, ref } from "vue";

import { deleteCredentials, getCredentials, putCredentials } from "@/api";
import type { CredentialsInfo } from "@/types";

const info = ref<CredentialsInfo | null>(null);
const loading = ref(true);
const saving = ref(false);
const errorMessage = ref("");

const form = reactive({
  api_key: "",
  secret: "",
  label: "Binance testnet",
});

onMounted(load);

async function load() {
  loading.value = true;
  errorMessage.value = "";
  try {
    info.value = await getCredentials();
  } catch (error) {
    errorMessage.value = (error as Error).message;
  } finally {
    loading.value = false;
  }
}

async function save() {
  if (!form.api_key.trim() || !form.secret.trim()) {
    ElMessage.warning("请填写 API Key 和 Secret");
    return;
  }
  saving.value = true;
  try {
    info.value = await putCredentials({
      api_key: form.api_key.trim(),
      secret: form.secret.trim(),
      label: form.label.trim(),
    });
    form.api_key = "";
    form.secret = "";
    ElMessage.success("API Key 已加密保存");
  } catch (error) {
    ElMessage.error((error as Error).message);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  try {
    await ElMessageBox.confirm(
      "删除后，该账户将无法用于实盘或测试网下单。确定删除吗？",
      "删除 API Key",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  try {
    await deleteCredentials();
    info.value = { exchange: "BINANCE", configured: false };
    ElMessage.success("已删除");
  } catch (error) {
    ElMessage.error((error as Error).message);
  }
}

function fmtTime(iso?: string): string {
  return iso ? new Date(iso).toISOString().slice(0, 16).replace("T", " ") : "-";
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>账户设置</h1>
        <p>Binance API Key 只用于该账号自己的交易实例，服务端加密存储，接口永不返回明文。</p>
      </div>
      <div class="head-extra">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
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

    <el-row :gutter="18">
      <el-col :xs="24" :lg="10">
        <el-card class="panel" shadow="never">
          <template #header>
            <div class="card-title">
              <el-icon><Key /></el-icon>
              Binance 现货
              <span class="aside">{{ info?.configured ? "已配置" : "未配置" }}</span>
            </div>
          </template>

          <el-skeleton v-if="loading" :rows="4" animated />

          <template v-else>
            <el-descriptions :column="1" size="small" border>
              <el-descriptions-item label="状态">
                <el-tag
                  size="small"
                  effect="plain"
                  :type="info?.configured ? 'success' : 'info'"
                >
                  {{ info?.configured ? "已保存" : "未保存" }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="API Key">
                <span class="mono">{{ info?.api_key_hint || "-" }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="备注">
                {{ info?.label || "-" }}
              </el-descriptions-item>
              <el-descriptions-item label="更新时间 (UTC)">
                <span class="mono">{{ fmtTime(info?.updated_at) }}</span>
              </el-descriptions-item>
            </el-descriptions>

            <el-alert
              type="warning"
              :closable="false"
              show-icon
              style="margin-top: 16px"
              title="只勾选现货交易权限，禁止提现；先用 testnet key 联调。"
            />

            <el-button
              v-if="info?.configured"
              class="run-button"
              type="danger"
              plain
              :icon="Delete"
              @click="remove"
            >
              删除已保存的 Key
            </el-button>
          </template>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="14">
        <el-card class="panel" shadow="never">
          <template #header>
            <div class="card-title">
              {{ info?.configured ? "更新 API Key" : "添加 API Key" }}
              <span class="aside">AES-256-GCM</span>
            </div>
          </template>

          <el-form label-position="top" @submit.prevent="save">
            <el-form-item label="API Key">
              <el-input
                v-model="form.api_key"
                placeholder="从 Binance 控制台复制"
                autocomplete="off"
                spellcheck="false"
              />
            </el-form-item>
            <el-form-item label="Secret Key">
              <el-input
                v-model="form.secret"
                type="password"
                show-password
                placeholder="只在保存时提交一次"
                autocomplete="new-password"
              />
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="form.label" placeholder="例如 Binance testnet" maxlength="64" />
            </el-form-item>

            <p class="field-hint">
              密钥使用服务端 <code>CREDENTIALS_KEY</code> 加密后写入 MySQL。即使数据库泄露，
              没有主密钥也无法还原。这里不会显示完整 Key，只能重新录入覆盖。
            </p>

            <el-button class="run-button" type="primary" size="large" :loading="saving" @click="save">
              加密保存
            </el-button>
          </el-form>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>
