<script setup lang="ts">
import { ref } from 'vue';
import { hazardApi } from '@safeguard/shared';
import type { AnalyzeResponse } from '@safeguard/shared';
import CameraCapture from '../components/CameraCapture.vue';
import AnalysisResult from '../components/AnalysisResult.vue';

const image = ref('');
const description = ref('');
const analyzing = ref(false);
const result = ref<AnalyzeResponse | null>(null);
const submitted = ref(false);
const errorMsg = ref('');
const isOnline = ref(navigator.onLine);

async function handleCapture(capturedImage: string) {
  image.value = capturedImage;
  analyzing.value = true;
  errorMsg.value = '';
  try {
    const res = await hazardApi.analyze({ image: capturedImage });
    result.value = res;
  } catch {
    errorMsg.value = '分析失败，请重试';
  } finally {
    analyzing.value = false;
  }
}

async function submitReport() {
  submitted.value = true;
}
</script>

<template>
  <div class="report-page">
    <h3>上报隐患</h3>
    <div class="step-section" v-if="!result">
      <p class="step-label">步骤 1：拍照</p>
      <CameraCapture @capture="handleCapture" />
      <div v-if="analyzing" class="analyzing-hint">
        <div class="spinner"></div>
        <p>AI 正在分析中...</p>
      </div>
      <p v-if="errorMsg" class="error">{{ errorMsg }}</p>
    </div>
    <div class="step-section" v-if="result">
      <p class="step-label">步骤 2：AI 分析结果</p>
      <AnalysisResult :result="result" />
      <div class="desc-input">
        <label>补充描述（选填）</label>
        <textarea v-model="description" placeholder="描述现场情况..." rows="3"></textarea>
      </div>
      <button class="submit-btn" @click="submitReport" :disabled="submitted">
        {{ isOnline ? (submitted ? '✅ 已提交' : '📤 确认提交') : '📦 暂存本地' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.report-page { padding: 16px; min-height: 100vh; background: #0d1117; }
.report-page h3 { margin: 0 0 16px; font-size: 18px; color: #fff; }
.step-section { margin-bottom: 16px; }
.step-label { font-size: 13px; color: #FF6B35; font-weight: 600; margin-bottom: 10px; }
.analyzing-hint { display: flex; flex-direction: column; align-items: center; padding: 24px; color: #888; }
.spinner { width: 32px; height: 32px; border: 3px solid #30363d; border-top-color: #FF6B35; border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }
.error { color: #FF4444; text-align: center; margin-top: 12px; font-size: 14px; }
.desc-input { margin: 16px 0; }
.desc-input label { display: block; font-size: 13px; color: #888; margin-bottom: 6px; }
.desc-input textarea { width: 100%; padding: 12px; background: #161b22; border: 1px solid #30363d; border-radius: 8px; color: #fff; font-size: 14px; resize: vertical; box-sizing: border-box; }
.desc-input textarea:focus { outline: none; border-color: #FF6B35; }
.submit-btn { width: 100%; padding: 14px; background: #4ECDC4; color: #000; border: none; border-radius: 10px; font-size: 16px; font-weight: 700; cursor: pointer; }
.submit-btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
