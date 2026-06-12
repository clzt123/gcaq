# SafeGuard-AI (安卫智脑) 架构决策记录

> 最后更新: 2026-06-11 | 版本: v0.1.0

---

## 概述

本文档记录了 SafeGuard-AI 项目在开发过程中做出的所有关键架构决策（Architecture Decision Records, ADR）。

每个 ADR 包含以下要素：

| 字段 | 说明 |
|------|------|
| **背景** | 触发此决策的问题或上下文 |
| **决策** | 最终选择的方案 |
| **理由** | 选择该方案的原因与权衡 |
| **代价** | 该决策带来的副作用或后续维护成本（如适用） |
| **效果** | 该决策带来的量化改进（如适用） |
| **涉及文件** | 受影响的源代码文件 |

---

## 📊 决策总览

| ADR | 名称 | 日期 | 状态 | 分类 |
|-----|------|------|------|------|
| ADR-1 | State 类型选择 TypedDict 而非 Pydantic BaseModel | 2026-06 | ✅ 已实施 | 数据契约 |
| ADR-2 | Mock 优先策略 + 配置化控制 | 2026-06 | ✅ 已实施 | 开发策略 |
| ADR-3 | 不使用 LangGraph ToolNode | 2026-06 | ✅ 已实施 | AI 编排 |
| ADR-4 | Handler 节点提取共享实现 | 2026-06 | ✅ 已实施 | 代码质量 |
| ADR-5 | Cypher 注入防护 | 2026-06 | ✅ 已实施 | 安全 |
| ADR-6 | 模块级常量替代魔法数字 | 2026-06 | ✅ 已实施 | 代码规范 |
| ADR-7 | NEO4J_USE_MOCK 配置化替代 auto-detect | 2026-06 | ✅ 已实施 | 开发体验 |
| ADR-8 | Qwen-VL 真实调用 + 图片不可用时 Mock 降级 | 2026-06 | ✅ 已实施 | AI 视觉 |
| ADR-9 | 统一项目路径解析 | 2026-06 | ✅ 已实施 | 工程化 |
| ADR-10 | 记忆系统分层设计 | 2026-06 | ✅ 已实施 | 记忆系统 |
| ADR-11 | dashscope SDK `hasattr` 兼容性修复 | 2026-06-11 | ✅ 已实施 | Bug 修复 |
| ADR-12 | 隐患类型英→中映射表 | 2026-06-11 | ✅ 已实施 | 检索优化 |
| ADR-13 | Neo4j 关键词搜索分词 | 2026-06-11 | ✅ 已实施 | 检索优化 |
| ADR-17 | 边缘端能力分级策略与 supervisor 四路分流 | 2026-06-11 | ✅ 已实施 | Phase 2 架构 |

> **统计**: 14 个 ADR 已记录（其中 13 个已实施 + 1 个 Phase 2 已实施）。覆盖架构设计、检索优化、安全、部署、可观测性、边缘智能 6 个领域。

---

## 项目上下文

在深入 ADR 之前，请先了解以下项目关键约束：

- **项目定位**: 工业安全智能体——隐患智能研判与闭环处置工作流
- **核心原则**: "参考架构，从零实现"（参考 `Base/` 分层逻辑和 `WorkFlow/` 状态机封装思路，但严格独立重写业务代码）
- **技术栈**: LangGraph ≥0.2.0, FastAPI + Uvicorn, Neo4j, Milvus, Redis, DashScope Qwen-VL
- **测试标准**: 121 个单元测试 0 失败 0 警告（pytest + pytest-asyncio）
- **文档参考**: [安卫智脑详细技术方案](docs/🏭%20安卫智脑%20(SafeGuard%20AI)%20详细技术方案.md)

---

## ADR-1: State 类型选择 TypedDict 而非 Pydantic BaseModel

- **背景**: WorkFlow 参考项目使用 Pydantic BaseModel 定义 State
- **决策**: 采用 `TypedDict` + `operator.add` 归约器
- **理由**: 与 LangGraph `add_messages` 机制兼容，无需处理 Pydantic 深拷贝陷阱，更轻量
- **涉及文件**: [app/core/graph/state.py](app/core/graph/state.py)

```python
# 核心类型结构
class HazardState(TypedDict):
    messages: Annotated[list, operator.add]   # add_messages 归约器
    alert_id: str
    image_url: str
    detection_result: dict
    next_action: str
    graph_context: str
    memory_context: str
    ticket_data: dict
    ticket_status: str
    need_cloud_analysis: bool
    area_type: str
    edge_node_id: str
    retry_count: int
```

---

## ADR-2: Mock 优先策略 + 配置化控制

- **决策**: 所有外部依赖（Neo4j、Milvus、Qwen-VL、MCP Server）均内置 Mock 模式；通过 `NEO4J_USE_MOCK` / `DASHSCOPE_API_KEY` 等环境变量显式控制
- **理由**: 开发阶段零外部依赖即可运行完整工作流；消除 auto-detect 的 1-3s 连接超时延迟
- **代价**: Mock 解析器（Cypher 正则、关键词匹配）需随查询模式扩展而维护
- **涉及文件**: [app/config.py](app/config.py), [app/core/rag/neo4j_client.py](app/core/rag/neo4j_client.py), [app/core/vision/analyzer.py](app/core/vision/analyzer.py)

### Mock 模式决策矩阵

```
                    是否配置       未配置时
组件              真实后端？      的行为
───────────────────────────────────────────
Neo4j     ←── NEO4J_USE_MOCK ──→ 内存 Cypher 解析
Qwen-VL   ←── DASHSCOPE_API_KEY → 文件名关键词匹配
Milvus    ←── 代码 use_mock=True → JSON 关键词重叠度
Redis     ←── 代码 deque 默认    → collections.deque
MCP       ←── 硬编码 mock 模式   → mock_mcp_responses.json
```

---

## ADR-3: 不使用 LangGraph ToolNode

- **背景**: CLAUDE.md 要求"通过 ToolNode 调度 MCP 工具"
- **决策**: `ticket_push_node` 内部直接 `create_ehs_ticket.ainvoke()`，未使用专用 `ToolNode`
- **理由**: 工具需在特定节点按需调用，非暴露给 LLM 自主选择；`ToolNode` 更适合 Agent 自主决策场景
- **涉及文件**: [app/core/graph/nodes.py](app/core/graph/nodes.py), [app/core/graph/workflow.py](app/core/graph/workflow.py)

---

## ADR-4: Handler 节点提取共享实现

- **背景**: `urgent_handler_node` 与 `normal_handler_node` 最初为独立函数（80 行×2）
- **决策**: 提取 `_handle_hazard(state, is_urgent: bool)` 共享实现
- **理由**: 代码审查发现 95% 重复，合并后 -35 行，维护点从 2 处减为 1 处
- **涉及文件**: [app/core/graph/nodes.py](app/core/graph/nodes.py)

```
Before:                           After:
┌──────────────────────┐          ┌──────────────────────┐
│ urgent_handler_node  │  80行    │ supervisor_node      │
│ (独立实现)           │          │   ├─ 路由到:          │
├──────────────────────┤          │   │    urgent   ──┐   │
│ normal_handler_node  │  80行    │   │    normal   ──┤   │
│ (拷贝粘贴 + 少量修改) │          │   │    no_risk  ──┘   │
└──────────────────────┘          │   └─ 共用:            │
                                  │      _handle_hazard  │  125行
                                  │      (is_urgent)     │
                                  └──────────────────────┘
                                  净节省: 35 行 (-22%)
```

---

## ADR-5: Cypher 注入防护

- **背景**: 审查发现 5 个方法使用 f-string 拼接用户输入到 Cypher
- **决策**: 全部改用 `$param` 占位符 + parameters dict；Mock 解析器支持 `$param` 字面值替换
- **理由**: 真实 Neo4j 模式下防止注入攻击（如 `name='test" RETURN n; DETACH DELETE n; //'`）
- **涉及文件**: [app/core/rag/neo4j_client.py](app/core/rag/neo4j_client.py)

```python
# ❌ 修复前（注入风险）
query = f"MATCH (n) WHERE n.name = '{user_input}' RETURN n"

# ✅ 修复后（参数化查询）
query = "MATCH (n) WHERE n.name = $name RETURN n"
await session.run(query, name=user_input)
```

---

## ADR-6: 模块级常量替代魔法数字

- **决策**: 提取以下模块级常量，集中管理所有阈值：

| 常量 | 值 | 用途 | 所在文件 |
|------|-----|------|----------|
| `MAX_DESCRIPTION_LENGTH` | 2000 | 工单描述最大字符数 | mcp_tools.py |
| `RUNTIME_OVERHAUL_THRESHOLD` | 1900 | 运行时长大修预警阈值(小时) | mcp_tools.py |
| `EDGE_CONFIDENCE_HIGH` | 0.95 | 边缘节点高置信度阈值 | mcp_tools.py |
| `EDGE_CONFIDENCE_LOW` | 0.6 | 边缘节点低置信度阈值 | mcp_tools.py |
| `DEFAULT_SHORT_TERM_WINDOW` | 5 | 短期记忆返回最近N轮 | manager.py |
| `MAX_CONVERSATION_TURNS` | 100 | 短期记忆最大保存轮数 | manager.py |
| `DEFAULT_EXPERT_TOP_K` | 3 | 专家经验默认返回数 | manager.py |
| `WEIGHT_NEO4J` | 0.5 | Neo4j 结构化匹配权重 | retriever.py |
| `WEIGHT_MILVUS` | 0.5 | Milvus 向量匹配权重 | retriever.py |

- **理由**: 集中管理阈值，后续调整无需跨文件搜索
- **涉及文件**: [app/tools/mcp_tools.py](app/tools/mcp_tools.py), [app/core/memory/manager.py](app/core/memory/manager.py), [app/core/rag/retriever.py](app/core/rag/retriever.py)

---

## ADR-7: NEO4J_USE_MOCK 配置化替代 auto-detect

- **背景**: `Neo4jClient(use_mock=None)` 在开发环境每次 API 调用先尝试真实 Neo4j 连接（~1-3s 超时），用户感知延迟明显
- **决策**: 新增 `Neo4jSettings.use_mock: bool = True`（环境变量 `NEO4J_USE_MOCK`），默认 Mock 模式零延迟；`use_mock` 参数显式传入时覆盖配置
- **理由**: 开发环境默认零延迟；生产环境显式设 `false` 即可切换真实 Neo4j
- **涉及文件**: [app/config.py](app/config.py) → `Neo4jSettings.use_mock`

```
修复前: 每次 API 调用 → try Neo4j(等待1-3s超时) → catch → Mock
修复后: 读取 NEO4J_USE_MOCK → 直接 Mock (0ms)
        或设置 NEO4J_USE_MOCK=false → 直连真实 Neo4j
```

---

## ADR-8: Qwen-VL 真实调用 + 图片不可用时 Mock 降级

- **背景**: `detection_node` 仅支持文件名关键词匹配，需接入 Qwen-VL 进行真实视觉隐患识别
- **决策**: 新增 `app/core/vision/analyzer.py`，使用 `dashscope.AioMultiModalConversation` 异步调用 Qwen-VL-Max；API Key 未配置或图片不可用时自动降级为 `_mock_analysis()` 关键词匹配
- **理由**: 零外部依赖开发体验不变（Mock 降级透明），配置 Key 后即时获得真实 AI 检测能力；图片格式自动检测（URL/Base64/本地路径）
- **涉及文件**: [app/core/vision/analyzer.py](app/core/vision/analyzer.py), [app/core/graph/nodes.py](app/core/graph/nodes.py) → `detection_node`

```
detection_node 路由逻辑:
┌─ DASHSCOPE_API_KEY 已配置? ──┤
│  YES → Qwen-VL-Max 真实调用
│     ├─ 成功 → 返回 10 类隐患分析结果
│     └─ 失败 → _mock_analysis() 降级
│  NO  → _mock_analysis() 降级（文件名关键词匹配）
│  图片不可用 → _mock_analysis() 降级（返回默认空结果）
```

---

## ADR-9: 统一项目路径解析

- **背景**: 4 个文件各自独立实现 `Path(__file__).resolve().parent.parent...` 定位项目根目录
- **决策**: 在 `app/utils/__init__.py` 中提取 `get_project_root()`（含全局缓存）和 `get_mock_path(filename)`，所有 mock 数据加载统一调用
- **理由**: 消除 3 处重复，路径计算逻辑集中维护；`get_project_root()` 按 CLAUDE.md/.env 标记定位，适配任意深度
- **涉及文件**: [app/utils/__init__.py](app/utils/__init__.py)

```python
# 统一的路径解析 API
from app.utils import get_project_root, get_mock_path

root = get_project_root()             # 返回项目根目录（全局缓存）
mock = get_mock_path("mock_alerts.json")  # 返回 mock_data/mock_alerts.json
```

---

## ADR-10: 记忆系统分层设计

- **背景**: `app/core/memory/manager.py` 为空壳，`memory_context` 未加入 HazardState，工作流未接入记忆
- **决策**: 分层设计——
  - **短期记忆**: `collections.deque(maxlen=100)` 滑动窗口（接口预留 Redis 替换路径）
  - **长期专家经验**: 关键词重叠度匹配 `mock_memory.json`（预留 Milvus 向量检索接口）
  - **工作流集成**: 新增 `memory_retrieval_node` 插入 `_handle_hazard` 流程（GraphRAG → Memory → TicketGen → Push）
- **理由**: 短期记忆提供对话连续性；长期专家经验为工单生成提供 few-shot 历史案例；接口预留真实后端替换路径
- **涉及文件**: [app/core/memory/manager.py](app/core/memory/manager.py), [app/core/memory/__init__.py](app/core/memory/__init__.py), [app/core/graph/nodes.py](app/core/graph/nodes.py)

### ADR-10 当前状态详析

**当前已实现（Mock 阶段）:**

| 组件 | 当前实现 | 接口预留 |
|------|----------|----------|
| 短期工作记忆 | `_ShortTermBuffer` — `collections.deque(maxlen=100)` | 方法签名与 Redis list 操作一致（`add`/`get_recent`/`clear`） |
| 长期专家经验 | `_ExpertMemoryStore(use_mock=True)` — 关键词重叠度匹配 `mock_memory.json` | `use_mock` 参数位预留；`retrieve()` docstring 标注 Milvus 真实模式 |
| 记忆上下文注入 | `build_memory_context()` — 将检索结果拼接为 LLM Prompt | 输出格式与 Milvus 检索结果兼容（`source`/`memory_id`/`text`/`score`） |
| 工作流位置 | `_handle_hazard()` 中 GraphRAG 之后、TicketGen 之前 | `memory_retrieval_node` 可作为独立节点提取 |

**中期升级路径（见 `PROGRESS.md` 下一步计划 #9）:**

```
当前 (Mock 阶段)                    目标 (生产阶段)
┌─────────────────────┐          ┌─────────────────────┐
│ _ShortTermBuffer    │ ───→    │ Redis list           │
│ (deque, 进程内存)   │  替换    │ (持久化 + 分布式)    │
├─────────────────────┤          ├─────────────────────┤
│ _ExpertMemoryStore  │ ───→    │ Milvus Client        │
│ (JSON 关键词匹配)   │  替换    │ (BGE-M3 向量检索)    │
└─────────────────────┘          └─────────────────────┘

升级触发条件:
  - Redis:  需求 #9 — "Redis 短期记忆（替换 deque）"
  - Milvus: 需求 #8 — "将 mock_memory.json 专家经验通过 BGE-M3 向量化后写入真实 Milvus"
```

> **关键设计原则**: 当前 Mock 实现与未来真实后端共享相同的接口签名，替换无需修改调用方（`MemoryManager` 公共 API 不变）。

---

## ADR-11: dashscope SDK `hasattr` 兼容性修复

- **日期**: 2026-06-11
- **背景**: `analyzer.py:314` 使用 `hasattr(output, "usage") and output.usage` 检测 token 用量，但 dashscope SDK 的 `__getattr__` 对不存在的 key 抛出 `KeyError` 而非 `AttributeError`，`hasattr()` 无法捕获 → 崩溃丢弃了已正确获取的 Qwen-VL 分析结果
- **决策**: 改用 `try: output.get("usage")` 安全访问，`KeyError/AttributeError/TypeError` 静默跳过
- **理由**: 用量统计为辅助功能，不应因 SDK 版本差异导致核心分析结果被丢弃
- **涉及文件**: [app/core/vision/analyzer.py](app/core/vision/analyzer.py)

```python
# ❌ 修复前
if hasattr(output, "usage") and output.usage:
    usage = output.usage  # KeyError 崩溃，丢弃分析结果

# ✅ 修复后
try:
    usage = output.get("usage")
except (KeyError, AttributeError, TypeError):
    usage = None  # 静默跳过，核心结果不受影响
```

---

## ADR-12: 隐患类型英→中映射表

- **日期**: 2026-06-11
- **背景**: Qwen-VL 返回英文 hazard type (`oil_leak`, `blocked_exit` 等)，但 Neo4j 图谱和 Mock 记忆均为中文（`"液压油泄漏"`, `"消防通道堵塞"`），导致检索命中率持续为 0
- **决策**: 在 `nodes.py` 新增 `HAZARD_TYPE_ZH_MAP` (10 个映射) + `_build_rag_query()` 函数，将英文 type 映射为中文关键词（如 `oil_leak` → `"油渍泄漏 化学品泄漏 液压油 切削液 密封圈 管路老化 防漏托盘"`），同时保留 Qwen-VL 的中文 description 字段
- **效果**:

| 指标 | 修复前 | 修复后 | 提升 |
|------|--------|--------|------|
| GraphRAG 总命中 | 0 条 | 6 条 | +∞ |
| Neo4j 命中 | 0 条 | 2 条 + 2 条关联扩展 | — |
| Milvus 命中 | 0 条 | 2 条 | — |
| 上下文长度 | 20 字符 | 621 字符 | 31× |
| 法规条款注入 | 无 | ✅ 含 GB 标准编号 | — |

- **涉及文件**: [app/core/graph/nodes.py](app/core/graph/nodes.py)

```python
HAZARD_TYPE_ZH_MAP = {
    "oil_leak":         "油渍泄漏 化学品泄漏 液压油 切削液 密封圈 管路老化 防漏托盘",
    "blocked_exit":     "消防通道堵塞 安全出口 疏散通道 杂物堆放 应急照明",
    "no_helmet":        "未戴安全帽 头部防护 PPE 劳保用品 焊接作业 安全培训",
    "chemical_smoke":   "化学品烟雾 有毒气体 通风系统 泄漏扩散 应急预案",
    # ... 共 10 个映射
}
```

---

## ADR-13: Neo4j 关键词搜索分词

- **日期**: 2026-06-11
- **背景**: `Neo4jClient.search_by_keyword()` 将整个查询字符串作为单一体用 `CONTAINS` 匹配，长查询（如 `"油渍泄漏 化学品泄漏 液压油..."`）无法匹配短节点名（如 `"液压油泄漏"`）
- **决策**: 新增 `_tokenize()` 方法，按空格/标点拆分长查询为独立关键词（2-10 字符），Mock 模式和真实 Neo4j 均改为逐词 OR 匹配（`CONTAINS $t0 OR CONTAINS $t1 OR ...`），同时按 `(label, name)` 去重
- **效果**: Neo4j 命中 0 条 → 2 条（"液压油泄漏" Hazard + "化学品泄漏与火灾应急处置SOP" SOP），关联扩展后翻倍至 4 条
- **涉及文件**: [app/core/rag/neo4j_client.py](app/core/rag/neo4j_client.py)

```
修复前: CONTAINS "油渍泄漏 化学品泄漏 液压油 切削液..."
        → 整个字符串匹配短节点名 → 0 命中

修复后: CONTAINS "油渍泄漏" OR CONTAINS "化学品泄漏"
        OR CONTAINS "液压油" OR CONTAINS "切削液" ...
        → 逐词匹配 → "液压油泄漏" 命中! (2-3 字重叠)
```

---

## ADR-17: 边缘端能力分级策略与 supervisor 四路分流

- **日期**: 2026-06-11
- **背景**: Phase 1 完成了全链路的云端闭环（detection → GraphRAG → memory → ticket → push），但所有计算均在云端完成。Phase 2 需要引入边缘-云端协同架构，将高置信度的明确违规场景在边缘端即时处置，降低延迟与云端算力消耗。
- **决策**: 
  1. **能力分级**: 将 MCP 工具和 Graph 节点明确划分为边缘端能力（`EDGE_TOOLS`）和云端能力（`CLOUD_TOOLS`）
  2. **四路分流**: supervisor_node 新增 `edge_handler` 路由，形成 `edge / urgent / normal / end` 四路分支
  3. **阈值参数化**: 分流阈值 `EDGE_CONFIDENCE_LOCAL_THRESHOLD = 0.90` 为模块级常量，edge_pre_screen 工具的阈值通过参数传入
- **理由**: 
  - 高置信度场景（>0.9）的特征已足够明确，无需 LLM + GraphRAG 增强即可生成有效工单
  - 边缘本地闭环可将响应延迟从 ~21s 降至 ~2s
  - 减少云端 LLM Token 消耗（预计 30-40% 的请求可在边缘端闭环）
  - 网络中断时边缘仍可独立处置明确违规，保证业务连续性
- **代价**: 边缘端工单不含法规/SOP 知识增强（`graph_context` 仅标注边缘处置），工单内容不如云端精算丰富
- **涉及文件**: [app/core/graph/nodes.py](app/core/graph/nodes.py)（+edge_handler_node + EDGE_CONFIDENCE_LOCAL_THRESHOLD）、[app/core/graph/workflow.py](app/core/graph/workflow.py)（+edge_handler 节点及条件边）、[app/tools/mcp_tools.py](app/tools/mcp_tools.py)（+EDGE_TOOLS/CLOUD_TOOLS 能力分级 + get_system_health）

### 能力分级矩阵

```
                     边缘端 (Edge)                    云端 (Cloud)
──────────────────────────────────────────────────────────────────────
  视觉分析    轻量模型 (yolov10n)           Qwen-VL-Max 精细分析
  路由决策    supervisor (四路分流)        supervisor (云端确认)
  GraphRAG    ❌ 跳过                       Neo4j + Milvus 混合检索
  专家记忆    ❌ 跳过                       Redis + Milvus 三层记忆
  工单生成    结构化模板 (轻量)             LLM 生成 (含法规引用)
  工单推送    ✅ 本地 MCP                   ✅ 云端 MCP

  工具分级    EDGE_TOOLS:                   CLOUD_TOOLS:
              - edge_pre_screen             - create_ehs_ticket
              - get_system_health 🆕        - verify_certificate
                                           - get_equipment_status
                                           - log_false_positive
```

### 四路分流流程

```
detection_node (Qwen-VL / 边缘轻量模型)
       │
       ▼
supervisor_node (路由决策)
       │
       ├─ max_confidence >= 0.90 ──→ edge_handler ──→ END
       │   (边缘即时处置: edge_pre_screen → 轻量工单 → 推送)
       │
       ├─ risk_level == "high"  ──→ urgent_handler ──→ END
       │   (云端全链路: GraphRAG → Memory → LLM工单 → 推送)
       │
       ├─ risk_level == "medium"──→ normal_handler ──→ END
       │   (云端全链路: 同 urgent，优先级较低)
       │
       └─ 其他 ──→ END (仅记录日志)
```

### 关联 ADR

- [ADR-2](#adr-2-mock-优先策略--配置化控制): Mock 优先策略支撑边缘离线运行
- [ADR-6](#adr-6-模块级常量替代魔法数字): `EDGE_CONFIDENCE_LOCAL_THRESHOLD` 遵循模块级常量规范
- [ADR-8](#adr-8-qwen-vl-真实调用--图片不可用时-mock-降级): 视觉分析双模（Qwen-VL 云端 / 轻量模型边缘）


---
## 长期规划：边缘-云端协同架构

> **状态**: 规划中（PROGRESS.md #16） | **优先级**: 长期 | **依赖**: 第 15 项「部署到生产」完成后启动

### 架构愿景

SafeGuard-AI 的目标部署拓扑为 **边缘端预筛 + 云端精算** 双层架构，以应对工业现场的网络带宽限制和实时性要求。

### 设计思路

```
┌─────────────────────────────────────────────────────────────────┐
│                        工业现场 (边缘层)                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐  │
│  │ 摄像头/传感器 │ → │ 边缘节点     │ → │ 本地 Neo4j (精简图谱)│  │
│  │ (RTSP 视频流) │    │ (SafeGuard  │    │ + Redis (短期记忆)   │  │
│  └─────────────┘    │  Edge)      │    └─────────────────────┘  │
│                      │             │                              │
│                      │ edge_pre_screen()                         │
│                      │ ├─ HIGH (>0.95) → 本地即时处置            │
│                      │ ├─ MEDIUM      → 加入队列批量上报         │
│                      │ └─ LOW (<0.6)  → 静默记录，不推送         │
│                      └──────┬──────┘                             │
│                             │ MEDIUM/UNCERTAIN                   │
│                             ▼                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                    安全通道 (HTTPS/MQTT)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        云端 (精算层)                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐  │
│  │ Qwen-VL-Max  │    │ 完整 Neo4j  │    │ Milvus (全量专家)    │  │
│  │ 精细视觉分析  │    │ (全量图谱)   │    │ + BGE-M3 向量检索   │  │
│  └─────────────┘    └─────────────┘    └─────────────────────┘  │
│                                                                  │
│  SafeGuard Cloud → 精算工单 → 反馈至边缘节点 (SFT 数据积累)      │
└─────────────────────────────────────────────────────────────────┘
```

### 现有基础

当前代码已为边缘-云端分流预留了关键组件：

| 组件 | 现状 | 边缘端角色 |
|------|------|-----------|
| `edge_pre_screen()` (MCP 工具) | ✅ 已实现，三档置信度分流 | 边缘节点本地决断——高置信即时处置，低置信静默记录 |
| Mock 优先策略 (ADR-2/7/8) | ✅ 全链路 Mock 降级 | 边缘节点可在网络中断时以 Mock 模式离线运行 |
| `NEO4J_USE_MOCK` 配置 | ✅ 环境变量控制 | 边缘端使用精简本地图谱，云端使用完整 Neo4j |
| `need_cloud_analysis` 字段 | ✅ `HazardState` 已有 | 由 `supervisor_node` 判定的云端需求标志 |
| `edge_node_id` 字段 | ✅ `HazardState` 已有 | 标识发起请求的边缘节点编号 |
| `area_type` 字段 | ✅ `HazardState` 已有 | 区域类型（production/warehouse/outdoor）影响路由决策 |
| Qwen-VL 视觉分析 (ADR-8) | ✅ 真实调用 + Mock 降级 | 边缘端本地轻量模型 / 云端完整 Qwen-VL-Max |

### 待实现

1. ✅ ~~**边缘端分流逻辑**~~ — supervisor_node 四路分流 + edge_handler_node + EDGE_CONFIDENCE_LOCAL_THRESHOLD (ADR-17, 2026-06-11)
2. ✅ ~~**MCP 工具能力分级**~~ — EDGE_TOOLS / CLOUD_TOOLS + get_system_health() 健康探测 (2026-06-11)
3. **边缘端镜像精简**：从完整 `Dockerfile` 拆分出 `Dockerfile.edge`，仅包含 Mock 模式 + 本地轻量模型，去除 `neo4j`/`pymilvus`/`dashscope` 等云依赖
4. **边缘-云端通信协议**：定义 MQTT Topic 规范（`safeguard/{edge_id}/alert`、`safeguard/{edge_id}/feedback`）
5. **离线队列**：边缘端网络中断时本地 SQLite 队列缓存待上报告警
6. **云端回调**：云端精算完成后通过 MQTT 回传工单结果至边缘节点
7. **模型同步**：SFT 微调后的轻量模型定期下发至边缘节点

### 关联 ADR

- [ADR-2](#adr-2-mock-优先策略--配置化控制)：Mock 优先策略是边缘离线运行的基础
- [ADR-6](#adr-6-模块级常量替代魔法数字)：`EDGE_CONFIDENCE_HIGH` / `EDGE_CONFIDENCE_LOW` 阈值控制分流逻辑
- [ADR-8](#adr-8-qwen-vl-真实调用--图片不可用时-mock-降级)：视觉分析云端/边缘双模运行

---

## 架构原则总结

从上述 13 个 ADR 中提炼出的核心架构原则：

1. **Mock 优先，配置驱动**: 所有外部依赖默认 Mock，通过环境变量显式切换到真实后端
2. **优雅降级**: 外部服务不可用时自动回退到 Mock，不阻断核心工作流
3. **接口预留，渐进升级**: Mock 实现与真实后端共享接口签名，替换无需修改调用方
4. **DRY (Don't Repeat Yourself)**: 发现重复立即提取共享实现
5. **安全第一**: 所有用户输入必须参数化，防止注入攻击
6. **可观测性**: 关键路径打印日志，异常附带堆栈，不用 `print()`
7. **中文优化**: 针对中文工业安全领域的检索与匹配做专项优化

---

## 相关文档

| 文档 | 说明 |
|------|------|
| [PROGRESS.md](PROGRESS.md) | 开发进度与完整的 ADR 原始记录 |
| [docs/安卫智脑详细技术方案](docs/🏭%20安卫智脑%20(SafeGuard%20AI)%20详细技术方案.md) | 完整的业务逻辑、数据库表结构、API 定义 |
| [CLAUDE.md](CLAUDE.md) | 开发指南与 AI 协作规范 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 部署指南（环境准备、Docker、API 验证） |
