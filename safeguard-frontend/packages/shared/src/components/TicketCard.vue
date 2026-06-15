<script setup lang="ts">
import type { TicketItem } from '../api/types';
import RiskBadge from './RiskBadge.vue';

defineProps<{ ticket: TicketItem }>();
defineEmits<{ click: [id: string] }>();

const ticketStatusMap: Record<string, string> = {
  pending: '待分配',
  assigned: '已分配',
  in_progress: '处理中',
  completed: '已完成',
  closed: '已关闭',
};
</script>

<template>
  <div class="ticket-card" @click="$emit('click', ticket.id)">
    <div class="ticket-left">
      <RiskBadge :level="ticket.risk_level" />
    </div>
    <div class="ticket-center">
      <h4>{{ ticket.title }}</h4>
      <p class="meta">{{ ticket.location }} · {{ ticket.created_at }}</p>
    </div>
    <div class="ticket-right">
      <span class="ticket-status">{{ ticketStatusMap[ticket.status] }}</span>
    </div>
  </div>
</template>

<style scoped>
.ticket-card {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; background: #161b22; border-radius: 8px;
  cursor: pointer; border: 1px solid transparent;
}
.ticket-card:hover { background: #1c2333; border-color: #30363d; }
.ticket-center { flex: 1; }
.ticket-center h4 { margin: 0 0 4px; font-size: 14px; color: #e6e6e6; }
.meta { margin: 0; font-size: 12px; color: #888; }
.ticket-status { font-size: 12px; color: #aaa; background: #21262d; padding: 2px 8px; border-radius: 4px; }
</style>
