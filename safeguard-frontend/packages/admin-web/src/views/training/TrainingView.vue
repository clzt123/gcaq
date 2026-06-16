<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { apiClient } from '@safeguard/shared';

interface TrainingCourse {
  id: string;
  title: string;
  category: string;
  duration: string;
  required_for: string[];
  completed_count: number;
  total_count: number;
  priority: 'high' | 'medium' | 'low';
}

interface TrainingRecord {
  id: string;
  employee_name: string;
  course_title: string;
  status: 'completed' | 'in_progress' | 'overdue' | 'assigned';
  score?: number;
  assigned_date: string;
  completed_date?: string;
}

const courses = ref<TrainingCourse[]>([]);
const records = ref<TrainingRecord[]>([]);
const activeTab = ref<'courses' | 'records'>('courses');
const loading = ref(false);
const showAssign = ref(false);
const selectedCourse = ref<TrainingCourse | null>(null);

const priorityLabel: Record<string, string> = { high: '高', medium: '中', low: '低' };
const priorityColor: Record<string, string> = { high: '#FF4444', medium: '#FFAA00', low: '#4ECDC4' };
const statusLabel: Record<string, string> = {
  completed: '已完成', in_progress: '进行中', overdue: '已逾期', assigned: '已分配',
};
const statusColor: Record<string, string> = {
  completed: '#4ECDC4', in_progress: '#FFAA00', overdue: '#FF4444', assigned: '#888',
};

async function fetchData() {
  loading.value = true;
  try {
    const [c, r] = await Promise.all([
      apiClient.get('/training/courses'),
      apiClient.get('/training/records'),
    ]);
    courses.value = (c as any).items ?? (c as any) ?? [];
    records.value = (r as any).items ?? (r as any) ?? [];
  } catch { /* use defaults */ }
  finally { loading.value = false; }
}

function openAssign(course: TrainingCourse) {
  selectedCourse.value = course;
  showAssign.value = true;
}

onMounted(fetchData);
</script>

<template>
  <div class="training-page">
    <div class="page-header">
      <h3>🎓 培训管理</h3>
      <button class="add-btn">+ 创建课程</button>
    </div>

    <!-- Tabs -->
    <div class="tabs">
      <button :class="{ active: activeTab === 'courses' }" @click="activeTab = 'courses'">课程库</button>
      <button :class="{ active: activeTab === 'records' }" @click="activeTab = 'records'">培训记录</button>
    </div>

    <div v-loading="loading">
      <!-- Courses Tab -->
      <div v-if="activeTab === 'courses'" class="courses-grid">
        <div v-for="course in courses" :key="course.id" class="course-card">
          <div class="course-header">
            <h4>{{ course.title }}</h4>
            <span class="priority-badge" :style="{ color: priorityColor[course.priority] }">
              {{ priorityLabel[course.priority] }}优先级
            </span>
          </div>
          <div class="course-meta">
            <span>📂 {{ course.category }}</span>
            <span>⏱️ {{ course.duration }}</span>
          </div>
          <div class="course-progress">
            <div class="progress-bar">
              <div
                class="progress-fill"
                :style="{ width: (course.completed_count / course.total_count * 100) + '%' }"
              ></div>
            </div>
            <span class="progress-text">
              {{ course.completed_count }}/{{ course.total_count }} 人完成
            </span>
          </div>
          <div class="course-required" v-if="course.required_for.length">
            <span class="label">适用岗位：</span>
            <span v-for="r in course.required_for" :key="r" class="tag">{{ r }}</span>
          </div>
          <div class="course-actions">
            <button class="action-btn" @click="openAssign(course)">📋 分配</button>
            <button class="action-btn secondary">✏️ 编辑</button>
          </div>
        </div>
      </div>

      <!-- Records Tab -->
      <div v-if="activeTab === 'records'" class="records-table-wrap">
        <table class="records-table">
          <thead>
            <tr>
              <th>员工</th>
              <th>课程</th>
              <th>状态</th>
              <th>成绩</th>
              <th>分配时间</th>
              <th>完成时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in records" :key="r.id">
              <td>{{ r.employee_name }}</td>
              <td>{{ r.course_title }}</td>
              <td>
                <span class="status-tag" :style="{ color: statusColor[r.status] }">
                  {{ statusLabel[r.status] }}
                </span>
              </td>
              <td>{{ r.score ? r.score + '分' : '-' }}</td>
              <td class="date-col">{{ r.assigned_date }}</td>
              <td class="date-col">{{ r.completed_date || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Assign Dialog -->
    <el-dialog v-model="showAssign" :title="'分配课程：' + selectedCourse?.title" width="480px">
      <el-form label-width="80px">
        <el-form-item label="选择员工">
          <el-select multiple placeholder="请选择员工">
            <el-option label="王巡检 - 一车间" value="1" />
            <el-option label="赵工 - 二车间" value="2" />
            <el-option label="钱师傅 - 仓库" value="3" />
          </el-select>
        </el-form-item>
        <el-form-item label="截止日期">
          <el-date-picker type="date" placeholder="选择日期" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAssign = false">取消</el-button>
        <el-button type="primary" @click="showAssign = false">确认分配</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.training-page { min-height: 100%; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h3 { margin: 0; font-size: 17px; color: #fff; }
.add-btn { padding: 8px 16px; background: #FF6B35; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; }
.tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.tabs button { padding: 6px 16px; background: #161b22; border: 1px solid #30363d; border-radius: 6px; color: #8b949e; cursor: pointer; font-size: 13px; }
.tabs button.active { background: #FF6B35; color: #fff; border-color: #FF6B35; }

/* Courses */
.courses-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.course-card { padding: 20px; background: #161b22; border-radius: 8px; border: 1px solid #21262d; }
.course-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }
.course-header h4 { margin: 0; font-size: 15px; color: #fff; }
.priority-badge { font-size: 11px; font-weight: 600; flex-shrink: 0; }
.course-meta { display: flex; gap: 16px; font-size: 12px; color: #888; margin-bottom: 10px; }
.course-progress { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.progress-bar { flex: 1; height: 6px; background: #21262d; border-radius: 3px; overflow: hidden; }
.progress-fill { height: 6px; background: #FF6B35; border-radius: 3px; transition: width 0.3s; }
.progress-text { font-size: 11px; color: #888; white-space: nowrap; }
.course-required { margin-bottom: 12px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.course-required .label { font-size: 11px; color: #888; }
.tag { padding: 1px 6px; background: #21262d; border-radius: 3px; font-size: 11px; color: #8b949e; }
.course-actions { display: flex; gap: 8px; }
.action-btn { flex: 1; padding: 8px; background: #FF6B35; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 12px; text-align: center; }
.action-btn.secondary { background: #21262d; color: #8b949e; }

/* Records */
.records-table-wrap { background: #161b22; border-radius: 8px; overflow: hidden; }
.records-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.records-table th { padding: 10px 14px; text-align: left; color: #888; background: #1c2333; border-bottom: 1px solid #30363d; }
.records-table td { padding: 10px 14px; color: #c9d1d9; border-bottom: 1px solid #21262d; }
.records-table tbody tr:hover { background: #1c2333; }
.date-col { color: #888; font-size: 12px; }
</style>
