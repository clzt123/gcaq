<script setup lang="ts">
import type { RiskLevel } from '../api/types';

defineProps<{ level: RiskLevel }>();

const levelMap: Record<RiskLevel, { label: string; color: string }> = {
  L1: { label: '紧急', color: '#FF4444' },
  L2: { label: '严重', color: '#FFAA00' },
  L3: { label: '一般', color: '#4ECDC4' },
  L4: { label: '低', color: '#45B7D1' },
};
</script>

<template>
  <span
    class="risk-badge"
    :style="{ background: levelMap[level].color, color: level === 'L4' ? '#000' : '#fff' }"
  >
    {{ level }} {{ levelMap[level].label }}
  </span>
</template>

<style scoped>
.risk-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
</style>
