<script setup lang="ts">
import { ref, onMounted } from 'vue';
import type { User } from '@safeguard/shared';
import axios from 'axios';

const users = ref<User[]>([]);
const loading = ref(false);
const dialogVisible = ref(false);
const form = ref({ name: '', phone: '', role: 'inspector' as string, department: '', username: '', password: '' });

async function fetchUsers() {
  loading.value = true;
  try {
    const res = await axios.get('/api/v1/users');
    users.value = (res.data as any).items ?? (res.data as any) ?? [];
  } finally {
    loading.value = false;
  }
}

async function createUser() {
  await axios.post('/api/v1/users', form.value);
  dialogVisible.value = false;
  form.value = { name: '', phone: '', role: 'inspector', department: '', username: '', password: '' };
  await fetchUsers();
}

onMounted(fetchUsers);

const roleLabels: Record<string, string> = { inspector: '巡检员', manager: 'EHS主管', admin: '管理员' };
</script>

<template>
  <div class="user-manage">
    <div class="page-header">
      <h3>用户管理</h3>
      <button class="add-btn" @click="dialogVisible = true">+ 添加用户</button>
    </div>
    <div class="table-container" v-loading="loading">
      <table class="user-table">
        <thead>
          <tr>
            <th>姓名</th>
            <th>手机号</th>
            <th>角色</th>
            <th>部门</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.id">
            <td>{{ user.name }}</td>
            <td>{{ user.phone }}</td>
            <td><span class="role-tag" :class="user.role">{{ roleLabels[user.role] }}</span></td>
            <td>{{ user.department }}</td>
            <td><span class="action-link">编辑</span> <span class="action-link danger">禁用</span></td>
          </tr>
        </tbody>
      </table>
    </div>

    <el-dialog v-model="dialogVisible" title="添加用户" width="460px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="用户名"><el-input v-model="form.username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="form.password" type="password" /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="手机号"><el-input v-model="form.phone" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role">
            <el-option label="巡检员" value="inspector" />
            <el-option label="EHS主管" value="manager" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门"><el-input v-model="form.department" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="createUser">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h3 { margin: 0; font-size: 17px; }
.add-btn { padding: 8px 16px; background: #FF6B35; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; }
.table-container { background: #161b22; border-radius: 8px; overflow: hidden; }
.user-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.user-table th { padding: 10px 14px; text-align: left; color: #888; background: #1c2333; border-bottom: 1px solid #30363d; }
.user-table td { padding: 10px 14px; color: #c9d1d9; border-bottom: 1px solid #21262d; }
.user-table tbody tr:hover { background: #1c2333; }
.role-tag { padding: 2px 8px; border-radius: 4px; font-size: 11px; }
.role-tag.inspector { background: #1a3a2e; color: #4ECDC4; }
.role-tag.manager { background: #2a1a00; color: #FFAA00; }
.role-tag.admin { background: #1a2a3e; color: #58a6ff; }
.action-link { color: #58a6ff; cursor: pointer; margin-right: 12px; font-size: 12px; }
.action-link.danger { color: #FF4444; }
</style>
