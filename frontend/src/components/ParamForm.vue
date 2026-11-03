<script setup lang="ts">
import { computed } from "vue";

import type { ParamProperty, StrategySpec } from "@/types";

const props = defineProps<{
  spec: StrategySpec | null;
  modelValue: Record<string, unknown>;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: Record<string, unknown>];
}>();

interface Entry {
  key: string;
  property: ParamProperty;
  required: boolean;
}

const entries = computed<Entry[]>(() => {
  const schema = props.spec?.params_schema;
  const properties = schema?.properties ?? {};
  const required = new Set(schema?.required ?? []);
  return Object.entries(properties).map(([key, property]) => ({
    key,
    property,
    required: required.has(key),
  }));
});

function update(key: string, value: unknown) {
  emit("update:modelValue", { ...props.modelValue, [key]: value });
}

function numberValue(entry: Entry): number | undefined {
  const raw = props.modelValue[entry.key] ?? entry.property.default;
  const value = Number(raw);
  return Number.isFinite(value) ? value : undefined;
}

function booleanValue(entry: Entry): boolean {
  return Boolean(props.modelValue[entry.key] ?? entry.property.default);
}

function stringValue(entry: Entry): string {
  const raw = props.modelValue[entry.key] ?? entry.property.default ?? "";
  return String(raw);
}

function hintFor(property: ParamProperty): string {
  if (property.description) return property.description;
  const parts: string[] = [];
  if (property.minimum != null) parts.push(`最小 ${property.minimum}`);
  if (property.maximum != null) parts.push(`最大 ${property.maximum}`);
  return parts.join(" · ");
}

function onNumber(entry: Entry, value: number | null | undefined) {
  if (typeof value === "number" && Number.isFinite(value)) {
    update(entry.key, value);
  }
}
</script>

<template>
  <div v-if="entries.length" class="param-grid">
    <el-form-item
      v-for="entry in entries"
      :key="entry.key"
      :label="entry.property.title || entry.key"
    >
      <el-select
        v-if="entry.property.enum"
        :model-value="stringValue(entry)"
        style="width: 100%"
        @update:model-value="update(entry.key, $event)"
      >
        <el-option
          v-for="option in entry.property.enum"
          :key="String(option)"
          :label="String(option)"
          :value="option"
        />
      </el-select>

      <el-switch
        v-else-if="entry.property.type === 'boolean'"
        :model-value="booleanValue(entry)"
        @update:model-value="update(entry.key, $event)"
      />

      <el-input
        v-else-if="entry.property.type !== 'number' && entry.property.type !== 'integer'"
        :model-value="stringValue(entry)"
        @update:model-value="update(entry.key, $event)"
      />

      <el-input-number
        v-else
        :model-value="numberValue(entry)"
        :min="entry.property.minimum"
        :max="entry.property.maximum"
        :step="entry.property.type === 'integer' ? 1 : 'any'"
        :precision="entry.property.type === 'integer' ? 0 : undefined"
        controls-position="right"
        style="width: 100%"
        @update:model-value="onNumber(entry, $event)"
      />

      <div v-if="hintFor(entry.property)" class="field-hint">
        {{ hintFor(entry.property) }}
      </div>
    </el-form-item>
  </div>

  <p v-else class="muted">该策略没有可调参数。</p>
</template>

<style scoped>
.param-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 12px;
}
</style>
