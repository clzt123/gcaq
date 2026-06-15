<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { hazardApi, RiskBadge, StatusTag } from '@safeguard/shared';
import type { AlertItem } from '@safeguard/shared';

const route = useRoute();
const router = useRouter();
const alert = ref<AlertItem | null>(null);
const loading = ref(true);

onMounted(async () => {
  try {
    const id = route.params.id as string;
    alert.value = await hazardApi.getAlert(id) as AlertItem;
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="alert-detail" v-loading="loading">
    <template v-if="alert">
      <div class="detail-header">
        <h2>{{ alert.hazard_type }}</h2>
        <div class="header-tags">
          <RiskBadge :level="alert.risk_level" />
          <StatusTag :status="alert.status" />
          <span class="source-tag" :class="alert.source">
            {{ alert.source === 'auto' ? '自动检测' : '人工上报' }}
          </span>
        </div>
      </div>
      <div class="detail-body">
        <div class="detail-section">
          <h4>基本信息</h4>
          <div class="info-grid">
            <div class="info-item"><span class="info-label">位置</span><span>{{ alert.location }}</span></div>
            <div class="info-item"><span class="info-label">上报时间</span><span>{{ alert.created_at }}</span></div>
            <div class="info-item"><span class="info-label">上报人</span><span>{{ alert.reported_by || '系统自动' }}</span></div>
          </div>
        </div>
        <div class="detail-section" v-if="alert.description">
          <h4>现场描述</h4>
          <p class="description">{{ alert.description }}</p>
        </div>
        <div class="detail-section" v-if="alert.image_url">
          <h4>现场图片</h4>
          <img :src="alert.image_url" class="detail-image" alt="隐患图片" />
        </div>
        <div class="detail-actions">
          <el-button type="primary" @click="router.push('/tickets')">创建工单</el-button>
          <el-button @click="router.back()">返回</el-button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.alert-detail { max-width: 800px; }
.detail-header { margin-bottom: 24px; }
.detail-header h2 { margin: 0 0 12px; font-size: 22px; }
.header-tags { display: flex; gap: 8px; align-items: center; }
.source-tag { padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.source-tag.auto { background: #1a3a2e; color: #4ECDC4; }
.source-tag.manual { background: #2a1a00; color: #FFAA00; }
.detail-section { margin-bottom: 20px; padding: 16px; background: #161b22; border-radius: 8px; }
.detail-section h4 { margin: 0 0 12px; font-size: 14px; color: #aaa; }
.info-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.info-item { display: flex; flex-direction: column; gap: 4px; }
.info-label { font-size: 12px; color: #888; }
.description { margin: 0; font-size: 14px; line-height: 1.6; color: #c9d1d9; }
.detail-image { max-width: 100%; border-radius: 8px; }
.detail-actions { display: flex; gap: 10px; margin-top: 20px; }
</style>
