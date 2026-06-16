<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { TicketCard, apiClient } from '@safeguard/shared';
import type { TicketItem } from '@safeguard/shared';

const router = useRouter();
const tickets = ref<TicketItem[]>([]);
const loading = ref(false);

onMounted(async () => {
  loading.value = true;
  try {
    const res = await apiClient.get('/tickets/my');
    tickets.value = (res as any).items ?? (res as any) ?? [];
  } finally { loading.value = false; }
});
</script>

<template>
  <div class="tickets-page">
    <h3>我的工单</h3>
    <div class="tabs">
      <button class="tab active">待处理</button>
      <button class="tab">已完成</button>
    </div>
    <div class="list" v-if="!loading">
      <TicketCard v-for="t in tickets" :key="t.id" :ticket="t" @click="router.push(`/tickets/${t.id}`)" />
      <p v-if="tickets.length === 0" class="empty">暂无工单</p>
    </div>
  </div>
</template>

<style scoped>
.tickets-page { padding: 16px; min-height: 100vh; background: #0d1117; }
.tickets-page h3 { margin: 0 0 12px; font-size: 18px; color: #fff; }
.tabs { display: flex; gap: 8px; margin-bottom: 14px; }
.tab { padding: 6px 14px; background: #161b22; border: 1px solid #30363d; border-radius: 20px; color: #aaa; font-size: 13px; cursor: pointer; }
.tab.active { background: #FF6B35; color: #fff; border-color: #FF6B35; }
.list { display: flex; flex-direction: column; gap: 8px; }
.empty { text-align: center; color: #888; padding: 40px 0; }
</style>
