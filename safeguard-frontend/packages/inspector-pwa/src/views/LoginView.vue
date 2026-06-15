<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { useAuth } from '@safeguard/shared';

const router = useRouter();
const { login } = useAuth();
const username = ref('');
const password = ref('');
const loading = ref(false);
const errorMsg = ref('');

async function handleLogin() {
  if (!username.value || !password.value) { errorMsg.value = '请输入用户名和密码'; return; }
  loading.value = true; errorMsg.value = '';
  try {
    await login(username.value, password.value);
    router.push('/');
  } catch { errorMsg.value = '用户名或密码错误'; }
  finally { loading.value = false; }
}
</script>

<template>
  <div class="login-page">
    <div class="login-header">
      <div class="logo-icon">🏭</div>
      <h1>安卫智脑</h1>
      <p>巡检助手</p>
    </div>
    <div class="login-form">
      <input v-model="username" type="text" placeholder="用户名" class="input" />
      <input v-model="password" type="password" placeholder="密码" class="input" />
      <p v-if="errorMsg" class="error">{{ errorMsg }}</p>
      <button class="btn" :disabled="loading" @click="handleLogin">
        {{ loading ? '登录中...' : '登 录' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.login-page { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; padding: 24px; background: #0d1117; }
.login-header { text-align: center; margin-bottom: 40px; }
.logo-icon { font-size: 48px; }
.login-header h1 { margin: 8px 0 4px; font-size: 22px; color: #fff; }
.login-header p { margin: 0; color: #888; font-size: 13px; }
.login-form { width: 100%; max-width: 320px; display: flex; flex-direction: column; gap: 16px; }
.input { padding: 12px; background: #161b22; border: 1px solid #30363d; border-radius: 8px; color: #fff; font-size: 15px; }
.input:focus { outline: none; border-color: #FF6B35; }
.error { color: #FF4444; font-size: 13px; margin: 0; text-align: center; }
.btn { padding: 14px; background: #FF6B35; color: #fff; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; }
.btn:disabled { opacity: 0.6; }
</style>
