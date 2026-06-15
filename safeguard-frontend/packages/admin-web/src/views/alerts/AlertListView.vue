<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { hazardApi, RiskBadge, StatusTag } from '@safeguard/shared';
import type { AlertItem, AlertQuery, PaginatedResponse } from '@safeguard/shared';

const router = useRouter();
const alerts = ref<AlertItem[]>([]);
const total = ref(0);
const loading = ref(false);
const query = ref<AlertQuery>({ page: 1, page_size: 20 });

async function fetchAlerts() {
  loading.value = true;
  try {
    const res = await hazardApi.getAlerts(query.value) as PaginatedResponse<AlertItem>;
    alerts.value = res.items;
    total.value = res.total;
  } finally {
    loading.value = false;
  }
}

function goDetail(id: string) {
  router.push(`/alerts/${id}`);
}

onMounted(fetchAlerts);
</script>

<template>
  <div class="alert-list-page">
    <div class="filters">
      <input v-model="query.search" placeholder="搜索隐患类型、位置..." class="filter-input" @keyup.enter="fetchAlerts" />
      <select v-model="query.risk_level" class="filter-select" @change="fetchAlerts">
        <option value="">全部等级</option>
        <option value="L1">L1 紧急</option>
        <option value="L2">L2 严重</option>
        <option value="L3">L3 一般</option>
        <option value="L4">L4 低</option>
      </select>
      <select v-model="query.source" class="filter-select" @change="fetchAlerts">
        <option value="">全部来源</option>
        <option value="auto">自动检测</option>
        <option value="manual">人工上报</option>
      </select>
      <select v-model="query.status" class="filter-select" @change="fetchAlerts">
        <option value="">全部状态</option>
        <option value="pending">待处理</option>
        <option value="processing">处理中</option>
        <option value="resolved">已解决</option>
        <option value="closed">已关闭</option>
      </select>
    </div>

    <div class="table-container" v-loading="loading">
      <table class="alert-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>来源</th>
            <th>隐患类型</th>
            <th>位置</th>
            <th>风险等级</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="alert in alerts" :key="alert.id">
            <td class="time-col">{{ alert.created_at }}</td>
            <td>
              <span class="source-tag" :class="alert.source">
                {{ alert.source === 'auto' ? '自动' : '人工' }}
              </span>
            </td>
            <td>{{ alert.hazard_type }}</td>
            <td>{{ alert.location }}</td>
            <td><RiskBadge :level="alert.risk_level" /></td>
            <td><StatusTag :status="alert.status" /></td>
            <td><span class="detail-link" @click="goDetail(alert.id)">详情 →</span></td>
          </tr>
        </tbody>
      </table>
      <div class="pagination" v-if="total > query.page_size!">
        <button :disabled="query.page === 1" @click="query.page!--; fetchAlerts()">‹</button>
        <span>{{ query.page }} / {{ Math.ceil(total / query.page_size!) }}</span>
        <button :disabled="query.page! * query.page_size! >= total" @click="query.page!++; fetchAlerts()">›</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.alert-list-page { min-height: 100%; }
.filters { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
.filter-input { flex: 1; min-width: 200px; padding: 8px 12px; background: #161b22; border: 1px solid #30363d; border-radius: 6px; color: #fff; font-size: 13px; }
.filter-input:focus { border-color: #FF6B35; outline: none; }
.filter-select { padding: 8px 12px; background: #161b22; border: 1px solid #30363d; border-radius: 6px; color: #fff; font-size: 13px; }
.table-container { background: #161b22; border-radius: 8px; overflow: hidden; }
.alert-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.alert-table th { padding: 10px 12px; text-align: left; color: #888; background: #1c2333; font-weight: 500; border-bottom: 1px solid #30363d; }
.alert-table td { padding: 10px 12px; color: #c9d1d9; border-bottom: 1px solid #21262d; }
.alert-table tbody tr:hover { background: #1c2333; }
.source-tag { padding: 1px 6px; border-radius: 3px; font-size: 11px; }
.source-tag.auto { background: #1a3a2e; color: #4ECDC4; }
.source-tag.manual { background: #2a1a00; color: #FFAA00; }
.time-col { color: #888; font-size: 12px; white-space: nowrap; }
.detail-link { color: #58a6ff; cursor: pointer; }
.pagination { display: flex; justify-content: center; align-items: center; gap: 12px; padding: 12px; }
.pagination button { padding: 4px 10px; background: #21262d; border: 1px solid #30363d; border-radius: 4px; color: #fff; cursor: pointer; }
.pagination button:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
