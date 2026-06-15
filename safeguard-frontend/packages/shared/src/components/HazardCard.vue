<script setup lang="ts">
import type { AlertItem } from '../api/types';
import RiskBadge from './RiskBadge.vue';
import StatusTag from './StatusTag.vue';

defineProps<{ alert: AlertItem }>();
defineEmits<{ click: [id: string] }>();
</script>

<template>
  <div class="hazard-card" @click="$emit('click', alert.id)">
    <div class="card-header">
      <RiskBadge :level="alert.risk_level" />
      <StatusTag :status="alert.status" />
    </div>
    <div class="card-body">
      <h4>{{ alert.hazard_type }}</h4>
      <p class="location">{{ alert.location }}</p>
      <p class="time">{{ alert.created_at }}</p>
    </div>
    <div class="card-footer">
      <span class="source-tag" :class="alert.source">
        {{ alert.source === 'auto' ? '自动检测' : '人工上报' }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.hazard-card {
  padding: 12px 16px;
  background: #161b22;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
  border: 1px solid transparent;
}
.hazard-card:hover { background: #1c2333; border-color: #30363d; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.card-body h4 { margin: 0 0 4px; font-size: 15px; color: #e6e6e6; }
.location, .time { margin: 0; font-size: 12px; color: #888; }
.card-footer { margin-top: 8px; }
.source-tag { padding: 1px 6px; border-radius: 3px; font-size: 11px; }
.source-tag.auto { background: #1a3a2e; color: #4ECDC4; }
.source-tag.manual { background: #2a1a00; color: #FFAA00; }
</style>
