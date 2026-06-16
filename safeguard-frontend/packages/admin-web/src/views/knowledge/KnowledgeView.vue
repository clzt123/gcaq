<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { apiClient } from '@safeguard/shared';

interface KnowledgeDoc {
  id: string;
  title: string;
  category: 'sop' | 'regulation' | 'manual' | 'graph';
  content: string;
  tags: string[];
  updated_at: string;
  related_count: number;
}

const docs = ref<KnowledgeDoc[]>([]);
const searchQuery = ref('');
const activeCategory = ref<string>('all');
const selectedDoc = ref<KnowledgeDoc | null>(null);
const loading = ref(false);
const detailLoading = ref(false);

const categories = [
  { key: 'all', label: '全部' },
  { key: 'sop', label: 'SOP 操作规程' },
  { key: 'regulation', label: '安全法规' },
  { key: 'manual', label: '设备手册' },
  { key: 'graph', label: '知识图谱' },
];

const categoryLabel: Record<string, string> = {
  sop: 'SOP', regulation: '法规', manual: '手册', graph: '图谱',
};

const filteredDocs = computed(() => {
  let list = docs.value;
  if (activeCategory.value !== 'all') {
    list = list.filter((d) => d.category === activeCategory.value);
  }
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase();
    list = list.filter(
      (d) =>
        d.title.toLowerCase().includes(q) ||
        d.tags.some((t) => t.toLowerCase().includes(q)) ||
        d.content.toLowerCase().includes(q),
    );
  }
  return list;
});

async function fetchDocs() {
  loading.value = true;
  try {
    const res = await apiClient.get<{ items: KnowledgeDoc[] }>('/knowledge/search', {
      params: { q: '', limit: 50 },
    });
    const data = res as any;
    docs.value = (data as { items: KnowledgeDoc[] }).items ?? (data as KnowledgeDoc[]) ?? [];
  } catch {
    docs.value = [];
  } finally {
    loading.value = false;
  }
}

async function viewDoc(doc: KnowledgeDoc) {
  selectedDoc.value = doc;
  detailLoading.value = true;
  try {
    const res = await apiClient.get<KnowledgeDoc>(`/knowledge/docs/${doc.id}`);
    const data = res as any;
    if (data && data.content) {
      selectedDoc.value = data as KnowledgeDoc;
    }
  } catch {
    // use the list item data as fallback
  } finally {
    detailLoading.value = false;
  }
}

function closeDetail() {
  selectedDoc.value = null;
}

function truncate(text: string, len: number): string {
  if (!text) return '';
  return text.length > len ? text.slice(0, len) + '...' : text;
}

onMounted(fetchDocs);
</script>

<template>
  <div class="knowledge-page">
    <!-- Header -->
    <div class="page-header">
      <h3>📚 知识库管理</h3>
      <button class="upload-btn">
        + 上传文档
      </button>
    </div>

    <!-- Search + Categories -->
    <div class="toolbar">
      <input
        v-model="searchQuery"
        type="text"
        class="search-input"
        placeholder="🔍 搜索 SOP、法规、设备手册..."
      />
      <div class="category-tabs">
        <button
          v-for="cat in categories"
          :key="cat.key"
          class="cat-tab"
          :class="{ active: activeCategory === cat.key }"
          @click="activeCategory = cat.key"
        >
          {{ cat.label }}
        </button>
      </div>
    </div>

    <!-- Doc List + Detail Side-by-Side -->
    <div class="content-area" :class="{ 'has-detail': selectedDoc }">
      <!-- Left: Document List -->
      <div class="doc-list-panel" v-loading="loading">
        <div v-if="filteredDocs.length === 0" class="empty-state">
          <p>{{ searchQuery ? '未找到匹配文档' : '暂无知识库文档' }}</p>
          <span class="hint">点击"上传文档"添加第一条知识条目</span>
        </div>

        <div
          v-for="doc in filteredDocs"
          :key="doc.id"
          class="doc-card"
          :class="{ selected: selectedDoc?.id === doc.id }"
          @click="viewDoc(doc)"
        >
          <div class="doc-top">
            <span class="doc-category" :class="doc.category">
              {{ categoryLabel[doc.category] }}
            </span>
            <span class="doc-time">{{ doc.updated_at }}</span>
          </div>
          <h4 class="doc-title">{{ doc.title }}</h4>
          <p class="doc-preview">{{ truncate(doc.content, 80) }}</p>
          <div class="doc-tags">
            <span v-for="tag in doc.tags.slice(0, 3)" :key="tag" class="tag">{{ tag }}</span>
            <span v-if="doc.related_count > 0" class="related-info">
              🔗 {{ doc.related_count }} 个关联
            </span>
          </div>
        </div>
      </div>

      <!-- Right: Detail Panel -->
      <div v-if="selectedDoc" class="detail-panel" v-loading="detailLoading">
        <div class="detail-header">
          <h3>{{ selectedDoc.title }}</h3>
          <button class="close-btn" @click="closeDetail">✕</button>
        </div>
        <div class="detail-meta">
          <span class="doc-category" :class="selectedDoc.category">
            {{ categoryLabel[selectedDoc.category] }}
          </span>
          <span>{{ selectedDoc.updated_at }}</span>
          <span v-if="selectedDoc.related_count > 0">🔗 {{ selectedDoc.related_count }} 条关联</span>
        </div>

        <div class="detail-tags" v-if="selectedDoc.tags.length">
          <span class="label">标签：</span>
          <span v-for="tag in selectedDoc.tags" :key="tag" class="tag">{{ tag }}</span>
        </div>

        <div class="detail-content">
          <h4>📄 正文</h4>
          <div class="content-text">{{ selectedDoc.content }}</div>
        </div>

        <div class="detail-relations" v-if="selectedDoc.related_count > 0">
          <h4>🔗 知识图谱关联</h4>
          <div class="relation-cards">
            <div class="relation-card">
              <span class="rel-icon">📜</span>
              <div>
                <strong>关联法规：安全生产法第28条</strong>
                <p>生产经营单位应当对从业人员进行安全生产教育和培训...</p>
              </div>
            </div>
            <div class="relation-card">
              <span class="rel-icon">🔧</span>
              <div>
                <strong>关联设备：便携式气体检测仪</strong>
                <p>定期校准周期：6个月 | 上次校准：2026-05-10</p>
              </div>
            </div>
            <div class="relation-card">
              <span class="rel-icon">⚠️</span>
              <div>
                <strong>相关隐患：化学品泄漏</strong>
                <p>该操作规程对应的历史隐患 3 条，已全部整改</p>
              </div>
            </div>
          </div>
        </div>

        <div class="detail-actions">
          <el-button type="primary">✏️ 编辑</el-button>
          <el-button type="danger" plain>🗑️ 删除</el-button>
        </div>
      </div>

      <!-- No selection hint -->
      <div v-else class="detail-panel empty-detail">
        <div class="no-selection">
          <p>👈 从左侧列表选择文档查看详情</p>
          <span class="hint">包含正文内容 + 知识图谱关联</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.knowledge-page {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

/* Header */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-header h3 {
  margin: 0;
  font-size: 17px;
  color: #fff;
}
.upload-btn {
  padding: 8px 16px;
  background: #FF6B35;
  color: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}

/* Toolbar */
.toolbar {
  margin-bottom: 16px;
}
.search-input {
  width: 100%;
  padding: 10px 14px;
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  box-sizing: border-box;
  margin-bottom: 10px;
}
.search-input:focus {
  outline: none;
  border-color: #FF6B35;
}
.category-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.cat-tab {
  padding: 5px 14px;
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 20px;
  color: #8b949e;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.cat-tab:hover {
  color: #fff;
  border-color: #888;
}
.cat-tab.active {
  background: #FF6B35;
  color: #fff;
  border-color: #FF6B35;
}

/* Content Layout */
.content-area {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  min-height: 0;
}
.content-area:not(.has-detail) {
  grid-template-columns: 1fr;
}

/* Doc List */
.doc-list-panel {
  background: #161b22;
  border-radius: 8px;
  overflow-y: auto;
  padding: 4px;
  max-height: calc(100vh - 250px);
}
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #888;
}
.empty-state p {
  font-size: 15px;
  margin: 0 0 6px;
}
.hint {
  font-size: 12px;
  color: #555;
}

/* Doc Card */
.doc-card {
  padding: 14px 16px;
  margin: 4px;
  background: #0d1117;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.15s;
}
.doc-card:hover {
  border-color: #30363d;
  background: #161b22;
}
.doc-card.selected {
  border-color: #FF6B35;
  background: #1a1510;
}
.doc-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.doc-category {
  padding: 1px 8px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
}
.doc-category.sop {
  background: #1a3a2e;
  color: #4ECDC4;
}
.doc-category.regulation {
  background: #2a1a00;
  color: #FFAA00;
}
.doc-category.manual {
  background: #1a2a3e;
  color: #58a6ff;
}
.doc-category.graph {
  background: #2a0a2e;
  color: #d2a8ff;
}
.doc-time {
  font-size: 11px;
  color: #555;
}
.doc-title {
  margin: 0 0 4px;
  font-size: 14px;
  color: #e6e6e6;
}
.doc-preview {
  margin: 0 0 8px;
  font-size: 12px;
  color: #888;
  line-height: 1.4;
}
.doc-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}
.tag {
  padding: 1px 6px;
  background: #21262d;
  border-radius: 3px;
  font-size: 11px;
  color: #8b949e;
}
.related-info {
  font-size: 11px;
  color: #4ECDC4;
  margin-left: auto;
}

/* Detail Panel */
.detail-panel {
  background: #161b22;
  border-radius: 8px;
  padding: 20px;
  overflow-y: auto;
  max-height: calc(100vh - 250px);
}
.empty-detail {
  display: flex;
  align-items: center;
  justify-content: center;
}
.no-selection {
  text-align: center;
  color: #555;
}
.no-selection p {
  font-size: 15px;
  margin: 0 0 4px;
}
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}
.detail-header h3 {
  margin: 0;
  font-size: 18px;
  color: #fff;
  flex: 1;
}
.close-btn {
  background: transparent;
  border: 1px solid #30363d;
  color: #888;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.close-btn:hover {
  color: #fff;
  border-color: #FF4444;
}
.detail-meta {
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 12px;
  color: #888;
  margin-bottom: 12px;
}
.detail-tags {
  margin-bottom: 16px;
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.detail-tags .label {
  font-size: 12px;
  color: #888;
}
.detail-content {
  margin-bottom: 20px;
}
.detail-content h4 {
  margin: 0 0 10px;
  font-size: 14px;
  color: #aaa;
}
.content-text {
  font-size: 14px;
  line-height: 1.8;
  color: #c9d1d9;
  white-space: pre-wrap;
}
.detail-relations {
  margin-bottom: 20px;
}
.detail-relations h4 {
  margin: 0 0 10px;
  font-size: 14px;
  color: #aaa;
}
.relation-cards {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.relation-card {
  display: flex;
  gap: 10px;
  padding: 12px;
  background: #0d1117;
  border-radius: 8px;
  border: 1px solid #21262d;
}
.relation-card .rel-icon {
  font-size: 20px;
  flex-shrink: 0;
  margin-top: 2px;
}
.relation-card strong {
  display: block;
  font-size: 13px;
  color: #e6e6e6;
  margin-bottom: 2px;
}
.relation-card p {
  margin: 0;
  font-size: 12px;
  color: #888;
  line-height: 1.4;
}
.detail-actions {
  display: flex;
  gap: 10px;
}
</style>
