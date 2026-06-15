<script setup lang="ts">
import type { AlertStatus } from '../api/types';

defineProps<{ status: AlertStatus }>();

const statusMap: Record<AlertStatus, { label: string; color: string }> = {
  pending: { label: '待处理', color: '#FF4444' },
  processing: { label: '处理中', color: '#FFAA00' },
  resolved: { label: '已解决', color: '#4ECDC4' },
  closed: { label: '已关闭', color: '#888888' },
};
</script>

<template>
  <span class="status-tag" :style="{ color: statusMap[status].color }">
    {{ statusMap[status].label }}
  </span>
</template>

<style scoped>
.status-tag {
  font-size: 13px;
  font-weight: 500;
}
</style>
