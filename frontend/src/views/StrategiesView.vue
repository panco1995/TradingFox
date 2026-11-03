<script setup lang="ts">
import { Refresh } from "@element-plus/icons-vue";
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { getStrategies } from "@/api";
import type { ParamProperty, StrategySpec } from "@/types";

interface ParamRow {
  key: string;
  label: string;
  type: string;
  range: string;
  defaultValue: string;
}

const strategies = ref<StrategySpec[]>([]);
const loading = ref(true);
const errorMessage = ref("");

const router = useRouter();

onMounted(load);

function openBacktest(name: string) {
  void router.push({ name: "backtest", query: { strategy: name } });
}

async function load() {
  loading.value = true;
  errorMessage.value = "";
  try {
    strategies.value = await getStrategies();
  } catch (error) {
    errorMessage.value = (error as Error).message;
  } finally {
    loading.value = false;
  }
}

function typeLabel(property: ParamProperty): string {
  if (property.enum) return "枚举";
  if (property.type === "integer") return "整数";
  if (property.type === "number") return "小数";
  if (property.type === "boolean") return "开关";
  return "文本";
}

function rangeLabel(property: ParamProperty): string {
  if (property.enum) return property.enum.map(String).join(" / ");
  const parts: string[] = [];
  if (property.minimum != null) parts.push(`≥ ${property.minimum}`);
  if (property.maximum != null) parts.push(`≤ ${property.maximum}`);
  return parts.join(" 且 ") || "-";
}

function paramRows(spec: StrategySpec): ParamRow[] {
  const properties = spec.params_schema.properties ?? {};
  return Object.entries(properties).map(([key, property]) => ({
    key,
    label: property.title || key,
    type: typeLabel(property),
    range: rangeLabel(property),
    defaultValue: String(spec.defaults[key] ?? property.default ?? "-"),
  }));
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>策略库</h1>
        <p>策略是仓库内的代码插件；新增 quant/strategies 下的模块后会自动出现在这里。</p>
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

    <el-skeleton v-if="loading" :rows="8" animated />

    <div v-else class="strategy-grid">
      <el-card
        v-for="item in strategies"
        :key="item.name"
        class="panel strategy-card"
        shadow="never"
      >
        <h3>{{ item.title }}</h3>
        <div class="strategy-name">{{ item.name }} · v{{ item.version }}</div>

        <div class="tag-row">
          <el-tag v-for="tag in item.tags" :key="tag" size="small" type="info" effect="plain">
            {{ tag }}
          </el-tag>
        </div>

        <p class="strategy-desc">{{ item.description }}</p>

        <el-table :data="paramRows(item)" size="small" class="schema-table">
          <el-table-column prop="label" label="参数" min-width="104" />
          <el-table-column prop="type" label="类型" width="64" />
          <el-table-column prop="range" label="范围" min-width="96" />
          <el-table-column prop="defaultValue" label="默认" width="76" align="right" />
        </el-table>

        <div class="strategy-actions">
          <el-button type="primary" plain size="small" @click="openBacktest(item.name)">
            用此策略回测
          </el-button>
        </div>
      </el-card>
    </div>

    <el-empty v-if="!loading && !errorMessage && strategies.length === 0" description="没有已注册的策略" />
  </div>
</template>

<style scoped>
.strategy-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
