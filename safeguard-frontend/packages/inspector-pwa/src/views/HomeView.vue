<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuth, hazardApi } from '@safeguard/shared';
import type { DashboardStats } from '@safeguard/shared';

const router = useRouter();
const { currentUser } = useAuth();
const stats = ref<DashboardStats | null>(null);

onMounted(async () => {
  try { stats.value = await hazardApi.getDashboardStats() as DashboardStats; } catch { /* use defaults */ }
});
</script>

<template>
  <div class="home-page">
    <div class="home-header">
      <div><h2>👋 {{ currentUser?.name || '巡检员' }}</h2><p class="sub">今日巡检 · 安全第一</p></div>
    </div>
    <div class="quick-actions">
      <div class="action-card primary" @click="router.push('/report')">
        <div class="action-icon">📸</div>
        <div class="action-text">拍照上报</div>
      </div>
      <div class="action-card" @click="router.push('/tickets')">
        <div class="action-icon">📋</div>
        <div class="action-text">我的工单</div>
      </div>
    </div>
    <div class="stat-mini" v-if="stats">
      <div class="mini-item"><span class="mini-num">{{ stats.today_hazards }}</span><span class="mini-label">今日隐患</span></div>
      <div class="mini-item"><span class="mini-num">{{ stats.pending_tickets }}</span><span class="mini-label">待处理</span></div>
      <div class="mini-item"><span class="mini-num">{{ stats.monthly_resolution_rate }}%</span><span class="mini-label">整改率</span></div>
    </div>
  </div>
</template>

<style scoped>
.home-page { padding: 16px; min-height: 100vh; background: #0d1117; }
.home-header { margin-bottom: 24px; }
.home-header h2 { margin: 0; font-size: 20px; color: #fff; }
.sub { margin: 4px 0 0; font-size: 13px; color: #888; }
.quick-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 24px; }
.action-card { padding: 24px 16px; background: #161b22; border-radius: 12px; text-align: center; cursor: pointer; border: 1px solid #30363d; }
.action-card.primary { background: linear-gradient(135deg, #FF6B35 0%, #FF5722 100%); border-color: transparent; }
.action-icon { font-size: 32px; margin-bottom: 8px; }
.action-text { font-size: 14px; font-weight: 600; color: #fff; }
.stat-mini { display: flex; gap: 12px; }
.mini-item { flex: 1; padding: 16px; background: #161b22; border-radius: 10px; text-align: center; }
.mini-num { display: block; font-size: 22px; font-weight: 700; color: #FF6B35; }
.mini-label { display: block; font-size: 11px; color: #888; margin-top: 4px; }
</style>
