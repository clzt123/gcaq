import { createRouter, createWebHistory } from 'vue-router';

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('./views/LoginView.vue'),
    meta: { title: '登录' },
  },
  {
    path: '/',
    name: 'Home',
    component: () => import('./views/HomeView.vue'),
    meta: { title: '首页', roles: ['inspector'] },
  },
  {
    path: '/report',
    name: 'Report',
    component: () => import('./views/ReportView.vue'),
    meta: { title: '上报隐患', roles: ['inspector'] },
  },
  {
    path: '/tickets',
    name: 'Tickets',
    component: () => import('./views/TicketsView.vue'),
    meta: { title: '我的工单', roles: ['inspector'] },
  },
  {
    path: '/tickets/:id',
    name: 'TicketDetail',
    component: () => import('./views/TicketDetailView.vue'),
    meta: { title: '工单详情', roles: ['inspector'] },
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('token');
  const userStr = localStorage.getItem('user');
  const user = userStr ? JSON.parse(userStr) : null;

  if (to.path !== '/login' && !token) {
    return next('/login');
  }

  if (to.meta.roles && user) {
    if (!(to.meta.roles as string[]).includes(user.role)) {
      return next('/');
    }
  }

  next();
});

export default router;
