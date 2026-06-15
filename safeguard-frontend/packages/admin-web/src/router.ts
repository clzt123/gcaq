import { createRouter, createWebHistory } from 'vue-router';
import type { RouteRecordRaw } from 'vue-router';
import type { UserRole } from '@safeguard/shared';

declare module 'vue-router' {
  interface RouteMeta {
    roles?: UserRole[];
    title: string;
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('./views/login/LoginView.vue'),
    meta: { title: '登录' },
  },
  {
    path: '/',
    component: () => import('./layouts/DefaultLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('./views/dashboard/DashboardView.vue'),
        meta: { title: '安全仪表盘', roles: ['manager', 'admin'] },
      },
      {
        path: 'alerts',
        name: 'Alerts',
        component: () => import('./views/alerts/AlertListView.vue'),
        meta: { title: '告警管理', roles: ['manager', 'admin'] },
      },
      {
        path: 'alerts/:id',
        name: 'AlertDetail',
        component: () => import('./views/alerts/AlertDetailView.vue'),
        meta: { title: '告警详情', roles: ['manager', 'admin'] },
      },
      {
        path: 'tickets',
        name: 'Tickets',
        component: () => import('./views/tickets/TicketListView.vue'),
        meta: { title: '工单管理', roles: ['manager', 'admin'] },
      },
      {
        path: 'system/users',
        name: 'UserManage',
        component: () => import('./views/system/UserManageView.vue'),
        meta: { title: '用户管理', roles: ['admin'] },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('./views/settings/SettingsView.vue'),
        meta: { title: '个人设置', roles: ['inspector', 'manager', 'admin'] },
      },
    ],
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

// Permission guard
router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('token');
  const userStr = localStorage.getItem('user');
  const user = userStr ? JSON.parse(userStr) : null;

  if (to.path !== '/login' && !token) {
    return next('/login');
  }

  if (to.meta.roles && user) {
    if (!to.meta.roles.includes(user.role)) {
      return next('/dashboard');
    }
  }

  next();
});

export default router;
