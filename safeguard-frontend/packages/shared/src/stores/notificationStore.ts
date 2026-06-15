import { defineStore } from 'pinia';
import { ref, computed } from 'vue';

export interface Notification {
  id: string;
  type: 'alert' | 'ticket' | 'system';
  title: string;
  message: string;
  read: boolean;
  created_at: string;
}

export const useNotificationStore = defineStore('notification', () => {
  const notifications = ref<Notification[]>([]);
  const unreadCount = computed(() =>
    notifications.value.filter((n) => !n.read).length,
  );

  function add(notification: Notification) {
    notifications.value.unshift(notification);
    if (notifications.value.length > 50) {
      notifications.value.pop();
    }
  }

  function markRead(id: string) {
    const n = notifications.value.find((n) => n.id === id);
    if (n) n.read = true;
  }

  function markAllRead() {
    notifications.value.forEach((n) => (n.read = true));
  }

  function clear() {
    notifications.value = [];
  }

  return { notifications, unreadCount, add, markRead, markAllRead, clear };
});
