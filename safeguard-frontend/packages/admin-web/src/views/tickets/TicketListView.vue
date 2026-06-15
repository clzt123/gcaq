<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { TicketCard } from '@safeguard/shared';
import type { TicketItem } from '@safeguard/shared';
import axios from 'axios';

const tickets = ref<TicketItem[]>([]);
const loading = ref(false);

onMounted(async () => {
  loading.value = true;
  try {
    const res = await axios.get('/api/v1/tickets');
    tickets.value = (res.data as any).items ?? (res.data as any) ?? [];
  } finally {
    loading.value = false;
  }
});

const activeTab = ref('all');
</script>

<template>
  <div class="ticket-list-page">
    <div class="tabs">
      <button :class="{ active: activeTab === 'all' }" @click="activeTab = 'all'">全部</button>
      <button :class="{ active: activeTab === 'pending' }" @click="activeTab = 'pending'">待处理</button>
      <button :class="{ active: activeTab === 'in_progress' }" @click="activeTab = 'in_progress'">处理中</button>
      <button :class="{ active: activeTab === 'completed' }" @click="activeTab = 'completed'">已完成</button>
    </div>
    <div class="ticket-cards" v-loading="loading">
      <TicketCard
        v-for="ticket in tickets"
        :key="ticket.id"
        :ticket="ticket"
      />
      <p v-if="!loading && tickets.length === 0" class="empty">暂无工单</p>
    </div>
  </div>
</template>

<style scoped>
.tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.tabs button {
  padding: 6px 14px; background: #161b22; border: 1px solid #30363d;
  border-radius: 6px; color: #8b949e; font-size: 13px; cursor: pointer;
}
.tabs button.active { background: #FF6B35; color: #fff; border-color: #FF6B35; }
.ticket-cards { display: flex; flex-direction: column; gap: 8px; }
.empty { text-align: center; color: #888; padding: 40px 0; }
</style>
