<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { apiClient } from '@safeguard/shared';

interface AuditLog {
  id: string;
  user: string;
  action: string;
  target: string;
  detail: string;
  ip: string;
  timestamp: string;
}

const logs = ref<AuditLog[]>([]);
const loading = ref(false);
const searchQuery = ref('');
const actionFilter = ref('all');

async function fetchLogs() {
  loading.value = true;
  try {
    const res = await apiClient.get('/system/audit-logs', { params: { limit: 100 } });
    logs.value = (res as any).items ?? (res as any) ?? [];
  } catch { /* use defaults */ }
  finally { loading.value = false; }
}

const actionColors: Record<string, string> = {
  '登录': '#4ECDC4', '创建': '#58a6ff', '编辑': '#FFAA00', '删除': '#FF4444', '审核': '#d2a8ff',
};

function actionColor(action: string): string {
  for (const [key, color] of Object.entries(actionColors)) {
    if (action.includes(key)) return color;
  }
  return '#888';
}

onMounted(fetchLogs);
</script>

<template>
  <div class="audit-page">
    <div class="page-header">
      <h3>📜 审计日志</h3>
      <span class="total-count">共 {{ logs.length }} 条记录</span>
    </div>

    <div class="filters">
      <input v-model="searchQuery" placeholder="🔍 搜索用户或操作..." class="search-input" />
      <select v-model="actionFilter" class="filter-select">
        <option value="all">全部操作</option>
        <option value="login">登录</option>
        <option value="create">创建</option>
        <option value="edit">编辑</option>
        <option value="delete">删除</option>
        <option value="audit">审核</option>
      </select>
      <button class="export-btn">📥 导出</button>
    </div>

    <div class="table-wrap" v-loading="loading">
      <table class="log-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>用户</th>
            <th>操作</th>
            <th>目标</th>
            <th>详情</th>
            <th>IP</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="log in logs" :key="log.id">
            <td class="time-col">{{ log.timestamp }}</td>
            <td>{{ log.user }}</td>
            <td>
              <span class="action-tag" :style="{ color: actionColor(log.action), borderColor: actionColor(log.action) }">
                {{ log.action }}
              </span>
            </td>
            <td>{{ log.target }}</td>
            <td class="detail-col">{{ log.detail }}</td>
            <td class="ip-col">{{ log.ip }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!loading && logs.length === 0" class="empty">暂无审计日志</p>
    </div>
  </div>
</template>

<style scoped>
.audit-page { min-height: 100%; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h3 { margin: 0; font-size: 17px; color: #fff; }
.total-count { font-size: 12px; color: #888; }

.filters { display: flex; gap: 10px; margin-bottom: 16px; }
.search-input { flex: 1; padding: 8px 12px; background: #161b22; border: 1px solid #30363d; border-radius: 6px; color: #fff; font-size: 13px; }
.search-input:focus { outline: none; border-color: #FF6B35; }
.filter-select { padding: 8px 12px; background: #161b22; border: 1px solid #30363d; border-radius: 6px; color: #fff; font-size: 13px; }
.export-btn { padding: 8px 16px; background: #21262d; color: #8b949e; border: 1px solid #30363d; border-radius: 6px; cursor: pointer; font-size: 13px; }

.table-wrap { background: #161b22; border-radius: 8px; overflow: hidden; }
.log-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.log-table th { padding: 10px 12px; text-align: left; color: #888; background: #1c2333; border-bottom: 1px solid #30363d; white-space: nowrap; }
.log-table td { padding: 10px 12px; color: #c9d1d9; border-bottom: 1px solid #21262d; }
.log-table tbody tr:hover { background: #1c2333; }
.time-col { color: #888; font-size: 12px; white-space: nowrap; }
.detail-col { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #888; font-size: 12px; }
.ip-col { color: #555; font-size: 11px; font-family: monospace; }
.action-tag { padding: 1px 8px; border-radius: 3px; border: 1px solid; font-size: 11px; font-weight: 500; }
.empty { text-align: center; color: #888; padding: 40px 0; }
</style>
