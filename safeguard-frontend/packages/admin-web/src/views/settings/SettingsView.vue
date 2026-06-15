<script setup lang="ts">
import { ref } from 'vue';
import { useAuth } from '@safeguard/shared';

const { currentUser } = useAuth();
const name = ref(currentUser.value?.name ?? '');
const phone = ref(currentUser.value?.phone ?? '');
const saved = ref(false);

function handleSave() {
  saved.value = true;
  setTimeout(() => (saved.value = false), 2000);
}
</script>

<template>
  <div class="settings-page">
    <h3>个人设置</h3>
    <div class="settings-card">
      <div class="form-item">
        <label>姓名</label>
        <input v-model="name" type="text" />
      </div>
      <div class="form-item">
        <label>手机号</label>
        <input v-model="phone" type="text" />
      </div>
      <button class="save-btn" @click="handleSave">
        {{ saved ? '✅ 已保存' : '保存修改' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.settings-page { max-width: 500px; }
.settings-page h3 { margin: 0 0 20px; font-size: 17px; }
.settings-card { padding: 24px; background: #161b22; border-radius: 8px; }
.form-item { margin-bottom: 16px; }
.form-item label { display: block; margin-bottom: 6px; font-size: 13px; color: #aaa; }
.form-item input {
  width: 100%; padding: 10px 12px; background: #0d1117; border: 1px solid #30363d;
  border-radius: 6px; color: #fff; font-size: 14px; box-sizing: border-box;
}
.form-item input:focus { outline: none; border-color: #FF6B35; }
.save-btn { padding: 10px 24px; background: #4ECDC4; color: #000; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; }
</style>
