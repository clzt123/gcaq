# SafeGuard-AI (安卫智脑)

> **Phase 1 ✅** | 121 Tests Passing | Docker Compose | LangSmith | GraphRAG + Qwen-VL

**基于 LangGraph 和 GraphRAG 的工业安全生产智能体** — 从视觉隐患检测到工单闭环处置的全链路 AI 工作流。

---

## 🏗️ 核心架构

```
                          📸 摄像头 / 图片输入
                                  │
                                  ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │                     🤖 LangGraph Agent (状态机)                    │
  │                                                                   │
  │   ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐   │
  │   │ 🔍 Detection  │───→│ 🧭 Supervisor │───→│ ⚙️ _handle_      │   │
  │   │  (视觉分析)    │    │  (三路路由)    │    │    hazard()     │   │
  │   │  Qwen-VL-Max  │    │              │    │                  │   │
  │   └──────────────┘    └──────┬───────┘    │  ┌─────────────┐ │   │
  │                              │            │  │ 📚 GraphRAG  │ │   │
  │                     urgent / normal       │  │ 🧠 Memory    │ │   │
  │                          / no_risk        │  │ 📝 TicketGen │ │   │
  │                                          │  │ 📤 Push      │ │   │
  │                                          │  └─────────────┘ │   │
  │                                          └────────┬─────────┘   │
  └───────────────────────────────────────────────────┬──────────────┘
                                                      │
          ┌───────────────────────────────────────────┼───────────────────────────────────────────┐
          │                                           ▼                                           │
          │                              📊 可观测性: LangSmith                                    │
          │                                           │                                           │
          ▼                                           ▼                                           ▼
  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────────┐
  │  ⚒️  Tools    │    │  📡 RAG       │    │  💾 Memory    │    │  🧠 LLM                      │
  │   (MCP 5 工具)│    │  (GraphRAG)   │    │  (分层记忆)    │    │                              │
  ├──────────────┤    ├──────────────┤    ├──────────────┤    ├──────────────────────────────┤
  │ create_ticket │    │ 🗄️  Neo4j    │    │ 📝 Redis     │    │ 💬 DeepSeek (推理/工单生成)    │
  │ verify_cert   │    │    知识图谱   │    │    短期记忆   │    │ 👁️  Qwen-VL-Max (视觉分析)    │
  │ get_equip     │    │    13节点    │    │    滑动窗口   │    │                              │
  │ log_false_pos │    │    10关系    │    │              │    │ 降级策略:                     │
  │ edge_pre_screen│   ├──────────────┤    ├──────────────┤    │ Mock → 本地关键词匹配          │
  └──────────────┘    │ 🔍 Milvus    │    │ 💾 Milvus    │    └──────────────────────────────┘
                      │    向量检索   │    │    专家经验   │
                      │    BGE-M3    │    │    Hash降级   │
                      └──────────────┘    └──────────────┘
          │                                           │
          ▼                                           ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │  🐳 部署: docker compose up -d                                    │
  │  Neo4j(:17687) + Redis(:6379) + Milvus(:19530) + FastAPI(:8000)  │
  └──────────────────────────────────────────────────────────────────┘
```

### 数据流说明

| 阶段 | 节点 | 输入 → 输出 | 关键技术 |
|------|------|-------------|----------|
| **感知** | `detection_node` | 图片 → 隐患列表 | DashScope Qwen-VL-Max |
| **决策** | `supervisor_node` | 隐患 → urgent/normal/no_risk | 置信度三档分流 |
| **检索** | `graph_rag_node` | 关键词 → 法规/SOP/案例 | Neo4j + Milvus 混合检索 |
| **注入** | `memory_retrieval_node` | 上下文 → 专家经验 | Redis 短期 + Milvus 长期 |
| **执行** | `ticket_generation_node` | 上下文 → 工单 | DeepSeek LLM 生成 |
| **闭环** | `ticket_push_node` | 工单 → EHS 系统 | MCP 协议推送 |

---

## 📚 文档体系

| 文档 | 说明 | 适合 |
|------|------|------|
| 📋 [RELEASE_NOTES.md](RELEASE_NOTES.md) | Phase 1 正式发布说明 | 所有人 |
| 📊 [PROJECT_REPORT.md](PROJECT_REPORT.md) | Phase 1 项目总结报告（KPI + 投入产出） | 项目经理 / 投资人 |
| 🚀 [DEPLOYMENT.md](DEPLOYMENT.md) | 部署指南（Docker/配置/验证/生产） | 运维 / DevOps |
| 🏛️ [ARCHITECTURE.md](ARCHITECTURE.md) | 架构决策记录（ADR-1 ~ ADR-16） | 架构师 / 开发者 |
| 🧪 [RUN_TEST.md](RUN_TEST.md) | 测试脚本使用指南 | QA / 开发者 |
| 📊 [PROGRESS.md](PROGRESS.md) | 开发进度与文件树 | 项目管理 |
| 🤖 [CLAUDE.md](CLAUDE.md) | AI 协作开发指南 | AI 协作者 |

---

## 🤖 AI 能力

### 👁️ 视觉隐患检测 (Vision)
- **模型**: 阿里云 DashScope Qwen-VL-Max
- **能力**: 检测 10 类工业安全隐患（油渍泄漏、消防通道堵塞、未戴安全帽、化学品烟雾、烟火、设备异常等）
- **降级**: API 不可用时自动切换文件名关键词匹配，**不阻断工作流**
- **格式**: 支持 URL / Base64 / 本地路径 三种图片输入

### 🔗 知识增强检索 (GraphRAG)
- **Neo4j 图谱**: 13 节点 + 10 关系，覆盖 Hazard / Equipment / Regulation / SOP 四类实体
- **混合检索**: Neo4j 结构化查询 (权重 0.5) + Milvus 向量相似度 (权重 0.5)
- **关联扩展**: 命中 1 个节点后自动沿边扩展关联实体（如隐患→法规→SOP）
- **中文优化**: 英→中隐患类型映射表 + 分词搜索，命中率从 0 提升至 6 条/621 字符

### 🧠 分层记忆系统 (Memory)
- **短期记忆**: Redis List 滑动窗口 (主) / `collections.deque` (降级)
- **长期专家经验**: Milvus BGE-M3 向量检索 (主) / MD5→256d Hash 本地向量 (降级) / JSON 关键词匹配 (兜底)
- **三层降级链**: 保证有网无网环境均可用

---

## 🛡️ 生产级特性

### 🐳 一键部署
```bash
docker compose up -d    # Neo4j + Redis + Milvus + FastAPI 四服务
```
- 多阶段 Dockerfile (builder + runtime)，最小化最终镜像
- 健康检查全覆盖 (30s 间隔 × 3 次重试)
- 命名卷数据持久化

### 🔄 优雅降级
所有外部依赖均内置 Mock 回退——网络波动、API 欠费、数据库宕机时**系统不崩溃**：
- Neo4j → 内存 Cypher 解析器
- Qwen-VL → 文件名关键词匹配
- Milvus → MD5 Hash 本地向量
- Redis → `collections.deque`

### 📊 全链路可观测性
LangSmith 集成 — LangGraph 节点级追踪、RAG 召回监控、LLM Token 统计，**配置即启用**。

### 🔒 安全设计
- Cypher 注入防护：全部 `$param` 参数化查询
- API Key 通过 pydantic-settings 管理，不入 Git
- `.env.example` 中所有密钥占位符化

### 🧪 测试覆盖
**121 个单元测试**，0 失败 0 警告：
- MCP 工具层: 22 用例
- Neo4j 客户端: 21 用例
- GraphRAG 检索: 24 用例
- LangGraph 状态机: 37 用例
- FastAPI 接口: 17 用例

---

## 🚀 快速部署

> 完整指南请参阅 [DEPLOYMENT.md](DEPLOYMENT.md)

### 开发环境（Mock 模式，零外部依赖）

```bash
cd SafeGuard-AI
cp .env.example .env
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python -m app.main
# 访问 http://localhost:8000/docs
```

### 生产环境（Docker Compose 全栈）

```bash
cd SafeGuard-AI
cp .env.example .env
# ⚠️ 编辑 .env：数据库地址改为 Docker 服务名（见 DEPLOYMENT.md §9.0）
docker compose up -d
# 访问 http://localhost:8000/docs
```

### 一键全链路验证

```bash
python run_real_test.py 1    # 油渍泄漏
python run_real_test.py 2    # 消防通道堵塞
python run_real_test.py 3    # 未戴安全帽
python run_real_test.py 4    # 化学品烟雾
```

---

## 📊 项目状态

| 指标 | 当前值 |
|------|--------|
| **版本** | v0.1.0 |
| **开发阶段** | **Phase 1 ✅ 全链路验证通过** |
| **代码审查** | 4 轮 / 28 问题 / 全部修复 |
| **真实场景验证** | 4/4 通过（DashScope Qwen-VL + Neo4j + Redis + Milvus） |
| **单元测试** | 121/121 passed (0 失败 0 警告) |
| **容器化** | Docker Compose 四服务一键部署 |
| **可观测性** | LangSmith 全链路追踪已启用 |
| **文档** | 6 份完整文档 |

---

## 🗺️ 路线图

- [x] **Phase 1 (Foundation)** ✅ — 基础架构 + MCP 工具 + GraphRAG + LangGraph + API + LangSmith + Docker + 文档
- [ ] **Phase 2 (Edge)** — 边缘端预筛 / 离线队列 / MQTT 通信 / 模型同步下发
- [ ] **Phase 3 (Scale)** — K8s Helm Chart / HPA 自动扩缩容 / Ingress + TLS
- [ ] **Phase 4 (Learn)** — SFT 微调流水线 / A/B 评估 / 反馈闭环

> 详见 [PROGRESS.md](PROGRESS.md) 和 [PROJECT_REPORT.md](PROJECT_REPORT.md)

---

## 📄 许可

本项目为 SafeGuard-AI (安卫智脑) Phase 1 生产级 MVP。

---

> 🏭 **SafeGuard-AI (安卫智脑)** — 让每一处隐患，都在酿成事故之前被看见、被研判、被处置。
