<script setup lang="ts">
import { Refresh, TrendCharts } from "@element-plus/icons-vue";
import { computed, onMounted, ref, watch } from "vue";

import { getKlineSymbols, getKlines } from "@/api";
import KlineChart from "@/components/KlineChart.vue";
import type { KlineBar, KlineResponse } from "@/types";

const INTERVALS = [
  { value: "1m", label: "1 分钟" },
  { value: "3m", label: "3 分钟" },
  { value: "5m", label: "5 分钟" },
  { value: "15m", label: "15 分钟" },
  { value: "30m", label: "30 分钟" },
  { value: "1h", label: "1 小时" },
  { value: "2h", label: "2 小时" },
  { value: "4h", label: "4 小时" },
  { value: "6h", label: "6 小时" },
  { value: "8h", label: "8 小时" },
  { value: "12h", label: "12 小时" },
  { value: "1d", label: "1 天" },
  { value: "3d", label: "3 天" },
  { value: "1w", label: "1 周" },
  { value: "1M", label: "1 月" },
];

const DAY_OPTIONS = [1, 2, 7, 14, 30, 90, 180, 365];

const symbol = ref("BTCUSDT");
const interval = ref("1m");
const days = ref(2);
const symbols = ref<string[]>([]);
const loading = ref(false);
const errorMessage = ref("");
const data = ref<KlineResponse | null>(null);

const intervalLabel = computed(
  () => INTERVALS.find((item) => item.value === interval.value)?.label ?? interval.value
);

const bars = computed(() => data.value?.bars ?? []);
const recent = computed(() => [...bars.value].slice(-12).reverse());

// Only the trailing bucket can still be forming; aggregated intervals and the
// raw 1m feed leave it unclosed until the full minute count has landed.
const lastIsForming = computed(() => {
  const rows = bars.value;
  return rows.length > 0 && rows[rows.length - 1].closed === false;
});

const latestClosed = computed(() => {
  const rows = bars.value;
  const index = lastIsForming.value ? rows.length - 2 : rows.length - 1;
  return index >= 0 ? rows[index] : null;
});

const summary = computed(() => {
  const rows = bars.value;
  if (rows.length === 0) return null;
  const first = rows[0];
  const last = latestClosed.value ?? rows[rows.length - 1];
  let high = first.h;
  let low = first.l;
  let volumeSum = 0;
  for (const bar of rows) {
    if (bar.h > high) high = bar.h;
    if (bar.l < low) low = bar.l;
    volumeSum += bar.v;
  }
  const change = first.o === 0 ? null : (last.c - first.o) / first.o;
  return { first, last, high, low, volumeSum, change };
});

onMounted(async () => {
  loading.value = true;
  await refreshSymbols();
  await load();
});

watch(interval, async () => {
  await refreshSymbols();
  await load();
});

async function refreshSymbols() {
  try {
    const payload = await getKlineSymbols(interval.value);
    symbols.value = payload.symbols;
    if (payload.symbols.length > 0 && !payload.symbols.includes(symbol.value)) {
      symbol.value = payload.symbols[0];
    }
  } catch {
    symbols.value = [];
  }
}

async function load() {
  const name = symbol.value.trim().toUpperCase();
  if (!name) return;
  symbol.value = name;
  loading.value = true;
  errorMessage.value = "";
  try {
    data.value = await getKlines({ symbol: name, interval: interval.value, days: days.value });
  } catch (error) {
    data.value = null;
    errorMessage.value = (error as Error).message;
  } finally {
    loading.value = false;
  }
}

function fmtPrice(value: number): string {
  const digits = value >= 100 ? 2 : value >= 1 ? 4 : 8;
  return value.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function fmtVolume(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

function fmtTime(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

function fmtPct(value: number | null): string {
  if (value == null || Number.isNaN(value)) return "n/a";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(2)}%`;
}

function tone(bar: KlineBar): string {
  return bar.c >= bar.o ? "green" : "red";
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>K 线</h1>
        <p>查看本地 Parquet 里已经收盘的行情。数据由采集任务写入，后台只读取，不向交易所请求。</p>
      </div>
      <div class="head-extra">
        <el-tag type="info" effect="plain">UTC</el-tag>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <el-card class="panel" shadow="never">
      <el-form inline @submit.prevent="load">
        <el-form-item label="交易对">
          <el-select
            v-model="symbol"
            filterable
            allow-create
            default-first-option
            style="width: 160px"
          >
            <el-option v-for="item in symbols" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="周期">
          <el-select v-model="interval" style="width: 120px">
            <el-option
              v-for="item in INTERVALS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="天数">
          <el-select v-model="days" style="width: 100px">
            <el-option v-for="item in DAY_OPTIONS" :key="item" :label="`${item} 天`" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="load">查看</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-alert
      v-if="errorMessage"
      :title="errorMessage"
      type="error"
      show-icon
      :closable="false"
      style="margin: 16px 0"
    />

    <el-alert
      v-if="data?.truncated"
      title="这个范围的 K 线超过单次上限，图表只保留最近 10000 根。可以缩短天数，或改用更大的周期。"
      type="warning"
      show-icon
      :closable="false"
      style="margin: 16px 0"
    />

    <el-alert
      v-if="lastIsForming && data && data.interval !== '1m'"
      :title="`最后一根 ${data.interval} K 线还在形成中，图上用空心虚线表示；指标和回测只使用已收盘的 K 线。`"
      type="info"
      show-icon
      :closable="false"
      style="margin: 16px 0"
    />

    <div v-if="!data && !errorMessage" class="empty-panel">
      <el-empty :description="loading ? '正在读取本地行情…' : '选择交易对后查看 K 线'" :image-size="116" />
    </div>

    <template v-else-if="data">
      <div v-if="bars.length === 0" class="empty-panel">
        <el-empty
          :description="`${data.symbol} ${data.interval} 在本地没有数据。先执行 make fetch，或换一个已采集的交易对。`"
          :image-size="116"
        />
      </div>

      <template v-else>
        <div v-if="summary" class="metric-grid kline-metrics">
          <div class="metric-card">
            <div class="metric-label">
              最新价{{ lastIsForming ? "（已收盘）" : "" }}
            </div>
            <div class="metric-value" :class="tone(summary.last)">{{ fmtPrice(summary.last.c) }}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">区间涨跌</div>
            <div class="metric-value" :class="summary.change != null && summary.change >= 0 ? 'green' : 'red'">
              {{ fmtPct(summary.change) }}
            </div>
          </div>
          <div class="metric-card">
            <div class="metric-label">最高</div>
            <div class="metric-value">{{ fmtPrice(summary.high) }}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">最低</div>
            <div class="metric-value">{{ fmtPrice(summary.low) }}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">成交量</div>
            <div class="metric-value">{{ fmtVolume(summary.volumeSum) }}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">根数</div>
            <div class="metric-value">{{ data.count.toLocaleString() }}</div>
          </div>
        </div>

        <el-card class="panel" shadow="never">
          <template #header>
            <div class="card-title">
              <el-icon><TrendCharts /></el-icon>
              {{ data.symbol }} · {{ intervalLabel }}
              <span class="aside">
                {{ fmtTime(summary!.first.t) }} → {{ fmtTime(summary!.last.t) }} UTC
                <template v-if="data.aggregated"> · 由 1 分钟聚合</template>
              </span>
            </div>
          </template>
          <KlineChart :bars="bars" />
        </el-card>

        <el-card class="panel" shadow="never">
          <template #header>
            <div class="card-title">
              最近 K 线
              <span class="aside">最新 {{ recent.length }} 根</span>
            </div>
          </template>
          <el-table :data="recent" size="small">
            <el-table-column label="时间 (UTC)" min-width="140">
              <template #default="{ row }">{{ fmtTime(row.t) }}</template>
            </el-table-column>
            <el-table-column label="开" align="right">
              <template #default="{ row }">{{ fmtPrice(row.o) }}</template>
            </el-table-column>
            <el-table-column label="高" align="right">
              <template #default="{ row }">{{ fmtPrice(row.h) }}</template>
            </el-table-column>
            <el-table-column label="低" align="right">
              <template #default="{ row }">{{ fmtPrice(row.l) }}</template>
            </el-table-column>
            <el-table-column label="收" align="right">
              <template #default="{ row }">
                <span :class="tone(row)">{{ fmtPrice(row.c) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="量" align="right">
              <template #default="{ row }">{{ fmtVolume(row.v) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </template>
    </template>
  </div>
</template>

<style scoped>
.panel {
  margin-bottom: 16px;
}

.kline-metrics {
  margin-bottom: 16px;
}

.panel :deep(.el-form) {
  margin-bottom: -18px;
}
</style>
