<script setup lang="ts">
import { LineChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import type { CurvePoint } from "@/types";

echarts.use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer]);

const props = withDefaults(
  defineProps<{
    points: CurvePoint[];
    color?: string;
    percent?: boolean;
  }>(),
  { color: "#34d399", percent: false }
);

const el = ref<HTMLDivElement>();
let chart: echarts.EChartsType | null = null;
let observer: ResizeObserver | null = null;

function rgba(hex: string, alpha: number): string {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function compact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (abs >= 100_000) return `${(value / 1_000).toFixed(0)}k`;
  return value.toLocaleString("en-US", {
    maximumFractionDigits: abs >= 1 ? 0 : 4,
  });
}

function tick(ms: number): string {
  const iso = new Date(ms).toISOString();
  return `${iso.slice(5, 10)} ${iso.slice(11, 16)}`;
}

function formatValue(value: number): string {
  return props.percent ? `${value.toFixed(2)}%` : compact(value);
}

function option(): echarts.EChartsCoreOption {
  const data = props.points.map((point) => [point.t, point.v]);
  return {
    animationDuration: 260,
    backgroundColor: "transparent",
    grid: { left: 68, right: 18, top: 18, bottom: 44 },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#111821",
      borderColor: "#243244",
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: "#e6edf5", fontSize: 12 },
      formatter: (params: unknown) => {
        const items = params as Array<{ value: [string, number] }>;
        const first = items[0];
        if (!first) return "";
        return `${first.value[0].slice(0, 16).replace("T", " ")}<br/><b>${formatValue(
          first.value[1]
        )}</b>`;
      },
    },
    xAxis: {
      type: "time",
      axisLine: { lineStyle: { color: "#243244" } },
      axisTick: { show: false },
      axisLabel: { color: "#8b9bb0", hideOverlap: true, formatter: tick },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: {
        color: "#8b9bb0",
        formatter: (value: number) => formatValue(value),
      },
      splitLine: { lineStyle: { color: "#1b2733" } },
    },
    dataZoom: [{ type: "inside", throttle: 60 }],
    series: [
      {
        type: "line",
        data,
        showSymbol: false,
        smooth: false,
        lineStyle: { color: props.color, width: 1.7 },
        itemStyle: { color: props.color },
        areaStyle: { color: rgba(props.color, 0.16) },
      },
    ],
  };
}

function render() {
  if (!el.value) return;
  if (!props.points.length) {
    chart?.clear();
    return;
  }
  if (!chart) {
    chart = echarts.init(el.value);
  }
  chart.setOption(option(), true);
}

watch(() => props.points, render, { deep: true });

onMounted(async () => {
  await nextTick();
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
  <div ref="el" class="chart-box" />
</template>
