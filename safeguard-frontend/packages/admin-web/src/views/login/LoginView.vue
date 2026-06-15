<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { useAuth } from '@safeguard/shared';

const router = useRouter();
const { login, currentRole } = useAuth();

const username = ref('');
const password = ref('');
const loading = ref(false);
const errorMsg = ref('');

async function handleLogin() {
  if (!username.value || !password.value) {
    errorMsg.value = '请输入用户名和密码';
    return;
  }
  loading.value = true;
  errorMsg.value = '';
  try {
    await login(username.value, password.value);
    const role = currentRole.value;
    if (role === 'inspector') {
      router.push('/tickets');
    } else {
      router.push('/dashboard');
    }
  } catch {
    errorMsg.value = '用户名或密码错误';
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <h1>安卫智脑</h1>
        <p>SafeGuard-AI · EHS 管理平台</p>
      </div>
      <form @submit.prevent="handleLogin" class="login-form">
        <div class="form-item">
          <label>用户名</label>
          <input v-model="username" type="text" placeholder="请输入用户名" />
        </div>
        <div class="form-item">
          <label>密码</label>
          <input v-model="password" type="password" placeholder="请输入密码" />
        </div>
        <p v-if="errorMsg" class="error-msg">{{ errorMsg }}</p>
        <button type="submit" class="login-btn" :disabled="loading">
          {{ loading ? '登录中...' : '登 录' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex; align-items: center; justify-content: center;
  min-height: 100vh; background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
}
.login-card {
  width: 380px; padding: 40px; background: #161b22;
  border: 1px solid #30363d; border-radius: 12px;
}
.login-header { text-align: center; margin-bottom: 32px; }
.login-header h1 { margin: 0; font-size: 24px; color: #fff; }
.login-header p { margin: 8px 0 0; font-size: 13px; color: #888; }
.login-form { display: flex; flex-direction: column; gap: 16px; }
.form-item label { display: block; margin-bottom: 6px; font-size: 13px; color: #aaa; }
.form-item input {
  width: 100%; padding: 10px 12px; background: #0d1117; border: 1px solid #30363d;
  border-radius: 6px; color: #fff; font-size: 14px; box-sizing: border-box;
}
.form-item input:focus { outline: none; border-color: #FF6B35; }
.error-msg { color: #FF4444; font-size: 13px; margin: 0; }
.login-btn {
  width: 100%; padding: 12px; background: #FF6B35; color: #fff;
  border: none; border-radius: 6px; font-size: 15px; font-weight: 600; cursor: pointer;
}
.login-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.login-btn:hover:not(:disabled) { background: #FF5722; }
</style>
