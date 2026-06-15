<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import { RiskBadge } from '@safeguard/shared';
import type { TicketItem } from '@safeguard/shared';
import axios from 'axios';

const route = useRoute();
const ticket = ref<TicketItem | null>(null);
const loading = ref(true);

onMounted(async () => {
  try {
    const id = route.params.id as string;
    const res = await axios.get(`/api/v1/tickets/${id}`);
    ticket.value = (res.data as any).data ?? (res.data as any);
  } finally { loading.value = false; }
});
</script>

<template>
  <div class="ticket-detail" v-if="ticket">
    <div class="header">
      <RiskBadge :level="ticket.risk_level" />
      <h2>{{ ticket.title }}</h2>
    </div>
    <div class="info">
      <div class="info-row"><span>位置</span><span>{{ ticket.location }}</span></div>
      <div class="info-row"><span>创建时间</span><span>{{ ticket.created_at }}</span></div>
      <div class="info-row"><span>截止日期</span><span>{{ ticket.due_date || '无' }}</span></div>
      <div class="info-row"><span>状态</span><span>{{ ticket.status }}</span></div>
    </div>
    <button class="complete-btn">✅ 标记完成</button>
  </div>
  <div v-else-if="loading" class="loading">加载中...</div>
</template>

<style scoped>
.ticket-detail { padding: 16px; }
.header { margin-bottom: 20px; }
.header h2 { margin: 10px 0 0; font-size: 20px; color: #fff; }
.info { background: #161b22; border-radius: 10px; padding: 16px; margin-bottom: 20px; }
.info-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #21262d; font-size: 14px; }
.info-row:last-child { border-bottom: none; }
.info-row span:first-child { color: #888; }
.info-row span:last-child { color: #c9d1d9; }
.complete-btn { width: 100%; padding: 14px; background: #4ECDC4; color: #000; border: none; border-radius: 10px; font-size: 16px; font-weight: 700; cursor: pointer; }
.loading { text-align: center; color: #888; padding: 40px; }
</style>
