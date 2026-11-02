<script setup lang="ts">
import { Monitor, Plus, Refresh } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { addSymbol, getCollectorStatus, removeSymbol } from "@/api";
import type { CollectorStatus, SymbolCoverage } from "@/types";

const POLL_MS = 10_000;

const status = ref<CollectorStatus | null>(null);
const loading = ref(false);
const errorMessage = ref("");
const autoRefresh = ref(true);
const lastLoadedAt = ref<Date | null>(null);
const newSymbol = ref("");
const adding = ref(false);
const removingSymbol = ref("");
let timer: number | undefined;

const collector = computed(() => status.value?.collector ?? null);
const rows = computed(() => status.value?.symbols ?? []);

const stateLabel = computed(() => {
  if (!collector.value) return "未知";
  if (collector.value.running) return "运行中";
  if (collector.value.state === "stopped") return "已停止";
  if (collector.value.state) return "心跳超时";
  return "未启动";
});

const stateType = computed(() => {
  if (!collector.value) return "info";
  if (collector.value.running) return "success";
  if (collector.value.state) return "danger";
  return "warning";
});

const staleCount = computed(() => rows.value.filter((row) => row.stale).length);

const summaryCards = computed(() => {
  const info = collector.value;
  if (!info) return [];
  return [
    { label: "运行状态", value: stateLabel.value },
    { label: "心跳", value: fmtAge(info.heartbeat_age_seconds) },
    { label: "断线重连", value: fmtCount(info.connects) },
    { label: "进程 PID", value: info.pid == null ? "-" : String(info.pid) },
  ];
});

onMounted(async () => {
  await load();
  startTimer();
});

onBeforeUnmount(() => {
  stopTimer();
});

function startTimer() {
  stopTimer();
  if (!autoRefresh.value) return;
  timer = window.setInterval(load, POLL_MS);
}

function stopTimer() {
  if (timer) window.clearInterval(timer);
  timer = undefined;
}

function toggleAutoRefresh(value: boolean) {
  autoRefresh.value = value;
  if (value) startTimer();
  else stopTimer();
}

async function load() {
  loading.value = true;
  errorMessage.value = "";
  try {
    status.value = await getCollectorStatus("1m");
    lastLoadedAt.value = new Date();
  } catch (error) {
    errorMessage.value = (error as Error).message;
  } finally {
    loading.value = false;
  }
}

// The backend asks the exchange first: an unknown or halted pair is rejected
// and nothing is saved, so the list only ever contains tradable symbols.
async function submitSymbol() {
  const symbol = newSymbol.value.trim().toUpperCase();
  if (!symbol) {
    ElMessage.warning("请输入交易对，例如 SOLUSDT");
    return;
  }
  adding.value = true;
  try {
    const result = await addSymbol(symbol);
    ElMessage.success(result.message || `${symbol} 已加入采集列表`);
    newSymbol.value = "";
    await load();
  } catch (error) {
    ElMessage.error((error as Error).message);
  } finally {
    adding.value = false;
  }
}

async function dropSymbol(row: SymbolCoverage) {
  try {
    await ElMessageBox.confirm(
      `停止采集 ${row.symbol}？已下载的历史数据会保留，可以随时重新加回来。`,
      "移除交易对",
      { type: "warning", confirmButtonText: "停止采集", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }

  removingSymbol.value = row.symbol;
  try {
    const result = await removeSymbol(row.symbol);
    ElMessage.success(result.message || `${row.symbol} 已移出采集列表`);
    await load();
  } catch (error) {
    ElMessage.error((error as Error).message);
  } finally {
    removingSymbol.value = "";
  }
}

function fmtAge(seconds: number | null): string {
  if (seconds == null) return "-";
  if (seconds < 60) return `${seconds.toFixed(0)} 秒前`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)} 分钟前`;
  return `${(seconds / 3600).toFixed(1)} 小时前`;
}

function fmtCount(value: number | null): string {
  return value == null ? "-" : value.toLocaleString("en-US");
}

function fmtLag(seconds: number | null): string {
  if (seconds == null) return "-";
  if (seconds < 120) return `${seconds.toFixed(0)} 秒`;
  if (seconds < 7200) return `${(seconds / 60).toFixed(0)} 分钟`;
  return `${(seconds / 3600).toFixed(1)} 小时`;
}

function fmtSize(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

function fmtTime(iso: string | null): string {
  return iso ? iso.slice(0, 19).replace("T", " ") : "-";
}

// Crypto prices span many orders of magnitude: BTC needs 2 decimals, small
// alts need 8. Show significant digits instead of a fixed precision.
function fmtPrice(value: number | null): string {
  if (value == null) return "-";
  if (value >= 1000) {
    return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (value >= 1) return value.toFixed(4);
  return value.toPrecision(4).replace(/0+$/, "").replace(/\.$/, "");
}

function rowClass({ row }: { row: SymbolCoverage }): string {
  if (row.stale || !row.subscribed) return "row-stale";
  return "";
}

function lagType(row: SymbolCoverage): "success" | "warning" | "danger" | "info" {
  if (row.stale) return "danger";
  if (row.lag_seconds != null && row.lag_seconds > 180) return "warning";
  return "success";
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>数据采集</h1>
        <p>
          实时采集器是独立进程，这里读取它写入的心跳文件。心跳超过 20 秒没有更新即判定为未运行。
        </p>
      </div>
      <div class="head-extra">
        <span v-if="lastLoadedAt" class="refresh-note">
          更新于 {{ lastLoadedAt.toLocaleTimeString("zh-CN", { hour12: false }) }}
        </span>
        <el-switch
          :model-value="autoRefresh"
          inline-prompt
          active-text="自动"
          inactive-text="手动"
          @change="toggleAutoRefresh($event as boolean)"
        />
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

    <el-alert
      v-if="collector && !collector.running"
      title="采集器当前没有在运行。行情不会自动更新，K 线和回测只能看到磁盘上已有的数据。"
      type="warning"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <el-alert
      v-else-if="staleCount > 0"
      :title="`有 ${staleCount} 个交易对的最新 K 线明显落后。检查采集器日志，或先用 make fetch 补数据。`"
      type="warning"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <el-card class="panel" shadow="never">
      <template #header>
        <div class="card-title">
          <el-icon><Monitor /></el-icon>
          采集器状态
          <span class="aside">
            <el-tag size="small" :type="stateType" effect="plain">{{ stateLabel }}</el-tag>
          </span>
        </div>
      </template>

      <el-skeleton v-if="!collector && loading" :rows="3" animated />

      <div v-else-if="collector" class="metric-grid">
        <div v-for="card in summaryCards" :key="card.label" class="metric-card">
          <div class="metric-label">{{ card.label }}</div>
          <div class="metric-value" :class="{ 'value-small': card.label === '订阅' }">
            {{ card.value }}
          </div>
        </div>
      </div>
    </el-card>

    <el-card class="panel" shadow="never">
      <template #header>
        <div class="card-title">
          <el-icon><Plus /></el-icon>
          添加交易对
          <span class="aside">先向交易所校验，可用才写入</span>
        </div>
      </template>

      <div class="add-symbol">
        <el-input
          v-model="newSymbol"
          placeholder="例如 SOLUSDT"
          maxlength="24"
          clearable
          style="max-width: 260px"
          @keyup.enter="submitSymbol"
        >
          <template #prepend>交易对</template>
        </el-input>
        <el-button type="primary" :loading="adding" @click="submitSymbol">查询并添加</el-button>
        <span class="add-hint">
          添加后采集器会自动重连并开始接收该交易对，无需重启；历史数据需要用 make fetch 或回填命令补。
        </span>
      </div>
    </el-card>

    <el-card class="panel" shadow="never">
      <template #header>
        <div class="card-title">
          交易对更新时间
          <span class="aside">共 {{ rows.length }} 个，按交易日历 UTC</span>
        </div>
      </template>

      <el-table
        v-loading="loading && !status"
        :data="rows"
        size="small"
        :row-class-name="rowClass"
        empty-text="本地还没有行情数据"
      >
        <el-table-column label="交易对" min-width="130">
          <template #default="{ row }">
            <div class="symbol-cell">
              <span class="symbol-name">{{ row.symbol }}</span>
              <el-tag v-if="row.subscribed" size="small" type="success" effect="plain">订阅中</el-tag>
              <el-tag v-else size="small" type="info" effect="plain">未订阅</el-tag>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="最新价" min-width="130" align="right">
          <template #default="{ row }">
            <span class="price">{{ fmtPrice(row.close) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="最后更新" min-width="170">
          <template #default="{ row }">
            <div class="mono">{{ fmtTime(row.last) }}</div>
            <div class="cell-sub">UTC</div>
          </template>
        </el-table-column>

        <el-table-column label="延迟" width="110" align="right">
          <template #default="{ row }">
            <el-tag size="small" :type="lagType(row)" effect="plain">
              {{ fmtLag(row.lag_seconds) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="最早数据" min-width="170">
          <template #default="{ row }">
            <div class="mono">{{ fmtTime(row.first) }}</div>
            <div class="cell-sub">UTC</div>
          </template>
        </el-table-column>

        <el-table-column label="根数" width="110" align="right">
          <template #default="{ row }">{{ fmtCount(row.bars) }}</template>
        </el-table-column>

        <el-table-column label="文件 / 大小" width="130" align="right">
          <template #default="{ row }">
            <div>{{ row.files }} 个</div>
            <div class="cell-sub">{{ fmtSize(row.bytes) }}</div>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="150" align="right">
          <template #default="{ row }">
            <el-button
              link
              size="small"
              @click="$router.push({ name: 'klines', query: { symbol: row.symbol } })"
            >
              看 K 线
            </el-button>
            <el-button
              link
              size="small"
              type="danger"
              :loading="removingSymbol === row.symbol"
              :disabled="!row.subscribed"
              @click="dropSymbol(row)"
            >
              移除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.panel {
  margin-bottom: 16px;
}

.refresh-note {
  color: var(--app-muted);
  font-size: 12px;
}

.add-symbol {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.add-hint {
  color: var(--app-muted);
  font-size: 12px;
}

.metric-value.value-small {
  font-size: 12.5px;
}

.symbol-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.symbol-name {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
  font-weight: 600;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
  font-size: 12px;
}

.price {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--app-text);
}

:deep(.row-stale) {
  background-color: rgba(248, 113, 113, 0.06);
}
</style>
