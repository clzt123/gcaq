import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import axios from 'axios';
import type { User, UserRole, LoginResponse } from '../api/types';

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('token'));
  const user = ref<User | null>(
    JSON.parse(localStorage.getItem('user') ?? 'null'),
  );

  const isLoggedIn = computed(() => !!token.value);
  const role = computed<UserRole | null>(() => user.value?.role ?? null);

  async function login(username: string, password: string) {
    const res = await axios.post<LoginResponse>('/api/v1/auth/login', {
      username,
      password,
    });
    const data = (res as any).data ?? res;
    token.value = data.token;
    user.value = data.user;
    localStorage.setItem('token', data.token);
    localStorage.setItem('user', JSON.stringify(data.user));
  }

  function logout() {
    token.value = null;
    user.value = null;
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    window.location.href = '/login';
  }

  return { token, user, isLoggedIn, role, login, logout };
});
