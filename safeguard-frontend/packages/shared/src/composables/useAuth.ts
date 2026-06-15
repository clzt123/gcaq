import { computed } from 'vue';
import { useAuthStore } from '../stores/authStore';
import type { UserRole } from '../api/types';

export function useAuth() {
  const authStore = useAuthStore();

  const isLoggedIn = computed(() => authStore.isLoggedIn);
  const currentUser = computed(() => authStore.user);
  const currentRole = computed(() => authStore.role);

  function hasRole(...roles: UserRole[]): boolean {
    if (!authStore.role) return false;
    return roles.includes(authStore.role);
  }

  async function login(username: string, password: string) {
    return authStore.login(username, password);
  }

  function logout() {
    authStore.logout();
  }

  return { isLoggedIn, currentUser, currentRole, hasRole, login, logout };
}
