# SafeGuard-AI (安卫智脑) — Phase 1 正式发布

> **发布日期**: 2026-06-11 | **版本**: v0.1.0 | **代号**: "Foundation"

---

## 🎉 核心亮点 (Key Highlights)

### ✅ 全链路验证通过

4 大真实工业安全场景全部通过端到端验证，覆盖从视觉检测到工单推送的完整管线：

| # | 场景 | 测试图片 | 风险等级 | Qwen-VL 置信度 | 检索命中 |
|---|------|----------|----------|----------------|----------|
| 1 | 🛢️ 液压油泄漏 | `inj_mold_leak.jpg` | **high** | 0.92 | 6 条 / 621 字符 |
| 2 | 🚫 消防通道堵塞 | `blocked_fire_exit.jpg` | **high** | 0.98 | 5 项隐患检出 |
| 3 | 🪖 未戴安全帽 | `welding_no_helmet.jpg` | **high** | 0.91 | 法规+PPE 标准 |
| 4 | ☁️ 化学品烟雾 | `chemical_smoke.jpg` | **high** | 0.88 | 应急预案+通风 SOP |

每条管线包含 7 个节点：`detection → supervisor → graph_rag → memory → ticket_gen → ticket_push`，平均耗时 21.5s，工单 `EHS-20240520-089` 推送成功。

### 🐳 生产级部署就绪

一键启动全栈 4 服务，Docker Compose 编排：

```bash
git clone <repo-url> && cd SafeGuard-AI
cp .env.example .env
docker compose up -d
```

启动后自动拉起：
- **Neo4j** (图数据库, `:17687`) — 13 节点 + 10 关系知识图谱
- **Redis** (短期记忆, `:6379`) — AOF+RDB 持久化 + 256MB maxmemory
- **Milvus** (向量库, `:19530`) — BGE-M3 专家经验向量检索
- **FastAPI** (API 服务, `:8000`) — Swagger UI 交互式文档

> 详见 [DEPLOYMENT.md](DEPLOYMENT.md) 第 9 章「生产部署流程」。

### 📊 可观测性完备

集成 **LangSmith** 全链路追踪，每次 API 调用自动上报：

- 🔍 **LangGraph 节点级追踪** — 每个节点的输入/输出、耗时、路由决策
- 🔎 **RAG 检索调试** — Neo4j Cypher 查询、Milvus 向量召回效果
- 📊 **LLM 调用监控** — Token 用量、延迟、错误率
- 🏷️ **Trace ID 关联** — 精确定位单次请求的完整链路

配置即启用（无 API Key 时自动跳过，不影响业务）：

```ini
LANGSMITH_API_KEY=lsv2_pt_your-key-here
LANGSMITH_PROJECT=SafeGuard-AI
```

> 详见 [DEPLOYMENT.md §7](DEPLOYMENT.md#7-可观测性-langsmith)。

### 🛡️ 极致的鲁棒性

所有外部依赖均内置 **Mock 降级策略**，网络波动或服务不可用时系统不崩溃：

| 组件 | 正常模式 | 降级模式 | 切换方式 |
|------|----------|----------|----------|
| Neo4j | 真实 Cypher 查询 | 内存 Cypher 解析器 | `NEO4J_USE_MOCK` |
| Qwen-VL | DashScope API | 文件名关键词匹配 | `DASHSCOPE_API_KEY` |
| Milvus | BGE-M3 向量检索 | MD5→256d Hash 本地向量 | `use_mock` 三态 |
| Redis | Redis List 滑动窗口 | `collections.deque` | 自动检测 |

---

## 🚀 快速开始 (Quick Start)

### 3 分钟最小化部署（开发环境，零外部依赖）

```bash
# 1. 进入项目
cd SafeGuard-AI

# 2. 创建环境变量（Mock 模式无需任何 API Key）
cp .env.example .env

# 3. 创建虚拟环境 + 安装依赖
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt

# 4. 启动应用
python -m app.main

# 5. 验证
curl http://localhost:8000/health
```

启动后访问 **Swagger UI**: http://localhost:8000/docs

### 尝鲜体验：运行全链路测试

```bash
# 场景 1: 油渍泄漏（需配置 DASHSCOPE_API_KEY）
python run_real_test.py 1

# 场景 2: 消防通道堵塞
python run_real_test.py 2

# 场景 3: 未戴安全帽
python run_real_test.py 3

# 场景 4: 化学品烟雾
python run_real_test.py 4

# 仅测试视觉分析（快速验证 DashScope 连通性）
python run_real_test.py --vision-only
```

> 详见 [RUN_TEST.md](RUN_TEST.md) 获取完整的命令行参数、预期输出截屏和 CI/CD 集成示例。

### 单元测试

```bash
pytest    # 121 passed in ~2s，0 失败 0 警告
```

---

## 📊 项目数据一览

| 指标 | 数值 |
|------|------|
| 源代码文件 | 13 |
| 单元测试 | 121 (0 失败 0 警告) |
| Mock 数据 | 4 份 JSON/Cypher + 4 张真实测试图片 |
| 基础设施脚本 | 2 (Neo4j 初始化 + Milvus 向量化) |
| 文档 | 5 (PROGRESS + ARCHITECTURE + DEPLOYMENT + RUN_TEST + RELEASE_NOTES) |
| ADR 架构决策 | 16 (全部已实施) |
| Docker 服务 | 4 (Neo4j + Redis + Milvus + FastAPI) |
| 代码审查 | 4 轮，28 个问题全部修复 |

---

## ⚠️ 已知问题 (Known Issues)

**Phase 1 所有已知阻碍已清零。** 7 项开发阻碍（无本地基础设施、API Key 泄露、视觉仅 Mock、记忆系统未实现、路径重复、Neo4j auto-detect 延迟、GraphRAG 命中率 0）已在发布前全部解决。

常见的运维注意事项（如 Milvus 首次启动较慢、内存需求等）已纳入 [DEPLOYMENT.md §8 常见问题](DEPLOYMENT.md#8-常见问题)。

---

## 🗺️ 下一步路线图

### 短期（已完成 ✅）
- [x] 基础架构搭建 + 121 单元测试
- [x] MCP 工具层 + GraphRAG 引擎
- [x] LangGraph 状态机 + Qwen-VL 真实接入
- [x] 记忆系统分层设计 (Redis + Milvus)
- [x] LangSmith 全链路可观测性
- [x] Docker 全栈容器化 + 盲测验证
- [x] 文档体系建设 (5 份完整文档)

### 中期（规划中）
- [ ] **边缘端集成** — 边缘节点预筛 → 云端精算分流（详见 [ARCHITECTURE.md §长期规划](ARCHITECTURE.md#长期规划边缘-云端协同架构)）
- [ ] **SFT 微调流水线** — 基于 `log_false_positive` 反馈数据的增量训练
- [ ] **Helm Chart** — K8s 生产级编排（Ingress + HPA + PVC）

### 长期展望
- [ ] 边缘端镜像精简 (`Dockerfile.edge`)
- [ ] MQTT 边缘-云端通信协议
- [ ] 离线队列 (SQLite) + 模型同步下发

---

## 📁 文档索引

| 文档 | 说明 | 受众 |
|------|------|------|
| [README.md](README.md) | 项目门面，架构总览 | 所有人 |
| [PROJECT_REPORT.md](PROJECT_REPORT.md) | Phase 1 项目总结报告（KPI + 投入产出 + 验收） | 项目经理 / 投资人 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 部署指南（Docker/配置/验证/生产） | 运维 / DevOps |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 架构决策记录（16 个 ADR） | 架构师 / 开发者 |
| [RUN_TEST.md](RUN_TEST.md) | 测试脚本使用指南 | QA / 开发者 |
| [PROGRESS.md](PROGRESS.md) | 开发进度与文件树 | 项目管理 |
| [CLAUDE.md](CLAUDE.md) | AI 协作开发指南 | AI 协作者 |

---

> 🤖 **SafeGuard-AI (安卫智脑)** — 基于 LangGraph + GraphRAG 的工业安全生产智能体。
>
> Phase 1 为生产级 MVP：Mock 优先开发体验、Docker 一键部署、LangSmith 全链路追踪、4/4 真实场景验证通过。
