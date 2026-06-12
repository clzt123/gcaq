```markdown
# SafeGuard AI (安卫智脑) 开发指南

## 0. 🚨 最高优先级指令 (Context & Knowledge)
- **核心设计蓝图**: 本项目的详细业务逻辑、数据库表结构、API 定义及 Prompt 模板，均位于 **[docs/安卫智脑 (SafeGuard AI) 详细技术方案.md](docs/安卫智脑%20(SafeGuard%20AI)%20详细技术方案.md)**。
- **执行原则**: 在编写任何业务代码（尤其是 `nodes.py`, `state.py`, `mcp_tools.py`）之前，**必须**先读取上述文档中的对应章节。**严禁凭空捏造字段或逻辑**。
- **架构参考规范**:
    - **`Base/` (架构参考模板)**: 仅作为**项目结构设计范本**（如分层逻辑、依赖注入模式、错误处理框架）。**禁止直接导入其代码**，所有功能必须独立重写，但需遵循其核心设计原则（如模块解耦、配置隔离）。
    - **`WorkFlow/` (实现参考)**: 仅展示 LangGraph 的封装思路。你需要**完全独立实现**业务逻辑，但状态机设计需保持与 `Base` 一致的抽象层级（例如：感知层→决策层→执行层）。

## 1. 项目概述
- **项目名称**：SafeGuard-AI
- **项目定位**：工业安全智能体（Industrial Safety Agent）。
- **核心业务**：隐患智能研判与闭环处置工作流。
- **核心策略**：**参考架构，从零实现**。
- **严禁复制粘贴**：绝对禁止直接复制外部项目（如 `Base` 或同级 `WorkFlow`）的代码文件到当前项目中。

## 2. 核心技术栈与版本要求
- **AI 编排**: LangGraph (>=0.2.0), LangChain (>=0.3.0)
- **大模型服务**:
    - **推理模型**: Qwen2.5 / DeepSeek-V3 (推荐使用 `langchain_community.chat_models.Tongyi` 或 OpenAI 兼容接口)。
    - **多模态模型**: Qwen-VL (用于图片隐患识别)。
    - **向量模型**: bge-m3 (本地部署或 API)。
- **数据存储**: Neo4j (图数据库), Milvus (向量库), Redis (短期记忆/缓存)。
- **后端框架**: FastAPI + Uvicorn (异步优先)。
- **跨系统协同**: MCP (Model Context Protocol) Python SDK。
- **配置管理**: pydantic-settings (强制要求，禁止硬编码密钥)。
- **测试框架**: pytest + pytest-asyncio。

## 3. 强制目录结构
请严格遵守以下目录结构，禁止随意新建顶层文件夹：

​```text
safeguard_ai/
├── app/
│   ├── main.py                # FastAPI 启动入口
│   ├── config.py              # 环境变量与配置加载 (pydantic-settings)
│   ├── api/v1/hazard.py       # 隐患研判接口
│   ├── core/
│   │   ├── graph/             # LangGraph 状态机与节点
│   │   │   ├── state.py       # 【核心】定义 LangGraph 的 State 契约
│   │   │   ├── workflow.py    # 图编排与流转逻辑
│   │   │   └── nodes.py       # 具体的节点执行函数
│   │   ├── rag/               # GraphRAG 检索引擎
│   │   │   ├── neo4j_client.py # Neo4j 连接与 Cypher 执行
│   │   │   └── retriever.py   # 混合检索逻辑
│   │   └── memory/            # 记忆系统
│   │       └── manager.py     # 长短期记忆管理
│   ├── tools/                 # MCP 工具定义
│   │   └── mcp_tools.py       # 跨系统接口封装
│   └── utils/                 # 通用工具类
├── tests/                     # 单元测试与集成测试
├── mock_data/                 # Mock 数据 (JSON/Cypher)
├── docs/                      # 技术文档与设计方案
│   └── 安卫智脑 (SafeGuard AI) 详细技术方案.md
├── .env                       # 环境变量 (禁止提交到Git)
├── CLAUDE.md                  # 本文件
└── requirements.txt
```

## 4. 核心数据契约 (State Definition)
LangGraph 的节点间通信必须使用强类型。请在 `app/core/graph/state.py` 中定义如下状态（具体字段以 `docs` 中的方案为准）：

```python
from typing import TypedDict, Annotated, List
from langgraph.graph.message import add_messages

class HazardState(TypedDict):
    messages: Annotated[List, add_messages] # 对话历史
    alert_id: str                          # 告警ID
    image_url: str                         # 图片路径/Base64
    graph_context: str                     # GraphRAG 检索到的上下文
    memory_context: str                    # 记忆系统召回的经验
    ticket_payload: dict                   # 最终生成的工单数据
```

## 5. 开发路线图 (Roadmap)
**请严格按照以下顺序进行开发，每完成一步必须等待我确认后再进行下一步：**

1.  **Phase 1**: 搭建基础架构 (`config.py`, `main.py`, `requirements.txt`)。
2.  **Phase 2**: 实现 Mock 数据读取与 MCP 工具层 (`mcp_tools.py`)。
    - *注意*: `mock_data/` 中的 JSON 文件必须包含**至少 3 种典型隐患场景**（如：未戴安全帽、烟火检测、通道堵塞），且字段结构必须与 `HazardState` 严格一致。
3.  **Phase 3**: 实现 GraphRAG 引擎 (`neo4j_client.py`, `retriever.py`)。
4.  **Phase 4**: 实现 LangGraph 状态机与核心节点 (`state.py`, `nodes.py`, `workflow.py`)。
    - *特别提示*：在实现 `workflow.py` 时，请参考同级目录下 `WorkFlow` 文件夹的**封装设计模式**（如 State 定义、消息传递机制），但**严禁复制其代码**。请基于本项目的 `HazardState` 重新编写。
5.  **Phase 5**: 串联 FastAPI 接口与端到端测试。

## 6. AI 协作与代码生成规范
1.  **配置先行**: 所有外部依赖必须通过 `app/config.py` 统一管理。
    - *环境变量清单*: `DASHSCOPE_API_KEY`, `NEO4J_URI`, `NEO4J_PASSWORD`, `MILVUS_HOST`, `REDIS_URL`, `MCP_SERVER_URL`。
2.  **异步优先**: FastAPI 接口、LangGraph 节点、数据库查询必须使用 `async/await`。
3.  **工具集成规范**: 在 LangGraph 中调用 MCP 工具时，必须使用 LangChain 的 `@tool` 装饰器将其包装，并通过 LangGraph 的 `ToolNode` 进行调度，禁止在节点函数中直接硬编码 HTTP 请求。
4.  **零幻觉原则**: GraphRAG 必须实现“先查 Neo4j，再注入 Prompt”的逻辑。
    - *Cypher 生成*: 优先使用 LangChain 的 `GraphCypherQAChain` 或自定义 Prompt 生成 Cypher，**禁止手写固定 SQL**。
    - *兜底策略*: 当 Neo4j 返回空结果时，自动降级为 Milvus 向量检索，并将两者结果合并。
5.  **优雅降级**: 外部工具调用必须包含 `try-except` 块，失败时返回明确的错误信息。
6.  **测试驱动与隔离**: 每次实现核心功能后，必须在 `tests/` 目录下编写对应的 `pytest` 用例。**严禁在单元测试中直接操作生产环境的图数据库节点，必须使用 Mock 或独立测试库。** 7. **分步执行**: 遇到复杂需求，先输出实现计划（Step-by-step），等待我回复“确认”后，再开始编写代码。
7.  **思维链验证**: 在编写 `workflow.py` 或 `nodes.py` 时，如果参考了同级 `WorkFlow` 项目的模式，**必须在代码注释中注明**：“借鉴了 WorkFlow 的 [具体模块] 设计思路，并根据本项目 State 进行了重构”。**禁止直接复制粘贴任何超过 10 行的代码块。**

## 7. 工程化底线要求
1.  **日志规范**: 严禁使用 `print()`。必须使用 Python 标准 `logging` 模块。关键节点（如 LLM 调用、Cypher 执行、MCP 工具调用）必须打印 `INFO` 级别日志，异常必须打印 `ERROR` 级别日志并附带堆栈信息。
2.  **注释与文档**: 所有核心类、复杂函数必须包含中文 Docstring，明确说明“功能描述”、“参数(Args)”和“返回值(Raises/Returns)”。
3.  **Git 提交规范**: 每次完成一个独立功能或修复 Bug 后，必须执行 Git Commit。提交信息必须遵循 `feat: xxx` 或 `fix: xxx` 的格式。