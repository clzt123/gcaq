import { computed } from 'vue';
import { useAuthStore } from '../stores/authStore';
import type { UserRole } from '../api/types';

type Permission = 'view_alerts' | 'manage_tickets' | 'manage_users' | 'manage_knowledge' | 'view_system';

const rolePermissions: Record<UserRole, Permission[]> = {
  inspector: ['view_alerts'],
  manager: ['view_alerts', 'manage_tickets', 'manage_knowledge'],
  admin: ['view_alerts', 'manage_tickets', 'manage_users', 'manage_knowledge', 'view_system'],
};

export function usePermission() {
  const authStore = useAuthStore();

  function can(permission: Permission): boolean {
    if (!authStore.role) return false;
    return rolePermissions[authStore.role]?.includes(permission) ?? false;
  }

  const canManageUsers = computed(() => can('manage_users'));
  const canManageTickets = computed(() => can('manage_tickets'));
  const canManageKnowledge = computed(() => can('manage_knowledge'));
  const canViewSystem = computed(() => can('view_system'));

  return { can, canManageUsers, canManageTickets, canManageKnowledge, canViewSystem };
}
