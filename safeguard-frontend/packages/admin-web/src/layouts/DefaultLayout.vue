<script setup lang="ts">
import { computed } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useAuth, useNotificationStore } from '@safeguard/shared';

const router = useRouter();
const route = useRoute();
const { currentUser, logout } = useAuth();
const notificationStore = useNotificationStore();

const menuItems = computed(() => {
  const items = [
    { path: '/dashboard', title: '仪表盘', roles: ['manager', 'admin'] },
    { path: '/alerts', title: '告警管理', roles: ['manager', 'admin'] },
    { path: '/tickets', title: '工单管理', roles: ['manager', 'admin'] },
    { path: '/system/users', title: '用户管理', roles: ['admin'] },
    { path: '/settings', title: '个人设置', roles: ['inspector', 'manager', 'admin'] },
  ];
  return items.filter((item) =>
    item.roles.includes(currentUser.value?.role ?? ''),
  );
});
</script>

<template>
  <div class="default-layout">
    <aside class="sidebar">
      <div class="logo">安卫智脑</div>
      <nav class="menu">
        <div
          v-for="item in menuItems"
          :key="item.path"
          class="menu-item"
          :class="{ active: route.path === item.path }"
          @click="router.push(item.path)"
        >
          {{ item.title }}
        </div>
      </nav>
      <div class="sidebar-footer">
        <span>{{ currentUser?.name }}</span>
        <button class="logout-btn" @click="logout">退出</button>
      </div>
    </aside>
    <main class="main-content">
      <header class="top-bar">
        <h2>{{ route.meta.title }}</h2>
        <div class="top-bar-right">
          <span v-if="notificationStore.unreadCount > 0" class="badge">
            {{ notificationStore.unreadCount }}
          </span>
        </div>
      </header>
      <div class="content-area">
        <router-view />
      </div>
    </main>
  </div>
</template>

<style scoped>
.default-layout { display: flex; min-height: 100vh; background: #0d1117; color: #c9d1d9; }
.sidebar { width: 220px; background: #161b22; border-right: 1px solid #30363d; display: flex; flex-direction: column; padding: 16px 0; }
.logo { padding: 0 16px 16px; font-size: 18px; font-weight: 700; color: #fff; border-bottom: 1px solid #30363d; margin-bottom: 8px; }
.menu { flex: 1; }
.menu-item { padding: 10px 16px; cursor: pointer; font-size: 14px; color: #8b949e; transition: all 0.15s; }
.menu-item:hover, .menu-item.active { color: #fff; background: #21262d; }
.sidebar-footer { padding: 12px 16px; border-top: 1px solid #30363d; font-size: 13px; display: flex; justify-content: space-between; align-items: center; }
.logout-btn { background: transparent; color: #FF6B35; border: 1px solid #FF6B35; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; }
.main-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.top-bar { padding: 14px 24px; background: #161b22; border-bottom: 1px solid #30363d; display: flex; justify-content: space-between; align-items: center; }
.top-bar h2 { margin: 0; font-size: 17px; }
.badge { background: #FF4444; color: #fff; padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.content-area { flex: 1; overflow-y: auto; padding: 20px 24px; }
</style>
