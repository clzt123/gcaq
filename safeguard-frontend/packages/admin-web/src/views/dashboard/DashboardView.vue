<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { hazardApi } from '@safeguard/shared';
import type { DashboardStats, TrendItem, HazardTypeDistribution } from '@safeguard/shared';
import BarChart from '../../components/charts/BarChart.vue';

const stats = ref<DashboardStats>({
  today_hazards: 0, yesterday_hazards: 0,
  pending_tickets: 0, overdue_tickets: 0,
  monthly_resolution_rate: 0, last_month_resolution_rate: 0,
  online_inspectors: 0, total_inspectors: 0,
});
const trends = ref<TrendItem[]>([]);
const distributions = ref<HazardTypeDistribution[]>([]);
const loading = ref(true);

onMounted(async () => {
  try {
    const [s, t, d] = await Promise.all([
      hazardApi.getDashboardStats(),
      hazardApi.getTrends(),
      hazardApi.getHazardDistribution(),
    ]);
    stats.value = s as DashboardStats;
    trends.value = t as TrendItem[];
    distributions.value = d as HazardTypeDistribution[];
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="dashboard" v-loading="loading">
    <!-- Stat Cards -->
    <div class="stat-cards">
      <div class="stat-card" style="border-top-color: #FF4444">
        <div class="stat-label">今日隐患</div>
        <div class="stat-value" style="color: #FF4444">{{ stats.today_hazards }}</div>
        <div class="stat-compare">
          较昨日 {{ stats.today_hazards >= stats.yesterday_hazards ? '↑' : '↓' }} {{ Math.abs(stats.today_hazards - stats.yesterday_hazards) }}
        </div>
      </div>
      <div class="stat-card" style="border-top-color: #FFAA00">
        <div class="stat-label">待处理工单</div>
        <div class="stat-value" style="color: #FFAA00">{{ stats.pending_tickets }}</div>
        <div class="stat-compare" v-if="stats.overdue_tickets > 0" style="color: #FF4444">
          {{ stats.overdue_tickets }} 个已逾期
        </div>
      </div>
      <div class="stat-card" style="border-top-color: #4ECDC4">
        <div class="stat-label">本月整改率</div>
        <div class="stat-value" style="color: #4ECDC4">{{ stats.monthly_resolution_rate }}%</div>
        <div class="stat-compare">
          较上月 {{ stats.monthly_resolution_rate >= stats.last_month_resolution_rate ? '↑' : '↓' }}
          {{ Math.abs(stats.monthly_resolution_rate - stats.last_month_resolution_rate) }}%
        </div>
      </div>
      <div class="stat-card" style="border-top-color: #45B7D1">
        <div class="stat-label">在线巡检员</div>
        <div class="stat-value" style="color: #45B7D1">{{ stats.online_inspectors }}</div>
        <div class="stat-compare">/ {{ stats.total_inspectors }} 在岗</div>
      </div>
    </div>

    <!-- Charts -->
    <div class="charts-row">
      <div class="chart-box chart-trend">
        <h3>近 7 天隐患趋势</h3>
        <BarChart
          :x-data="trends.map(t => t.date.slice(5))"
          :y-data="trends.map(t => t.count)"
          color="#FF6B35"
          height="240px"
        />
      </div>
      <div class="chart-box chart-distribution">
        <h3>隐患类型分布</h3>
        <div class="distribution-list">
          <div v-for="d in distributions" :key="d.hazard_type" class="distribution-item">
            <span class="dist-label">{{ d.hazard_type }}</span>
            <div class="dist-bar-bg">
              <div
                class="dist-bar-fill"
                :style="{
                  width: (d.count / Math.max(...distributions.map(x => x.count)) * 100) + '%',
                }"
              ></div>
            </div>
            <span class="dist-count">{{ d.count }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard { min-height: 100%; }
.stat-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 20px; }
.stat-card { padding: 20px; background: #161b22; border-radius: 8px; border-top: 3px solid; }
.stat-label { font-size: 13px; color: #888; margin-bottom: 8px; }
.stat-value { font-size: 32px; font-weight: 700; }
.stat-compare { font-size: 12px; color: #888; margin-top: 4px; }
.charts-row { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; }
.chart-box { padding: 20px; background: #161b22; border-radius: 8px; }
.chart-box h3 { margin: 0 0 16px; font-size: 14px; color: #aaa; }
.distribution-list { display: flex; flex-direction: column; gap: 10px; }
.distribution-item { display: flex; align-items: center; gap: 10px; font-size: 12px; }
.dist-label { width: 80px; color: #aaa; flex-shrink: 0; }
.dist-bar-bg { flex: 1; height: 6px; background: #21262d; border-radius: 3px; }
.dist-bar-fill { height: 6px; background: #FF6B35; border-radius: 3px; }
.dist-count { width: 24px; text-align: right; color: #FF6B35; font-weight: 600; }

@media (max-width: 1024px) {
  .stat-cards { grid-template-columns: repeat(2, 1fr); }
  .charts-row { grid-template-columns: 1fr; }
}
</style>
