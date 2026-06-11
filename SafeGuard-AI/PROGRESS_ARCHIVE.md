# SafeGuard-AI (安卫智脑) 开发进度归档

> **归档日期**: 2026-06-11
> **归档范围**: Phase 1-8 全部已完成内容 | 121/121 测试通过 | 本项目 Phase 1-4 + Phase 2 边缘智能已锁定
> **当前活跃任务**: 请查看 [PROGRESS.md](PROGRESS.md)

---

## 📊 Phase 完成总览

| Phase | 名称 | 状态 | 源文件 | 测试 |
|-------|------|------|--------|------|
| 1 | 基础架构 | ✅ | 13 | `/health` 200 OK |
| 2 | MCP 工具层 | ✅ | 1 | 22/22 |
| 3 | GraphRAG 引擎 | ✅ | 2 | 45/45 |
| 4 | LangGraph 状态机 | ✅ | 3 | 37/37 |
| 5 | 端到端串联 | ✅ | 2 | 17/17 |
| 6 | LangSmith 可观测性 | ✅ | 4 | 121/121 |
| 7 | Docker 容器化 | ✅ | 3 | — |
| 8 | 🆕 Phase 2 边缘智能 MVP | ✅ | 4 | 121/121 (23.7s) |
| **文档** | README + RELEASE_NOTES + PROJECT_REPORT + DEPLOYMENT + ARCHITECTURE + RUN_TEST | ✅ | 6 | — |
| **脚本** | init_neo4j + embed_to_milvus + RELEASE_ARCHIVE | ✅ | 3 | — |
| **UI** | app_ui.py (Streamlit 可视化) | ✅ | 1 | — |
| **合计** | | | **59** | **121/121 (23.7s)** |

**Mock 数据**: `mock_data/` 含 4 份 JSON/Cypher 数据 + 4 张真实测试图片（inj_mold_leak / blocked_fire_exit / welding_no_helmet / chemical_smoke），覆盖 10 种隐患场景。

**代码审查**: 4 轮审查共发现 28 个问题，全部修复。最终 **121 个测试 0 失败 0 警告**。

**真实环境**: DashScope Qwen-VL-Max + Neo4j (13节点/10关系) + **Redis** (`:6379` ✅) + **Milvus** (`:19530` expert_memory ✅)。全链路 7 节点 21.5s 通过，GraphRAG 6条/621字符，Memory 2条/291字符（Milvus hash向量+IP检索），工单 EHS-20240520-089 推送成功。**LangSmith** 全链路追踪已启用，Trace 数据实时上报至 smith.langchain.com。

---

## 🔧 已完成功能详情

### Phase 1 — 基础架构
- **`app/config.py`**: pydantic-settings 配置管理，LLM / DashScope / Neo4j / Redis / Milvus / LangSmith 子配置类 + 聚合单例；`setup_langsmith()` 全局追踪初始化
- **`app/main.py`**: FastAPI 入口，彩色日志（参考 `Base/Config/logConfig.py`）、CORS、`/health`、lifespan；模块级 LangSmith 初始化（领先于 LangChain 导入）
- **`requirements.txt`**: LangGraph、FastAPI、Neo4j、Milvus、Redis、dashscope、langsmith 等依赖已锁定
- **`.env.example`**: 安全修复——暴露的 DeepSeek API Key 已替换为占位符；新增 DashScope + NEO4J_USE_MOCK + LangSmith 配置项
- **`docker-compose.neo4j.yml`**: Neo4j 本地一键部署（Bolt:7687 + HTTP:7474 + 数据持久化）
- **`docker-compose.redis.yml`**: Redis 7 Alpine（AOF+RDB 持久化 + 256MB maxmemory）
- **`docker-compose.milvus.yml`**: Milvus 2.5.4 Standalone（内嵌 etcd+minio）
- **`app/utils/__init__.py`**: `get_project_root()` + `get_mock_path()` 统一路径解析
- **`pyproject.toml`**: pytest `asyncio_mode = "auto"`

### Phase 2 — MCP 工具层
- **`app/tools/mcp_tools.py`**: 5 个 LangChain `@tool` 异步函数
  - `create_ehs_ticket` — 摘要压缩(>2000字符) + 幂等性预留
  - `verify_certificate` — 证书过期自动检测
  - `get_equipment_status` — 维保预警 + 大修阈值预警
  - `log_false_positive` — 反馈类型校验 + Negative Sample 标记
  - `edge_pre_screen` — 置信度三档分流
- 所有工具通过 `MCP_TOOLS` 列表注册，供 LangGraph `ToolNode` 调度
- Mock 数据懒加载+全局缓存；错误响应统一 `_make_error()` 入口

### Phase 3 — GraphRAG 引擎
- **`app/core/rag/neo4j_client.py`**: 异步 Neo4j 驱动 + Mock 内存图谱
  - 自动降级：真实 Neo4j 不可用时切换 Mock（解析 `init_graph.cypher`）
  - 12 种 Cypher 查询模式（正则匹配）+ `$param` 参数化（防注入）
  - 6 个高级查询方法 + 双向关键词搜索
- **`app/core/rag/retriever.py`**: 混合检索引擎
  - 4 步流水线：Neo4j 关键词 → 关联扩展 → Milvus 向量 → 合并置信度排序
  - `build_context()` 将结果拼接为 LLM Prompt 格式（含 📎 引用）
  - Neo4j 空结果时 Milvus 兜底；`asyncio.gather` 并行化关联查询

### Phase 4 — LangGraph 状态机
- **`app/core/graph/state.py`**: `HazardState` TypedDict 12 字段 + `operator.add` 归约器
- **`app/core/graph/nodes.py`**: 8→9 个异步节点函数
  - `detection_node` — Qwen-VL 真实调用 + 图片不可用时自动降级 Mock（10 类隐患）
  - `supervisor_node` — 四路路由 + `retry_count >= 3` 强制终止
  - `edge_handler_node` — 🆕 边缘即时处置
  - `graph_rag_node` → `memory_retrieval_node` → `ticket_generation_node` → `ticket_push_node`
- **`app/core/graph/workflow.py`**: StateGraph 编排 + 条件边 + 四路分流
- **`app/core/vision/analyzer.py`**: `analyze_image_with_qwen()` — DashScope Qwen-VL-Max 异步调用 + 图片格式自动检测 + Mock 关键词降级
- **`app/core/memory/manager.py`**: `MemoryManager` — 短期记忆: Redis List(主)/deque(降级)；长期专家经验: Milvus→BGE-M3(主)→hash本地(降级)/JSON 关键词匹配(兜底)

### Phase 5 — 端到端串联
- **`app/api/v1/hazard.py`**: Pydantic 强类型模型 + 3 个 API (POST /analyze + GET /alerts + GET /alerts/{id})
- **`tests/test_api.py`**: 17 个用例
- 全链路验证：`curl POST /analyze` → 200 OK

### 🆕 真实环境验证 (2026-06-11)
- **`run_real_test.py`**: 全链路真实环境测试脚本，5 种模式
- 4/4 场景全部通过：油渍泄漏 / 消防通道堵塞(5项隐患) / 未戴安全帽 / 化学品烟雾
- DashScope Qwen-VL-Max 真实调用（HTTP 200, ~3-5s 响应）, 置信度 0.88-0.98
- GraphRAG 命中率 0→6 条（Neo4j 2条→关联扩展 4条 + Milvus 2条）
- Bug 修复: 3 个生产级问题（见 ADR-11~13）

### 🆕 项目文档 (2026-06-11)
- **`DEPLOYMENT.md`**: 完整部署指南 — Docker/Python 版本要求 / `.env` 配置项详解 / 一键启动 / 全链路验证 / Swagger UI / LangSmith 可观测性 / 8 个 FAQ
- **`ARCHITECTURE.md`**: 17 个 ADR 全部标注"已实施" + 代码示例 + 可视化图表
- **`RUN_TEST.md`**: 测试脚本使用指南
- **`README.md`**: 项目门面 — ASCII 架构图 + 文档导航 + AI 能力详解
- **`RELEASE_NOTES.md`**: Phase 1 正式发布说明
- **`PROJECT_REPORT.md`**: Phase 1 项目总结报告 — KPI Dashboard + 验收确认 (10 项全部✅)
- **`RELEASE_ARCHIVE.py`**: 发布归档脚本

### 🆕 基础设施脚本与记忆系统升级 (2026-06-11)
- **`scripts/init_neo4j.py`**: Neo4j 图谱初始化（解析Cypher→执行→验证）
- **`scripts/embed_to_milvus.py`**: Milvus 专家经验向量化（BGE-M3→MilvusClient）
- **`app/config.py` 升级**: MilvusSettings/RedisSettings 新增字段，向后兼容
- **`app/core/memory/manager.py` 升级**: ADR-10 生产化落地（RedisShortTermBuffer + MilvusExpertStore + HashEmbedder）
- **`docker-compose.yml` 合并**: Neo4j+Redis+Milvus 三合一

### 🆕 LangSmith 可观测性集成 (2026-06-11)
- LangSmithSettings 配置类 + `setup_langsmith()` 全局初始化
- `main.py`/`run_real_test.py` 模块级调用，无 Key 时自动跳过
- 全链路验证：4 个 Trace 总计 3377 bytes 已上传

### 🆕 Docker 容器化 (2026-06-11)
- **`Dockerfile`**: 多阶段构建（builder→runtime），HEALTHCHECK
- **`.dockerignore`**: 12 类排除规则
- **`docker-compose.yml`** 升级: 新增 safeguard-api 服务，四服务一键启动
- **`DEPLOYMENT.md`** 升级: 新增第 9 章「生产部署流程」(13 个子章节)
- 盲测部署验证: 发现并修复 5 个知识诅咒缺口

### 🆕 Phase 2 — 边缘智能 MVP (2026-06-11)

**MCP 工具层升级：**
- `get_system_health()` — 边缘节点查询云端健康状态
- `edge_pre_screen` 通用化 — 置信度阈值参数化
- 能力分级 — EDGE_TOOLS / CLOUD_TOOLS 显式声明

**LangGraph 四路分流：**
- `edge_handler_node` — 边缘即时处置，失败时安全上升至云端
- `supervisor_node` 重构 — 三路→四路分流（max_confidence ≥ 0.90 → edge_handler）

**边缘镜像精简：**
- `Dockerfile.edge` — ~180MB (vs 云端 ~500MB+)，去除所有云依赖
- `requirements.edge.txt` — 12 包 (vs 云端 20 包)
- `docker-compose.edge.yml` — 边缘节点部署编排
- `app_edge.py` — 边缘 FastAPI 入口（4 个边缘 API，无云依赖导入链）
- `.env.edge` — 边缘节点环境变量模板

**MQTT 通信与离线队列：**
- `app/tools/mqtt_client.py` — 3 个 Topic 规范 + EdgeMQTTClient + Mock 文件模拟
- `app/tools/offline_queue.py` — SQLite 持久化 + 断网自动入队 + 恢复自动冲洗
- `app_edge.py` 集成 — MQTT 心跳/队列统计/手动冲洗/清理端点

**可视化界面：**
- `app_ui.py` — Streamlit Web 界面（图片上传→AI 分析→可视化报告）

---

## 🧱 架构决策记录 (ADR)

> 📎 **ADR 详细信息**: 查看 [ARCHITECTURE.md](ARCHITECTURE.md)

| ADR | 名称 | 日期 | 状态 | 分类 |
|-----|------|------|------|------|
| ADR-1 | State 类型选择 TypedDict 而非 Pydantic BaseModel | 2026-06 | ✅ | 数据契约 |
| ADR-2 | Mock 优先策略 + 配置化控制 | 2026-06 | ✅ | 开发策略 |
| ADR-3 | 不使用 LangGraph ToolNode | 2026-06 | ✅ | AI 编排 |
| ADR-4 | Handler 节点提取共享实现 | 2026-06 | ✅ | 代码质量 |
| ADR-5 | Cypher 注入防护 | 2026-06 | ✅ | 安全 |
| ADR-6 | 模块级常量替代魔法数字 | 2026-06 | ✅ | 代码规范 |
| ADR-7 | NEO4J_USE_MOCK 配置化替代 auto-detect | 2026-06 | ✅ | 开发体验 |
| ADR-8 | Qwen-VL 真实调用 + 图片不可用时 Mock 降级 | 2026-06 | ✅ | AI 视觉 |
| ADR-9 | 统一项目路径解析 | 2026-06 | ✅ | 工程化 |
| ADR-10 | 记忆系统分层设计 | 2026-06 | ✅ | 记忆系统 |
| ADR-11 | dashscope SDK `hasattr` 兼容性修复 | 2026-06-11 | ✅ | Bug 修复 |
| ADR-12 | 隐患类型英→中映射表 | 2026-06-11 | ✅ | 检索优化 |
| ADR-13 | Neo4j 关键词搜索分词 | 2026-06-11 | ✅ | 检索优化 |
| ADR-14 | LangSmith 全链路追踪集成 | 2026-06-11 | ✅ | 可观测性 |
| ADR-15 | FastAPI 多阶段 Docker 容器化 | 2026-06-11 | ✅ | 部署 |
| ADR-16 | DEPLOYMENT.md 盲测部署验证与知识诅咒消除 | 2026-06-11 | ✅ | 文档 |
| ADR-17 | 边缘端能力分级策略与 supervisor 四路分流 | 2026-06-11 | ✅ | Phase 2 架构 |

### 要点摘要
- **ADR-2/7/8**: Mock 优先策略贯穿全项目——Neo4j、Milvus、Qwen-VL、MCP Server 均内置 Mock，零外部依赖开发体验
- **ADR-10**: 记忆系统分层设计已生产化——短期: Redis List(主)/deque(降级)；长期: Milvus→BGE-M3(主)→hash本地(降级)/JSON(兜底)
- **ADR-12/13**: 检索命中率从 0 条提升至 6 条（621 字符），核心是英→中映射表 + 关键词分词搜索
- **ADR-14**: LangSmith 可观测性——`setup_langsmith()` 在 LangChain 导入前设置环境变量
- **ADR-15**: Docker 容器化——多阶段构建 + 全栈一键部署四服务
- **ADR-16**: 盲测部署验证——发现 5 个知识诅咒缺口并全部修复
- **ADR-17**: 边缘端能力分级——EDGE_TOOLS/CLOUD_TOOLS + 四路分流 + 边缘本地闭环 ~2s vs 云端 ~21s
- **ADR-5**: 5 处 Cypher f-string 全部改用 `$param` 参数化查询，防止注入攻击

---

## 🚧 已清零阻碍 (7/7)

| # | 阻碍 | 解决方案 |
|---|------|----------|
| 1 | ~~无本地 Neo4j/Milvus/Redis~~ | ✅ Docker Compose 已就绪 |
| 2 | ~~DeepSeek API Key 泄露~~ | ✅ 已轮换 |
| 3 | ~~视觉检测仅 Mock~~ | ✅ Qwen-VL API 接入 + 4/4 场景真实验证 |
| 4 | ~~记忆系统未实现~~ | ✅ MemoryManager 已接入 workflow |
| 5 | ~~mock 路径重复~~ | ✅ `app/utils.get_mock_path()` 统一 |
| 6 | ~~Neo4j auto-detect 延迟~~ | ✅ `NEO4J_USE_MOCK` 配置化 |
| 7 | ~~GraphRAG 命中率 0~~ | ✅ 英→中映射 + 分词搜索（6条/621字符） |

---

## 📋 已完成的下一步计划

### 短期（本周）— 全部完成 ✅
1. ✅ 轮换 DeepSeek API Key (2026-06-10)
2. ✅ 搭建本地基础设施 — Neo4j :17687 + Redis :6379 + Milvus :19530 (2026-06-10)
3. ✅ 接入 Qwen-VL API — DashScope Qwen-VL-Max 真实调用，4/4 场景验证 (2026-06-11)
4. ✅ API 层 Mock 模式配置化 (2026-06-10)
5. ✅ GraphRAG 检索命中率修复 — 0→6条 (2026-06-11)
6. ✅ 真实环境全链路验证 (2026-06-11)
7. ✅ 项目文档体系建设 — 6 份文档 (2026-06-11)

### 中期（本月）— 全部完成 ✅
8. ✅ Neo4j 数据导入 — `scripts/init_neo4j.py` (2026-06-11)
9. ✅ Milvus 向量化 — `scripts/embed_to_milvus.py` (2026-06-11)
10. ✅ 记忆系统升级 — MemoryManager 接入 Redis + Milvus (2026-06-11)
11. ✅ Neo4j/Milvus 实际导入 — `run_real_test.py --init-data` (2026-06-11)
12. ✅ 一体化 Docker Compose (2026-06-11)
13. ✅ Milvus Embedding 本地降级 — `_HashEmbedder` (2026-06-11)
14. ✅ 可观测性 — LangSmith 全链路追踪 (2026-06-11)
15. ✅ 发布归档与项目总结 (2026-06-11)
16. ✅ 部署到生产 — Docker Compose 全栈容器化 (2026-06-11)

---

## 🗺️ 后续路线图 — 全部完成 ✅

### Phase 2 — 边缘智能 (Edge Intelligence)
17. ✅ 边缘端分流 MVP — supervisor 四路分流 + edge_handler_node
18. ✅ MCP 工具能力分级 — EDGE_TOOLS/CLOUD_TOOLS + get_system_health()
19. ✅ 边缘镜像精简 — Dockerfile.edge(~180MB) + requirements.edge.txt(12包) + app_edge.py
20. ✅ MQTT 通信协议 — mqtt_client.py (3 Topic + EdgeMQTTClient + Mock)
21. ✅ 离线队列 — offline_queue.py (SQLite + 自动冲洗 + 重试)

### Phase 3 — 规模化 (Scale)
22. ✅ K8s 生产级编排 — Helm Chart 完整交付 (23 文件, 170+ 参数)

### Phase 4 — 持续学习 (Continuous Learning)
23. ✅ SFT 微调流水线 — `scripts/export_training_data.py`
24. ✅ A/B 评估框架 — `app/core/evaluation/ab_evaluator.py`
25. ✅ 反馈闭环 — `app/core/evaluation/feedback_loop.py`

---

## 📝 代码审查历史

| 审查 | Phase | 发现 | 修复 |
|------|-------|------|------|
| 第 1 轮 | Phase 2 (MCP 工具) | 7 个问题：Mock 缓存污染🔴、非确定性 hash、内联 import、缺失 args_schema、typo、错误 shape 不一致、魔法数字 | 全部修复 + `copy.deepcopy()` + `hashlib.sha256` + 统一 `_make_error()` |
| 第 2 轮 | Phase 3 (GraphRAG) | 7 个问题：Cypher 注入🔴、驱动泄漏🟡、死变量、未用导入、无缓存、查询模式重复、串行 I/O | 全部修复 + `$param` 参数化 + `_query_edges_by_source()` 提取 + `asyncio.gather` |
| 第 3 轮 | Phase 4 (状态机) | 7 个问题：`_load_mock_alerts` 死代码🔴、handler 95%重复🟡、内联 import🟡、未用 Optional、中文关键词不一致、硬编码 Mock、类型丢失 | 全部修复 + `_handle_hazard()` 提取 + 统一 `image_lower` + `use_mock=None` |
| 第 4 轮 | Phase 5 (API) | 7 个问题：`messages: list` 裸类型🟡、Optional 未用🟡、无缓存🟡、响应缺字段🟡、limit 无校验🟢、auto-detect 延迟🟢、TestClient 模块级🟢 | 全部修复 + `list[dict]` + `_MOCK_ALERTS_CACHE` + `AnalyzeResponse` 补 3 字段 + `Query(ge=1,le=100)` + TestClient fixture |

---

## 📁 项目文件树 (归档时快照)

```
SafeGuard-AI/
├── app/
│   ├── main.py                     # FastAPI 入口 + /health + router 注册 + LangSmith 初始化
│   ├── config.py                   # pydantic-settings 配置管理 (LLM/DashScope/Neo4j/Redis/Milvus/LangSmith)
│   ├── api/v1/hazard.py            # POST /analyze + GET /alerts
│   ├── core/
│   │   ├── graph/
│   │   │   ├── state.py            # HazardState TypedDict
│   │   │   ├── nodes.py            # 🆕 9 节点 + edge_handler(Phase2) + EDGE_CONFIDENCE_LOCAL_THRESHOLD
│   │   │   └── workflow.py         # 🆕 StateGraph 6节点 四路分流 (edge/urgent/normal/end)
│   │   ├── rag/
│   │   │   ├── neo4j_client.py     # Neo4j 异步客户端 + Mock 图谱 + _tokenize() 分词
│   │   │   └── retriever.py        # GraphRAG 混合检索 + 上下文构建
│   │   ├── memory/
│   │   │   ├── __init__.py         # 记忆系统模块入口
│   │   │   └── manager.py          # MemoryManager: Redis/Milvus主 + deque/JSON降级 + hash embed兜底
│   │   └── vision/
│   │       ├── __init__.py         # 视觉分析模块入口
│   │       └── analyzer.py         # analyze_image_with_qwen() + Mock 降级 + SDK 兼容修复
│   ├── utils/
│   │   └── __init__.py             # get_project_root() + get_mock_path()
│   └── tools/
│       ├── mcp_tools.py            # 🆕 6 个 @tool + EDGE_TOOLS/CLOUD_TOOLS 能力分级 + get_system_health()
│       ├── mqtt_client.py          # 🆕 Phase 2 MQTT 客户端 (3 Topic + EdgeMQTTClient + Mock)
│       └── offline_queue.py        # 🆕 Phase 2 离线队列 (SQLite + 自动冲洗 + 重试)
├── tests/
│   ├── test_mcp_tools.py           # 22 用例
│   ├── test_neo4j_client.py        # 21 用例
│   ├── test_retriever.py           # 24 用例
│   ├── test_workflow.py            # 37 用例
│   └── test_api.py                 # 17 用例
├── mock_data/
│   ├── images/                     # 🆕 4 张真实测试图片
│   │   ├── inj_mold_leak.jpg       #   油渍泄漏 (568KB)
│   │   ├── blocked_fire_exit.jpg   #   消防通道堵塞 (1.1MB)
│   │   ├── welding_no_helmet.jpg   #   未戴安全帽 (393KB)
│   │   └── chemical_smoke.jpg      #   化学品烟雾 (259KB)
│   ├── mock_alerts.json            # 4 条告警记录
│   ├── mock_mcp_responses.json     # 3 个 MCP 工具响应
│   ├── mock_memory.json            # 1 专家经验 + 1 反思记忆
│   └── init_graph.cypher           # Neo4j 初始化脚本
├── scripts/
│   ├── init_neo4j.py               # 🆕 Neo4j 图谱初始化（解析Cypher→执行→验证）
│   └── embed_to_milvus.py          # 🆕 Milvus 专家经验向量化（BGE-M3→MilvusClient）
├── docs/
│   └── 🏭 安卫智脑 (SafeGuard AI) 详细技术方案.md
├── run_real_test.py                # 🆕 全链路测试 + --init-data 一键数据导入 + LangSmith 追踪
├── app_ui.py                        # 🆕 Streamlit 可视化界面（图片上传→AI分析→可视化报告）
├── app_edge.py                      # 🆕 Phase 2 边缘节点入口（4 个边缘 API + 无云依赖）
├── README.md                        # 🆕 项目门面（ASCII架构图 + 文档导航 + AI能力 + 快速部署）
├── RELEASE_NOTES.md                 # 🆕 Phase 1 正式发布说明（亮点 + 已清零 + 路线图）
├── PROJECT_REPORT.md                # 🆕 Phase 1 总结报告（KPI + 验证 + 投入产出 + 验收）
├── RELEASE_ARCHIVE.py               # 🆕 发布归档脚本（白名单打包 + SHA256SUMS）
├── DEPLOYMENT.md                   # 🆕 部署指南（环境/Docker/配置/验证）
├── ARCHITECTURE.md                 # 🆕 架构决策记录（17个ADR已实施 + ADR-17 Phase2 边缘分级）
├── RUN_TEST.md                     # 🆕 测试脚本使用指南
├── CLAUDE.md                       # 开发指南
├── PROGRESS.md                     # 当前活跃任务
├── PROGRESS_ARCHIVE.md             # 本文件（归档）
├── requirements.txt
├── pyproject.toml
├── .env.example
├── Dockerfile                       # 🆕 多阶段构建（builder+runtime，python:3.11-slim）
├── Dockerfile.edge                  # 🆕 Phase 2 边缘精简镜像（~180MB，去除云依赖）
├── .dockerignore                    # 🆕 Docker 构建排除规则（12类）
├── docker-compose.yml              # 🆕 全栈四服务一键部署（Neo4j+Redis+Milvus+FastAPI）
├── docker-compose.edge.yml         # 🆕 Phase 2 边缘节点部署（Edge API + 可选 Redis）
├── docker-compose.neo4j.yml        # (保留) 独立 Neo4j 部署
├── docker-compose.redis.yml        # (保留) 独立 Redis 部署
├── docker-compose.milvus.yml       # (保留) 独立 Milvus 部署
├── requirements.edge.txt            # 🆕 Phase 2 边缘精简依赖（12 包）
├── .env.edge                        # 🆕 Phase 2 边缘节点环境变量模板
└── .claudeignore
```
