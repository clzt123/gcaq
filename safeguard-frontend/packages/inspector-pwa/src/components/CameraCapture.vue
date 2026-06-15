<script setup lang="ts">
import { ref } from 'vue';

const emit = defineEmits<{ capture: [image: string] }>();
const previewUrl = ref<string>('');
const fileInput = ref<HTMLInputElement>();

function openCamera() {
  fileInput.value?.click();
}

function handleFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    previewUrl.value = reader.result as string;
    emit('capture', previewUrl.value);
  };
  reader.readAsDataURL(file);
}
</script>

<template>
  <div class="camera-capture">
    <input ref="fileInput" type="file" accept="image/*" capture="environment" hidden @change="handleFileChange" />
    <div class="capture-area" @click="openCamera">
      <template v-if="previewUrl">
        <img :src="previewUrl" alt="Preview" class="preview-img" />
      </template>
      <template v-else>
        <div class="capture-placeholder">
          <div class="placeholder-icon">📸</div>
          <p>点击拍照</p>
        </div>
      </template>
    </div>
    <div class="capture-actions">
      <button class="action-btn" @click="openCamera">📷 拍照</button>
      <button class="action-btn secondary" @click="openCamera">📁 相册</button>
    </div>
  </div>
</template>

<style scoped>
.camera-capture { width: 100%; }
.capture-area { width: 100%; aspect-ratio: 4/3; background: #161b22; border-radius: 12px; overflow: hidden; cursor: pointer; display: flex; align-items: center; justify-content: center; border: 2px dashed #30363d; }
.preview-img { width: 100%; height: 100%; object-fit: cover; }
.capture-placeholder { text-align: center; color: #888; }
.placeholder-icon { font-size: 48px; margin-bottom: 8px; }
.capture-actions { display: flex; gap: 12px; margin-top: 12px; }
.action-btn { flex: 1; padding: 12px; background: #FF6B35; color: #fff; border: none; border-radius: 8px; font-size: 14px; font-weight: 500; cursor: pointer; text-align: center; }
.action-btn.secondary { background: #21262d; }
</style>
