<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { apiClient } from '@safeguard/shared';

interface EmployeeProfile {
  id: string;
  name: string;
  department: string;
  role: string;
  violation_count: number;
  training_completion: number;
  risk_score: number;
  last_patrol: string;
}

const employees = ref<EmployeeProfile[]>([]);
const loading = ref(false);
const searchQuery = ref('');
const deptFilter = ref('all');
const router = useRouter();

async function fetchEmployees() {
  loading.value = true;
  try {
    const res = await apiClient.get('/employees');
    employees.value = (res as any).items ?? (res as any) ?? [];
  } catch { /* use defaults */ }
  finally { loading.value = false; }
}

function viewDetail(id: string) {
  router.push(`/employees/${id}`);
}

function riskColor(score: number): string {
  if (score >= 70) return '#FF4444';
  if (score >= 40) return '#FFAA00';
  return '#4ECDC4';
}

onMounted(fetchEmployees);
</script>

<template>
  <div class="employee-page">
    <div class="page-header">
      <h3>👤 员工安全档案</h3>
    </div>

    <!-- Filters -->
    <div class="filters">
      <input v-model="searchQuery" placeholder="🔍 搜索员工姓名..." class="search-input" />
      <select v-model="deptFilter" class="filter-select">
        <option value="all">全部部门</option>
        <option value="一车间">一车间</option>
        <option value="二车间">二车间</option>
        <option value="仓库">仓库</option>
        <option value="EHS管理部">EHS管理部</option>
      </select>
    </div>

    <!-- Stats -->
    <div class="stat-cards">
      <div class="stat-card">
        <div class="stat-num">{{ employees.length }}</div>
        <div class="stat-label">总人数</div>
      </div>
      <div class="stat-card warn">
        <div class="stat-num">{{ employees.filter(e => e.risk_score >= 70).length }}</div>
        <div class="stat-label">高风险人员</div>
      </div>
      <div class="stat-card good">
        <div class="stat-num">{{ Math.round(employees.reduce((s, e) => s + e.training_completion, 0) / (employees.length || 1)) }}%</div>
        <div class="stat-label">平均培训完成率</div>
      </div>
    </div>

    <!-- Table -->
    <div class="table-wrap" v-loading="loading">
      <table class="emp-table">
        <thead>
          <tr>
            <th>姓名</th>
            <th>部门</th>
            <th>角色</th>
            <th>违规次数</th>
            <th>培训完成率</th>
            <th>风险评分</th>
            <th>最近巡检</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="emp in employees" :key="emp.id">
            <td><strong>{{ emp.name }}</strong></td>
            <td>{{ emp.department }}</td>
            <td>{{ emp.role }}</td>
            <td>
              <span :style="{ color: emp.violation_count > 2 ? '#FF4444' : '#888' }">
                {{ emp.violation_count }}
              </span>
            </td>
            <td>
              <div class="mini-progress">
                <div class="mini-bar">
                  <div class="mini-fill" :style="{ width: emp.training_completion + '%' }"></div>
                </div>
                <span>{{ emp.training_completion }}%</span>
              </div>
            </td>
            <td>
              <span class="risk-badge" :style="{ background: riskColor(emp.risk_score) }">
                {{ emp.risk_score }}
              </span>
            </td>
            <td class="date-col">{{ emp.last_patrol || '无记录' }}</td>
            <td>
              <span class="detail-link" @click="viewDetail(emp.id)">详情 →</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.employee-page { min-height: 100%; }
.page-header { margin-bottom: 16px; }
.page-header h3 { margin: 0; font-size: 17px; color: #fff; }
.filters { display: flex; gap: 10px; margin-bottom: 16px; }
.search-input { flex: 1; padding: 8px 12px; background: #161b22; border: 1px solid #30363d; border-radius: 6px; color: #fff; font-size: 13px; }
.search-input:focus { outline: none; border-color: #FF6B35; }
.filter-select { padding: 8px 12px; background: #161b22; border: 1px solid #30363d; border-radius: 6px; color: #fff; font-size: 13px; }

.stat-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px; }
.stat-card { padding: 16px; background: #161b22; border-radius: 8px; text-align: center; }
.stat-card.warn { border-left: 3px solid #FF4444; }
.stat-card.good { border-left: 3px solid #4ECDC4; }
.stat-num { font-size: 24px; font-weight: 700; color: #fff; }
.stat-label { font-size: 12px; color: #888; margin-top: 4px; }

.table-wrap { background: #161b22; border-radius: 8px; overflow: hidden; }
.emp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.emp-table th { padding: 10px 12px; text-align: left; color: #888; background: #1c2333; border-bottom: 1px solid #30363d; }
.emp-table td { padding: 10px 12px; color: #c9d1d9; border-bottom: 1px solid #21262d; }
.emp-table tbody tr:hover { background: #1c2333; }
.mini-progress { display: flex; align-items: center; gap: 6px; }
.mini-bar { width: 60px; height: 5px; background: #21262d; border-radius: 3px; overflow: hidden; }
.mini-fill { height: 5px; background: #4ECDC4; border-radius: 3px; }
.risk-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; color: #fff; font-size: 12px; font-weight: 600; min-width: 20px; text-align: center; }
.date-col { color: #888; font-size: 12px; }
.detail-link { color: #58a6ff; cursor: pointer; }
</style>
