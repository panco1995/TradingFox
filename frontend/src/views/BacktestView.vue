<script setup lang="ts">
import { Setting } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { getKlineSymbols, getStrategies, runBacktest } from "@/api";
import EquityChart from "@/components/EquityChart.vue";
import ParamForm from "@/components/ParamForm.vue";
import type { BacktestReport, StrategySpec, Trade } from "@/types";

const INTERVALS = [
  { value: "1m", label: "1 分钟" },
  { value: "5m", label: "5 分钟" },
  { value: "15m", label: "15 分钟" },
  { value: "1h", label: "1 小时" },
  { value: "4h", label: "4 小时" },
  { value: "1d", label: "1 天" },
];

const METRICS = [
  { key: "total_return", label: "总收益", kind: "pct" },
  { key: "cagr", label: "年化收益", kind: "pct" },
  { key: "max_drawdown", label: "最大回撤", kind: "pct" },
  { key: "sharpe", label: "Sharpe", kind: "ratio" },
  { key: "sortino", label: "Sortino", kind: "ratio" },
  { key: "calmar", label: "Calmar", kind: "ratio" },
  { key: "volatility", label: "年化波动", kind: "pct" },
  { key: "win_rate", label: "胜率", kind: "pct" },
  { key: "profit_factor", label: "盈亏比", kind: "ratio" },
  { key: "exposure", label: "仓位暴露", kind: "pct" },
  { key: "trades", label: "成交笔数", kind: "int" },
  { key: "fees_paid", label: "手续费", kind: "money" },
];

const strategies = ref<StrategySpec[]>([]);
const strategiesLoading = ref(true);
const strategiesError = ref("");
const strategyName = ref("");
const params = ref<Record<string, unknown>>({});
const running = ref(false);
const report = ref<BacktestReport | null>(null);
const errorMessage = ref("");

const route = useRoute();

const symbolOptions = ref<string[]>([]);
const symbolsLoading = ref(false);
const symbolsError = ref("");

const form = reactive({
  symbol: "BTCUSDT",
  days: 30,
  interval: "15m",
  cash: 10000,
  feeBps: 5,
  slippageBps: 2,
});

const spec = computed(
  () => strategies.value.find((item) => item.name === strategyName.value) ?? null
);

const reportSpec = computed(
  () => strategies.value.find((item) => item.name === report.value?.strategy) ?? null
);

const symbols = computed(() => {
  const symbol = form.symbol.trim().toUpperCase();
  return symbol ? [symbol] : [];
});

const metricItems = computed(() => {
  const metrics = report.value?.metrics ?? {};
  return METRICS.filter((metric) => metric.key in metrics).map((metric) => {
    const value = metrics[metric.key];
    return {
      key: metric.key,
      label: metric.label,
      text: formatMetric(metric.kind, value),
      cls: metricClass(metric.kind, value),
    };
  });
});

const monthlyRows = computed(() =>
  Object.entries(report.value?.monthly_returns ?? {}).map(([month, value]) => ({
    month,
    value,
  }))
);

const tradeRows = computed(() => [...(report.value?.trades ?? [])].reverse());

const paramsText = computed(() =>
  Object.entries(report.value?.params ?? {})
    .map(([key, value]) => `${key}=${value}`)
    .join("  ")
);

onMounted(async () => {
  await Promise.all([loadStrategies(), loadSymbols()]);
});

watch(
  () => form.interval,
  () => {
    void loadSymbols();
  }
);

watch(
  () => route.query.strategy,
  (value) => {
    if (typeof value !== "string" || value === strategyName.value) return;
    if (!strategies.value.some((item) => item.name === value)) return;
    applyStrategy(value);
  }
);

async function loadSymbols() {
  symbolsLoading.value = true;
  symbolsError.value = "";
  try {
    const available = (await getKlineSymbols(form.interval)).symbols;
    symbolOptions.value = available;
    const known = new Set(available);
    if (known.has(form.symbol)) {
      // Keep the current choice when it is still available at this interval.
    } else if (known.has("BTCUSDT")) {
      form.symbol = "BTCUSDT";
    } else {
      form.symbol = available[0] ?? "";
    }
  } catch (error) {
    symbolsError.value = (error as Error).message;
  } finally {
    symbolsLoading.value = false;
  }
}

async function loadStrategies() {
  strategiesLoading.value = true;
  strategiesError.value = "";
  try {
    strategies.value = await getStrategies();
    if (strategies.value.length === 0) {
      strategiesError.value = "没有已注册的策略，请先在 quant/strategies 下添加策略模块";
      return;
    }
    const saved = localStorage.getItem("quant.strategy");
    const requested = typeof route.query.strategy === "string" ? route.query.strategy : "";
    const initial =
      strategies.value.find((item) => item.name === requested) ??
      strategies.value.find((item) => item.name === saved) ??
      strategies.value[0];
    applyStrategy(initial.name);
  } catch (error) {
    strategiesError.value = (error as Error).message;
  } finally {
    strategiesLoading.value = false;
  }
}

function applyStrategy(name: string) {
  strategyName.value = name;
  const found = strategies.value.find((item) => item.name === name);
  params.value = found ? { ...found.defaults } : {};
}

async function submit() {
  if (running.value) return;
  if (!spec.value) {
    ElMessage.warning("请先选择策略");
    return;
  }
  if (symbols.value.length === 0) {
    ElMessage.warning("请选择一个交易对");
    return;
  }
  const days = Math.round(form.days);
  if (days < 1 || days > 3650) {
    ElMessage.warning("回看天数需要在 1 到 3650 之间");
    return;
  }

  running.value = true;
  errorMessage.value = "";
  try {
    report.value = await runBacktest({
      strategy: strategyName.value,
      symbols: symbols.value,
      days,
      interval: form.interval,
      initial_cash: form.cash,
      fee_rate: form.feeBps / 10000,
      slippage_bps: form.slippageBps,
      params: params.value,
    });
    localStorage.setItem("quant.strategy", strategyName.value);
    ElMessage.success("回测完成");
  } catch (error) {
    errorMessage.value = (error as Error).message;
    ElMessage.error(errorMessage.value);
  } finally {
    running.value = false;
  }
}

// -------------------------------------------------------------- formatting

function formatMetric(kind: string, value: number | null | undefined): string {
  if (value == null) return "n/a";
  if (kind === "pct") return `${(value * 100).toFixed(2)}%`;
  if (kind === "ratio") return value.toFixed(3);
  if (kind === "int") return String(Math.round(value));
  if (kind === "money") return fmtMoney(value);
  return String(value);
}

function metricClass(kind: string, value: number | null | undefined): string {
  if (value == null) return "na";
  if (kind === "pct" || kind === "money") {
    if (value > 0) return "pos";
    if (value < 0) return "neg";
  }
  return "";
}

function fmtMoney(value: number | null | undefined): string {
  if (value == null) return "n/a";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtPct(value: number | null | undefined): string {
  return value == null ? "n/a" : `${(value * 100).toFixed(2)}%`;
}

function fmtQty(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 8 });
}

function fmtPrice(value: number): string {
  const digits = value >= 100 ? 2 : value >= 1 ? 4 : 8;
  return value.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function fmtTime(iso: string | null): string {
  return iso ? iso.slice(0, 16).replace("T", " ") : "-";
}

function fmtShortTime(iso: string): string {
  return iso.slice(5, 16).replace("T", " ");
}

function pnlText(trade: Trade): string {
  const value = trade.realized_pnl || 0;
  if (value === 0) return "-";
  return `${value > 0 ? "+" : ""}${fmtMoney(value)}`;
}

function pnlClass(trade: Trade): string {
  if (trade.realized_pnl > 0) return "green";
  if (trade.realized_pnl < 0) return "red";
  return "";
}

async function copyPath() {
  if (!report.value?.report_dir) return;
  try {
    await navigator.clipboard.writeText(report.value.report_dir);
    ElMessage.success("报告路径已复制");
  } catch {
    ElMessage.warning("浏览器不允许复制，请手动选择路径");
  }
}

function downloadReport() {
  if (!report.value) return;
  const blob = new Blob([JSON.stringify(report.value, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `backtest-${report.value.strategy}-${report.value.start ?? "report"}.json`;
  link.click();
  URL.revokeObjectURL(url);
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>策略回测</h1>
        <p>选择已注册策略、调整参数，用本地 Parquet 行情回测。信号在 K 线收盘产生，成交在下一根开盘价执行。</p>
      </div>
      <div class="head-extra">
        <el-tag type="info" effect="plain">数据源：本地 Parquet</el-tag>
        <el-tag type="success" effect="plain">手数参与率 1%</el-tag>
      </div>
    </div>

    <el-row :gutter="18">
      <el-col :xs="24" :lg="8" :xl="7" class="col-left">
        <el-card class="panel" shadow="never">
          <template #header>
            <div class="card-title">
              <el-icon><Setting /></el-icon>
              回测配置
              <span class="aside">UTC</span>
            </div>
          </template>

          <el-alert
            v-if="strategiesError"
            :title="strategiesError"
            type="error"
            show-icon
            :closable="false"
            style="margin-bottom: 14px"
          />

          <el-form label-position="top" @submit.prevent>
            <el-form-item label="策略">
              <el-select
                v-model="strategyName"
                :loading="strategiesLoading"
                style="width: 100%"
                placeholder="选择策略"
                @change="applyStrategy"
              >
                <el-option
                  v-for="item in strategies"
                  :key="item.name"
                  :value="item.name"
                  :label="`${item.title} · ${item.name}`"
                />
              </el-select>
            </el-form-item>

            <template v-if="spec">
              <p class="muted">{{ spec.description }}</p>
              <div class="tag-row">
                <el-tag
                  v-for="tag in spec.tags"
                  :key="tag"
                  size="small"
                  type="info"
                  effect="plain"
                >
                  {{ tag }}
                </el-tag>
              </div>
            </template>

            <el-divider class="form-divider" content-position="left">策略参数</el-divider>
            <ParamForm v-model="params" :spec="spec" />

            <el-divider class="form-divider" content-position="left">行情</el-divider>
            <el-form-item label="交易对">
              <el-select
                v-model="form.symbol"
                filterable
                :loading="symbolsLoading"
                :disabled="!symbolsLoading && symbolOptions.length === 0"
                placeholder="选择交易对"
                no-data-text="本地暂无行情数据"
                style="width: 100%"
              >
                <el-option
                  v-for="symbol in symbolOptions"
                  :key="symbol"
                  :value="symbol"
                  :label="symbol"
                />
              </el-select>
              <p v-if="symbolsError" class="field-hint error-text">{{ symbolsError }}</p>
              <p v-else-if="!symbolsLoading && symbolOptions.length === 0" class="field-hint">
                本地还没有可用的行情数据，请先到「数据采集」添加交易对并回填。
              </p>
              <p v-else class="field-hint">只列出本地已有 K 线数据的交易对。</p>
            </el-form-item>

            <el-row :gutter="10">
              <el-col :span="12">
                <el-form-item label="回看天数">
                  <el-input-number
                    v-model="form.days"
                    :min="1"
                    :max="3650"
                    controls-position="right"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="K 线周期">
                  <el-select v-model="form.interval" style="width: 100%">
                    <el-option
                      v-for="item in INTERVALS"
                      :key="item.value"
                      :value="item.value"
                      :label="item.label"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>

            <el-divider class="form-divider" content-position="left">资金与成本</el-divider>
            <el-row :gutter="10">
              <el-col :span="12">
                <el-form-item label="初始资金 (USDT)">
                  <el-input-number
                    v-model="form.cash"
                    :min="100"
                    :step="1000"
                    controls-position="right"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="手续费 (bps)">
                  <el-input-number
                    v-model="form.feeBps"
                    :min="0"
                    :max="100"
                    :step="0.5"
                    controls-position="right"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
            </el-row>

            <el-form-item label="滑点 (bps)">
              <el-input-number
                v-model="form.slippageBps"
                :min="0"
                :max="100"
                :step="0.5"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>

            <p class="field-hint">
              5 bps = 0.05%，按 taker 保守估计。买入受单根 K 线 1% 成交量限制，卖出不受限。
            </p>

            <el-button
              class="run-button"
              type="primary"
              size="large"
              :loading="running"
              :disabled="!spec"
              @click="submit"
            >
              {{ running ? "回测中…" : "运行回测" }}
            </el-button>
          </el-form>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="16" :xl="17">
        <el-alert
          v-if="errorMessage"
          :title="errorMessage"
          type="error"
          show-icon
          :closable="false"
          style="margin-bottom: 14px"
        />

        <div v-if="!report" class="empty-panel">
          <el-empty
            :description="
              running ? '正在运行回测…' : '运行一次回测后，这里会显示绩效、权益曲线与成交记录'"
            :image-size="116"
          />
        </div>

        <div v-else class="report">
          <el-card class="panel" shadow="never">
            <div class="report-head">
              <h2>{{ reportSpec?.title ?? report.strategy }}</h2>
              <span class="report-meta">
                {{ report.symbols.join(" / ") }} · {{ fmtTime(report.start) }} →
                {{ fmtTime(report.end) }} · {{ report.bars_processed.toLocaleString() }} bars
              </span>
              <div class="head-extra">
                <el-button size="small" @click="downloadReport">下载 JSON</el-button>
              </div>
            </div>
            <div class="report-sub">
              初始资金 <b>{{ fmtMoney(report.initial_cash) }}</b> → 期末权益
              <b>{{ fmtMoney(report.final_equity) }}</b>
            </div>
            <div class="params-line">{{ paramsText }}</div>

            <el-divider class="form-divider" />

            <div class="metric-grid">
              <div v-for="item in metricItems" :key="item.key" class="metric-card">
                <div class="metric-label">{{ item.label }}</div>
                <div class="metric-value" :class="item.cls">{{ item.text }}</div>
              </div>
            </div>

            <template v-if="monthlyRows.length">
              <div class="monthly-section">
                <div class="monthly-title">月度收益 · UTC 月末权益</div>
                <div class="monthly-grid">
                  <div v-for="row in monthlyRows" :key="row.month" class="monthly-chip">
                    <span class="month">{{ row.month }}</span>
                    <span :class="row.value >= 0 ? 'green' : 'red'">{{ fmtPct(row.value) }}</span>
                  </div>
                </div>
              </div>
            </template>
          </el-card>

          <el-row :gutter="16">
            <el-col :span="24">
              <el-card class="panel" shadow="never">
                <template #header>
                  <div class="card-title">
                    权益曲线
                    <span class="aside">{{ report.equity_curve.length }} 个采样点</span>
                  </div>
                </template>
                <EquityChart :points="report.equity_curve" color="#34d399" />
              </el-card>
            </el-col>
            <el-col :span="24">
              <el-card class="panel" shadow="never">
                <template #header>
                  <div class="card-title">
                    回撤
                    <span class="aside">水下曲线，单位 %</span>
                  </div>
                </template>
                <EquityChart :points="report.drawdown_curve" color="#f87171" percent />
              </el-card>
            </el-col>
          </el-row>

          <el-card class="panel" shadow="never">
            <template #header>
              <div class="card-title">
                成交记录
                <span class="aside">
                  最近 {{ report.trades.length }} 笔 / 共 {{ report.trades_total }} 笔
                </span>
              </div>
            </template>
            <el-table :data="tradeRows" size="small" max-height="420">
              <el-table-column label="时间 (UTC)" width="132">
                <template #default="{ row }">
                  <div>{{ fmtShortTime(row.time) }}</div>
                  <div class="cell-sub">{{ row.symbol }}</div>
                </template>
              </el-table-column>
              <el-table-column label="方向" width="56" align="center">
                <template #default="{ row }">
                  <el-tag
                    size="small"
                    effect="plain"
                    :type="row.side === 'buy' ? 'success' : 'warning'"
                  >
                    {{ row.side === "buy" ? "买" : "卖" }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="数量" align="right" min-width="96">
                <template #default="{ row }">{{ fmtQty(row.qty) }}</template>
              </el-table-column>
              <el-table-column label="价格" align="right" min-width="96">
                <template #default="{ row }">{{ fmtPrice(row.price) }}</template>
              </el-table-column>
              <el-table-column label="手续费" align="right" width="78">
                <template #default="{ row }">{{ fmtMoney(row.fee) }}</template>
              </el-table-column>
              <el-table-column label="盈亏" align="right" width="88">
                <template #default="{ row }">
                  <span :class="pnlClass(row)">{{ pnlText(row) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="原因" min-width="100">
                <template #default="{ row }">{{ row.reason || "-" }}</template>
              </el-table-column>
            </el-table>
          </el-card>

          <div class="report-foot">
            <span>报告文件：{{ report.report_dir || "-" }}</span>
            <el-button v-if="report.report_dir" link size="small" @click="copyPath">
              复制路径
            </el-button>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.col-left {
  margin-bottom: 18px;
}

.report-head .head-extra {
  margin-left: auto;
}

.report .el-col {
  margin-bottom: 16px;
}

@media (min-width: 1200px) {
  .col-left {
    margin-bottom: 0;
  }
}
</style>
