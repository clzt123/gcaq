<script setup lang="ts">
import type { AnalyzeResponse, RiskLevel } from '@safeguard/shared';

const props = defineProps<{ result: AnalyzeResponse }>();

const riskLabel: Record<RiskLevel, string> = { L1: '紧急', L2: '严重', L3: '一般', L4: '低' };
</script>

<template>
  <div class="analysis-result">
    <div class="result-header" :class="result.risk_level.toLowerCase()">
      <span class="risk-badge">⚠️ {{ result.risk_level }} {{ riskLabel[result.risk_level] }}</span>
      <span class="confidence">置信度 {{ (result.confidence * 100).toFixed(0) }}%</span>
    </div>
    <div class="result-body">
      <div class="result-item">
        <span class="label">隐患类型</span>
        <span class="value">{{ result.hazard_type }}</span>
      </div>
      <div class="result-item" v-if="result.findings.length">
        <span class="label">发现问题</span>
        <ul class="findings">
          <li v-for="f in result.findings" :key="f">{{ f }}</li>
        </ul>
      </div>
      <div class="result-item" v-if="result.regulation_refs.length">
        <span class="label">相关法规</span>
        <ul class="refs">
          <li v-for="r in result.regulation_refs" :key="r">{{ r }}</li>
        </ul>
      </div>
      <div class="result-item" v-if="result.recommended_actions.length">
        <span class="label">建议措施</span>
        <ul class="actions">
          <li v-for="a in result.recommended_actions" :key="a">{{ a }}</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.analysis-result { background: #161b22; border-radius: 12px; overflow: hidden; margin-top: 12px; }
.result-header { padding: 14px 16px; display: flex; justify-content: space-between; align-items: center; }
.result-header.l1 { background: #3d1111; }
.result-header.l2 { background: #3d2a00; }
.result-header.l3 { background: #0d2a2a; }
.risk-badge { font-weight: 700; font-size: 16px; color: #fff; }
.confidence { font-size: 12px; color: #aaa; }
.result-body { padding: 16px; }
.result-item { margin-bottom: 12px; }
.result-item:last-child { margin-bottom: 0; }
.label { font-size: 12px; color: #888; display: block; margin-bottom: 4px; }
.value { font-size: 14px; color: #fff; }
.findings, .refs, .actions { margin: 4px 0 0; padding-left: 18px; font-size: 13px; color: #aaa; }
</style>
