<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import { offlineQueue } from '../offline/queue';

const isOnline = ref(navigator.onLine);
const pendingCount = ref(0);

let interval: ReturnType<typeof setInterval>;

async function updateStatus() {
  isOnline.value = navigator.onLine;
  if (!isOnline.value) {
    pendingCount.value = await offlineQueue.pendingCount();
  }
}

onMounted(() => {
  updateStatus();
  window.addEventListener('online', updateStatus);
  window.addEventListener('offline', updateStatus);
  interval = setInterval(updateStatus, 5000);
});

onUnmounted(() => {
  window.removeEventListener('online', updateStatus);
  window.removeEventListener('offline', updateStatus);
  clearInterval(interval);
});
</script>

<template>
  <Transition name="slide">
    <div v-if="!isOnline" class="offline-banner">
      ⚠️ 当前离线 · {{ pendingCount }} 条待同步
    </div>
  </Transition>
</template>

<style scoped>
.offline-banner {
  position: sticky; top: 0; z-index: 100;
  padding: 8px 16px; background: #FFAA00; color: #000;
  text-align: center; font-size: 13px; font-weight: 600;
}
.slide-enter-active, .slide-leave-active { transition: all 0.3s ease; }
.slide-enter-from, .slide-leave-to { transform: translateY(-100%); opacity: 0; }
</style>
