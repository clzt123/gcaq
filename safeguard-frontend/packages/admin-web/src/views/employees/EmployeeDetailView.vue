<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import { apiClient } from '@safeguard/shared';

interface ViolationRecord { id: string; date: string; type: string; level: string; status: string; }
interface TrainingRecord { id: string; course: string; status: string; score?: number; date: string; }

const route = useRoute();
const employee = ref<any>(null);
const violations = ref<ViolationRecord[]>([]);
const trainings = ref<TrainingRecord[]>([]);
const activeTab = ref<'violations' | 'trainings' | 'equipment'>('violations');
const loading = ref(true);

onMounted(async () => {
  try {
    const id = route.params.id as string;
    const [emp, v, t] = await Promise.all([
      apiClient.get(`/employees/${id}`),
      apiClient.get(`/employees/${id}/violations`),
      apiClient.get(`/employees/${id}/trainings`),
    ]);
    employee.value = (emp as any).data ?? emp;
    violations.value = (v as any).items ?? (v as any) ?? [];
    trainings.value = (t as any).items ?? (t as any) ?? [];
  } catch { /* use defaults */ }
  finally { loading.value = false; }
});
</script>

<template>
  <div class="detail-page" v-loading="loading">
    <div class="profile-header" v-if="employee">
      <div class="avatar">{{ employee.name?.charAt(0) }}</div>
      <div class="info">
        <h2>{{ employee.name }}</h2>
        <p>{{ employee.department }} · {{ employee.role }}</p>
      </div>
      <div class="risk-indicator" :style="{ borderColor: (employee.risk_score ?? 0) >= 70 ? '#FF4444' : '#4ECDC4' }">
        <div class="risk-num">{{ employee.risk_score ?? 0 }}</div>
        <div class="risk-label">风险评分</div>
      </div>
    </div>

    <div class="tabs">
      <button :class="{ active: activeTab === 'violations' }" @click="activeTab = 'violations'">
        违规记录 ({{ violations.length }})
      </button>
      <button :class="{ active: activeTab === 'trainings' }" @click="activeTab = 'trainings'">
        培训记录 ({{ trainings.length }})
      </button>
      <button :class="{ active: activeTab === 'equipment' }" @click="activeTab = 'equipment'">
        领用设备
      </button>
    </div>

    <!-- Violations -->
    <div v-if="activeTab === 'violations'" class="list-section">
      <div v-for="v in violations" :key="v.id" class="record-card">
        <div class="record-left">
          <span class="level-tag" :class="v.level">{{ v.level }}</span>
        </div>
        <div class="record-center">
          <strong>{{ v.type }}</strong>
          <span class="record-date">{{ v.date }}</span>
        </div>
        <div class="record-right">
          <span class="status" :style="{ color: v.status === '已整改' ? '#4ECDC4' : '#FF4444' }">
            {{ v.status }}
          </span>
        </div>
      </div>
      <p v-if="violations.length === 0" class="empty">暂无违规记录 ✅</p>
    </div>

    <!-- Trainings -->
    <div v-if="activeTab === 'trainings'" class="list-section">
      <div v-for="t in trainings" :key="t.id" class="record-card">
        <div class="record-center">
          <strong>{{ t.course }}</strong>
          <span class="record-date">{{ t.date }}</span>
        </div>
        <div class="record-right">
          <span class="status" :style="{ color: t.status === 'completed' ? '#4ECDC4' : '#FFAA00' }">
            {{ t.status === 'completed' ? '已完成' : '进行中' }}
          </span>
          <span v-if="t.score" class="score">{{ t.score }}分</span>
        </div>
      </div>
      <p v-if="trainings.length === 0" class="empty">暂无培训记录</p>
    </div>

    <!-- Equipment -->
    <div v-if="activeTab === 'equipment'" class="list-section">
      <div class="equipment-card">
        <span>🦺</span>
        <div><strong>安全帽 #103</strong><p>领用日期：2026-03-01 · 状态：正常</p></div>
      </div>
      <div class="equipment-card">
        <span>🧤</span>
        <div><strong>防护手套 #A45</strong><p>领用日期：2026-04-15 · 状态：需更换</p></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.detail-page { max-width: 800px; }
.profile-header { display: flex; align-items: center; gap: 16px; padding: 24px; background: #161b22; border-radius: 10px; margin-bottom: 20px; }
.avatar { width: 56px; height: 56px; border-radius: 50%; background: #FF6B35; display: flex; align-items: center; justify-content: center; font-size: 24px; color: #fff; font-weight: 700; }
.info h2 { margin: 0; font-size: 20px; color: #fff; }
.info p { margin: 4px 0 0; font-size: 13px; color: #888; }
.risk-indicator { margin-left: auto; width: 70px; height: 70px; border-radius: 50%; border: 3px solid; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.risk-num { font-size: 20px; font-weight: 700; color: #fff; }
.risk-label { font-size: 10px; color: #888; }

.tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.tabs button { padding: 6px 14px; background: #161b22; border: 1px solid #30363d; border-radius: 6px; color: #8b949e; cursor: pointer; font-size: 13px; }
.tabs button.active { background: #FF6B35; color: #fff; border-color: #FF6B35; }

.list-section { display: flex; flex-direction: column; gap: 8px; }
.record-card { display: flex; align-items: center; gap: 12px; padding: 14px; background: #161b22; border-radius: 8px; }
.record-center { flex: 1; }
.record-center strong { display: block; font-size: 14px; color: #e6e6e6; }
.record-date { font-size: 11px; color: #888; }
.level-tag { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.level-tag.L1 { background: #3d1111; color: #FF4444; }
.level-tag.L2 { background: #3d2a00; color: #FFAA00; }
.status { font-size: 12px; }
.score { font-size: 12px; color: #888; margin-left: 8px; }
.equipment-card { display: flex; align-items: center; gap: 12px; padding: 14px; background: #161b22; border-radius: 8px; font-size: 22px; }
.equipment-card strong { display: block; font-size: 14px; color: #e6e6e6; }
.equipment-card p { margin: 2px 0 0; font-size: 12px; color: #888; }
.empty { text-align: center; color: #888; padding: 40px 0; }
</style>
