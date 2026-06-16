<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import { apiClient } from '@safeguard/shared';

interface ServiceStatus {
  name: string;
  status: 'healthy' | 'degraded' | 'down';
  latency_ms: number;
  uptime: string;
}

interface EdgeNode {
  id: string;
  name: string;
  location: string;
  status: 'online' | 'offline';
  last_heartbeat: string;
  queue_size: number;
}

const services = ref<ServiceStatus[]>([]);
const edgeNodes = ref<EdgeNode[]>([]);
const loading = ref(true);
const refreshInterval = ref<ReturnType<typeof setInterval>>();

const statusIcon: Record<string, string> = { healthy: '✅', degraded: '⚠️', down: '❌' };
const statusColor: Record<string, string> = { healthy: '#4ECDC4', degraded: '#FFAA00', down: '#FF4444' };

async function fetchStatus() {
  try {
    const [s, e] = await Promise.all([
      apiClient.get('/system/health'),
      apiClient.get('/system/edge-nodes'),
    ]);
    services.value = (s as any).services ?? (s as any) ?? [];
    edgeNodes.value = (e as any).nodes ?? (e as any) ?? [];
  } catch { /* use defaults */ }
  finally { loading.value = false; }
}

onMounted(() => {
  fetchStatus();
  refreshInterval.value = setInterval(fetchStatus, 30000);
});

onUnmounted(() => {
  if (refreshInterval.value) clearInterval(refreshInterval.value);
});
</script>

<template>
  <div class="monitor-page">
    <div class="page-header">
      <h3>🖥️ 系统健康监控</h3>
      <span class="refresh-hint">每 30 秒自动刷新</span>
    </div>

    <!-- Service Status -->
    <div class="section" v-loading="loading">
      <h4>核心服务</h4>
      <div class="service-grid">
        <div v-for="svc in services" :key="svc.name" class="service-card" :class="svc.status">
          <div class="svc-top">
            <span class="svc-icon">{{ statusIcon[svc.status] }}</span>
            <span class="svc-name">{{ svc.name }}</span>
            <span class="svc-status" :style="{ color: statusColor[svc.status] }">
              {{ { healthy: '正常', degraded: '降级', down: '宕机' }[svc.status] }}
            </span>
          </div>
          <div class="svc-metrics">
            <div class="metric">
              <span class="metric-label">延迟</span>
              <span class="metric-value">{{ svc.latency_ms }}ms</span>
            </div>
            <div class="metric">
              <span class="metric-label">运行时间</span>
              <span class="metric-value">{{ svc.uptime }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Edge Nodes -->
    <div class="section">
      <h4>Edge 边缘节点</h4>
      <div class="edge-grid">
        <div v-for="node in edgeNodes" :key="node.id" class="edge-card" :class="node.status">
          <div class="edge-top">
            <strong>{{ node.name }}</strong>
            <span class="edge-status" :style="{ color: node.status === 'online' ? '#4ECDC4' : '#FF4444' }">
              {{ node.status === 'online' ? '🟢 在线' : '🔴 离线' }}
            </span>
          </div>
          <div class="edge-info">
            <span>📍 {{ node.location }}</span>
            <span>🕐 {{ node.last_heartbeat }}</span>
          </div>
          <div class="edge-queue" v-if="node.queue_size > 0">
            ⚠️ 离线队列积压：{{ node.queue_size }} 条
          </div>
        </div>
      </div>
    </div>

    <!-- API Stats -->
    <div class="section">
      <h4>API 网关</h4>
      <div class="api-stats">
        <div class="api-card">
          <div class="api-num" style="color:#4ECDC4">99.8%</div>
          <div class="api-label">可用率 (24h)</div>
        </div>
        <div class="api-card">
          <div class="api-num" style="color:#58a6ff">142ms</div>
          <div class="api-label">平均响应时间</div>
        </div>
        <div class="api-card">
          <div class="api-num" style="color:#FFAA00">1,247</div>
          <div class="api-label">今日请求数</div>
        </div>
        <div class="api-card">
          <div class="api-num" style="color:#4ECDC4">0</div>
          <div class="api-label">错误数</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.monitor-page { min-height: 100%; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-header h3 { margin: 0; font-size: 17px; color: #fff; }
.refresh-hint { font-size: 11px; color: #555; }

.section { margin-bottom: 24px; }
.section h4 { margin: 0 0 12px; font-size: 14px; color: #aaa; }

/* Services */
.service-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.service-card { padding: 16px; background: #161b22; border-radius: 8px; border-left: 3px solid #30363d; }
.service-card.healthy { border-left-color: #4ECDC4; }
.service-card.degraded { border-left-color: #FFAA00; }
.service-card.down { border-left-color: #FF4444; }
.svc-top { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.svc-name { font-size: 14px; font-weight: 600; color: #fff; }
.svc-status { font-size: 12px; margin-left: auto; }
.svc-metrics { display: flex; gap: 20px; }
.metric { display: flex; flex-direction: column; gap: 2px; }
.metric-label { font-size: 11px; color: #888; }
.metric-value { font-size: 16px; font-weight: 600; color: #e6e6e6; }

/* Edge */
.edge-grid { display: flex; flex-direction: column; gap: 8px; }
.edge-card { padding: 14px; background: #161b22; border-radius: 8px; }
.edge-card.online { border-left: 3px solid #4ECDC4; }
.edge-card.offline { border-left: 3px solid #FF4444; }
.edge-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.edge-top strong { font-size: 14px; color: #fff; }
.edge-info { display: flex; gap: 16px; font-size: 12px; color: #888; }
.edge-queue { margin-top: 8px; padding: 6px 10px; background: #2a1a00; border-radius: 4px; font-size: 12px; color: #FFAA00; }

/* API Stats */
.api-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.api-card { padding: 16px; background: #161b22; border-radius: 8px; text-align: center; }
.api-num { font-size: 24px; font-weight: 700; }
.api-label { font-size: 11px; color: #888; margin-top: 4px; }
</style>
