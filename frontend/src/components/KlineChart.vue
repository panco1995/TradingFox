<script setup lang="ts">
import { BarChart, CandlestickChart } from "echarts/charts";
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

import type { KlineBar } from "@/types";

echarts.use([
  CandlestickChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  AxisPointerComponent,
  CanvasRenderer,
]);

const props = defineProps<{
  bars: KlineBar[];
}>();

const el = ref<HTMLDivElement>();
let chart: echarts.EChartsType | null = null;
let observer: ResizeObserver | null = null;

const UP = "#34d399";
const DOWN = "#f87171";

function price(value: number): string {
  const digits = value >= 100 ? 2 : value >= 1 ? 4 : 8;
  return value.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function volume(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(2)}k`;
  return value.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

function stamp(iso: string): string {
  return iso.slice(5, 16).replace("T", " ");
}

function option(): echarts.EChartsCoreOption {
  const categories = props.bars.map((bar) => stamp(bar.t));
  // A bar that is still forming gets a hollow body so it never reads as final.
  const candles = props.bars.map((bar, index) => {
    const body: [number, number, number, number] = [bar.o, bar.c, bar.l, bar.h];
    if (bar.closed === false) {
      return {
        value: body,
        itemStyle: {
          color: "transparent",
          color0: "transparent",
          borderColor: index === props.bars.length - 1 ? UP : "#8b9bb0",
          borderColor0: DOWN,
          borderType: "dashed",
        },
      };
    }
    return body;
  });
  const volumes = props.bars.map((bar) => ({
    value: bar.v,
    itemStyle: { color: bar.c >= bar.o ? UP : DOWN },
  }));
  const visible = Math.min(120, props.bars.length);
  const start = props.bars.length <= visible ? 0 : ((props.bars.length - visible) / props.bars.length) * 100;

  return {
    animationDuration: 260,
    backgroundColor: "transparent",
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: 72, right: 18, top: 16, bottom: 168 },
      { left: 72, right: 18, height: 64, bottom: 72 },
    ],
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      backgroundColor: "#111821",
      borderColor: "#243244",
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: "#e6edf5", fontSize: 12 },
      formatter: (params: unknown) => {
        const items = (Array.isArray(params) ? params : [params]) as Array<{ dataIndex?: number }>;
        const index = items.find((item) => item.dataIndex != null)?.dataIndex;
        if (index == null) return "";
        const bar = props.bars[index];
        if (!bar) return "";
        const tone = bar.c >= bar.o ? UP : DOWN;
        const lines = [
          stamp(bar.t),
          `开 <b>${price(bar.o)}</b>`,
          `高 <b>${price(bar.h)}</b>`,
          `低 <b>${price(bar.l)}</b>`,
          `收 <b style="color:${tone}">${price(bar.c)}</b>`,
          `量 <b>${volume(bar.v)}</b>`,
        ];
        if (bar.closed === false) {
          lines.push('<span style="color:#fbbf24">未收盘</span>');
        }
        return lines.join("<br/>");
      },
    },
    xAxis: [
      {
        type: "category",
        data: categories,
        boundaryGap: true,
        axisLine: { lineStyle: { color: "#243244" } },
        axisTick: { show: false },
        axisLabel: { color: "#8b9bb0", hideOverlap: true },
        splitLine: { show: false },
      },
      {
        type: "category",
        data: categories,
        gridIndex: 1,
        boundaryGap: true,
        axisLabel: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true,
        axisLabel: { color: "#8b9bb0", formatter: (value: number) => price(value) },
        splitLine: { lineStyle: { color: "#1b2733" } },
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 2,
        axisLabel: { color: "#8b9bb0", formatter: (value: number) => volume(value) },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1], start, end: 100 },
      {
        type: "slider",
        xAxisIndex: [0, 1],
        start,
        end: 100,
        height: 18,
        bottom: 16,
        borderColor: "#1e2a38",
        backgroundColor: "#0e141c",
        fillerColor: "rgba(52, 211, 153, 0.16)",
        handleStyle: { color: UP, borderColor: UP },
        textStyle: { color: "#8b9bb0" },
        dataBackground: {
          lineStyle: { color: "#243244" },
          areaStyle: { color: "#16202c" },
        },
      },
    ],
    series: [
      {
        type: "candlestick",
        data: candles,
        itemStyle: {
          color: UP,
          color0: DOWN,
          borderColor: UP,
          borderColor0: DOWN,
        },
      },
      {
        type: "bar",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
      },
    ],
  };
}

function render() {
  if (!el.value) return;
  if (!props.bars.length) {
    chart?.clear();
    return;
  }
  if (!chart) {
    chart = echarts.init(el.value);
  }
  chart.setOption(option(), true);
}

watch(() => props.bars, render);

onMounted(() => {
  render();
  if (el.value) {
    observer = new ResizeObserver(() => chart?.resize());
    observer.observe(el.value);
  }
});

onBeforeUnmount(() => {
  observer?.disconnect();
  observer = null;
  chart?.dispose();
  chart = null;
});
</script>

<template>
  <div ref="el" class="kline-chart" />
</template>

<style scoped>
.kline-chart {
  width: 100%;
  height: 560px;
}
</style>
