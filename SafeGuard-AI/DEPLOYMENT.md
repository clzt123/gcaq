# SafeGuard-AI (安卫智脑) 部署指南

> 最后更新: 2026-06-11 | 适用版本: v0.1.0

---

## 📋 目录

1. [环境准备](#1-环境准备)
2. [配置文件](#2-配置文件)
3. [基础设施启动](#3-基础设施启动)
4. [应用启动](#4-应用启动)
5. [全链路验证](#5-全链路验证)
6. [API 文档](#6-api-文档)
7. [可观测性 (LangSmith)](#7-可观测性-langsmith)
8. [常见问题](#8-常见问题)
9. [生产部署流程](#9-生产部署流程)
   - [9.0 前置准备：创建生产环境配置](#90-前置准备创建生产环境配置)
   - [9.1 构建镜像](#91-构建镜像)
   - [9.2 启动服务](#92-启动服务)
   - [9.3 验证容器状态](#93-验证容器状态)
   - [9.4 查看日志](#94-查看日志)
   - [9.5 访问 Swagger 文档](#95-访问-swagger-文档)
   - [9.6 运行健康检查](#96-运行健康检查)
   - [9.7 端到端 API 验证](#97-端到端-api-验证)
   - [9.8 初始化数据库（首次部署）](#98-初始化数据库首次部署)
   - [9.9 停止与重启](#99-停止与重启)
   - [9.10 生产环境注意事项](#910-生产环境注意事项)
   - [9.11 生产环境 .env 检查清单](#911-生产环境-env-检查清单)
   - [9.12 🎉 部署成功！](#912--部署成功)

---

## 1. 环境准备

### 1.1 硬件要求

| 资源 | 最低配置 | 推荐配置 |
|------|----------|----------|
| CPU | 4 核 | 8 核+ |
| 内存 | 16 GB | 32 GB+ |
| 磁盘 | 20 GB 可用 | 50 GB+ SSD |

> **说明**：Milvus Standalone（内嵌 etcd + MinIO）需要至少 4 GB 空闲内存。若仅使用 Mock 模式（见下文），最低 8 GB 内存即可。

### 1.2 软件清单

| 软件 | 版本要求 | 用途 | 安装指引 |
|------|----------|------|----------|
| **Docker** | ≥ 24.0 | 运行 Neo4j / Redis / Milvus 容器 | [Docker Desktop](https://www.docker.com/products/docker-desktop/) |
| **Docker Compose** | ≥ 2.20 | 编排多容器依赖 | 随 Docker Desktop 附带 |
| **Python** | 3.10 - 3.12 | 应用运行环境 | [python.org](https://www.python.org/downloads/) |
| **pip** | ≥ 23.0 | Python 包管理 | 随 Python 附带 |
| **Git** | ≥ 2.40 | 版本控制（可选） | [git-scm.com](https://git-scm.com/) |

### 1.3 快速验证

```bash
# 检查已安装软件的版本
docker --version          # 应输出 ≥ 24.0
docker compose version    # 应输出 ≥ 2.20
python --version          # 应输出 3.10 - 3.12
pip --version             # 应输出 ≥ 23.0
```

### 1.4 Python 虚拟环境（推荐）

```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

---

## 2. 配置文件

### 2.1 创建 .env

```bash
# 复制模板
cp .env.example .env
```

### 2.2 关键配置项

编辑 `.env` 文件，填入以下关键配置：

```ini
# ========================================
# 🔑 必填项（生产环境必须配置真实值）
# ========================================

# --- LLM 大模型（DeepSeek / OpenAI 兼容接口） ---
LLM_API_KEY=sk-your-deepseek-api-key-here
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL_NAME=deepseek-chat

# --- 视觉大模型（阿里云 DashScope / Qwen-VL） ---
DASHSCOPE_API_KEY=sk-your-dashscope-api-key-here
DASHSCOPE_VL_MODEL=qwen-vl-max-latest
DASHSCOPE_VL_TIMEOUT=60.0

# ========================================
# 🗄️  数据库连接（Docker 本地部署无需修改）
# ========================================

# --- Neo4j 图数据库 ---
NEO4J_URI=bolt://localhost:17687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-neo4j-password
# NEO4J_USE_MOCK=true   # 开发环境默认注释 = Mock 模式（无需真实 Neo4j）

# --- Redis 短期记忆 ---
REDIS_URL=redis://localhost:6379/0

# --- Milvus 向量库 ---
MILVUS_HOST=localhost
MILVUS_PORT=19530
```

### 2.3 Mock 模式 vs 真实模式

| 组件 | Mock 模式（默认） | 真实模式 |
|------|-------------------|----------|
| **Neo4j** | 解析 `mock_data/init_graph.cypher`，内存图谱 | 取消注释 `NEO4J_USE_MOCK=false` |
| **Milvus** | 关键词匹配 `mock_data/mock_memory.json` | 代码预留 `use_mock=False` 参数（待中期实现） |
| **Redis** | `collections.deque` 滑动窗口缓冲 | 代码预留 Redis 接口（待中期实现） |
| **Qwen-VL** | 图片文件名关键词匹配 10 类隐患 | 配置真实 `DASHSCOPE_API_KEY` 即可自动切换 |

> **开发环境建议**：无需配置任何真实基础设施，Mock 模式即可跑通完整工作流（121 个单元测试 0 失败）。

---

## 3. 基础设施启动

### 3.1 合并版 docker-compose.yml（一键启动所有依赖）

以下为三个独立 compose 文件的整合版本，并存为项目根目录下的 `docker-compose.yml`：

```yaml
# ==========================================
# SafeGuard-AI — 全栈基础设施
# 启动命令: docker compose up -d
# ==========================================
version: "3.8"

services:
  # ====================
  # Neo4j 图数据库
  # ====================
  neo4j:
    image: neo4j:latest
    container_name: safeguard-neo4j
    restart: unless-stopped
    ports:
      - "7474:7474"     # HTTP 浏览器访问
      - "17687:7687"    # Bolt 协议（应用连接端口，与 .env 中 NEO4J_URI 一致）
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD:-your-neo4j-password}
      - NEO4J_server_memory_heap_initial__size=512m
      - NEO4J_server_memory_heap_max__size=1g
      - NEO4J_server_memory_pagecache_size=256m
      - NEO4J_server_directories_import=/
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
      - ./mock_data:/var/lib/neo4j/import
    healthcheck:
      test: ["CMD-SHELL", "cypher-shell -u neo4j -p ${NEO4J_PASSWORD:-your-neo4j-password} 'RETURN 1' || exit 1"]
      interval: 10s
      timeout: 10s
      retries: 10
      start_period: 30s

  # ====================
  # Redis 缓存
  # ====================
  redis:
    image: redis:7-alpine
    container_name: safeguard-redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    command: >
      redis-server
      --appendonly yes
      --save 900 1
      --save 300 10
      --save 60 10000
      --maxmemory 256mb
      --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s

  # ====================
  # Milvus 向量数据库
  # ====================
  milvus:
    image: milvusdb/milvus:v2.4.17
    container_name: safeguard-milvus
    restart: unless-stopped
    ports:
      - "19530:19530"   # gRPC（SDK 连接）
      - "9091:9091"     # HTTP 管理接口
    environment:
      - ETCD_USE_EMBED=true
      - ETCD_DATA_DIR=/var/lib/milvus/etcd
      - MINIO_USE_EMBED=true
      - MINIO_DATA_DIR=/var/lib/milvus/minio
      - COMMON_STORAGETYPE=local
    volumes:
      - milvus_data:/var/lib/milvus
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9091/healthz"]
      interval: 15s
      timeout: 10s
      retries: 10
      start_period: 60s
    command: ["milvus", "run", "standalone"]

volumes:
  neo4j_data:
    name: safeguard-neo4j-data
  neo4j_logs:
    name: safeguard-neo4j-logs
  redis_data:
    name: safeguard-redis-data
  milvus_data:
    name: safeguard-milvus-data
```

### 3.2 启动命令

```bash
# 一键启动所有基础设施（合并版）
docker compose up -d

# 或分别启动（使用独立 compose 文件）
docker compose -f docker-compose.neo4j.yml up -d
docker compose -f docker-compose.redis.yml up -d
docker compose -f docker-compose.milvus.yml up -d
```

### 3.3 健康检查与状态

```bash
# 查看所有容器运行状态
docker compose ps

# 预期输出：
# NAME                STATUS                    PORTS
# safeguard-neo4j     running (healthy)        0.0.0.0:7474->7474/tcp, 0.0.0.0:17687->7687/tcp
# safeguard-redis     running (healthy)        0.0.0.0:6379->6379/tcp
# safeguard-milvus    running (healthy)        0.0.0.0:19530->19530/tcp, 0.0.0.0:9091->9091/tcp
```

```bash
# 逐一验证服务可用性
# Neo4j — 浏览器访问或 curl
curl -s http://localhost:7474

# Redis — ping
docker exec safeguard-redis redis-cli ping   # 应返回 PONG

# Milvus — 健康端点
curl -s http://localhost:9091/healthz        # 应返回 200 OK
```

### 3.4 Neo4j 初始化数据（可选，生产/真实验证时执行）

```bash
# 将 mock_data/init_graph.cypher 导入真实 Neo4j
docker exec -i safeguard-neo4j cypher-shell \
  -u neo4j \
  -p "${NEO4J_PASSWORD:-your-neo4j-password}" \
  < mock_data/init_graph.cypher
```

> **提示**：导入后在 `.env` 中设置 `NEO4J_USE_MOCK=false` 即可切换为真实 Neo4j 查询。

### 3.5 停止与清理

```bash
# 停止所有容器（保留数据卷）
docker compose down

# 停止并删除所有数据卷（⚠️ 不可逆）
docker compose down -v
```

---

## 4. 应用启动

### 4.1 安装 Python 依赖

```bash
# 确保虚拟环境已激活
pip install -r requirements.txt
```

### 4.2 启动 FastAPI 服务

```bash
# 开发模式（热重载）
python -m app.main

# 或显式使用 uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

启动成功后的日志输出示例：

```
🚀 SafeGuard-AI v0.1.0 正在启动...
   LLM: https://api.deepseek.com (model: deepseek-chat)
   Neo4j: bolt://localhost:17687
   Redis: redis://localhost:6379/0
   Milvus: localhost:19530
```

### 4.3 验证基础连通性

```bash
# 健康检查
curl http://localhost:8000/health
```

预期返回：

```json
{
  "status": "healthy",
  "app": "SafeGuard-AI",
  "version": "0.1.0",
  "timestamp": "2026-06-11T12:00:00.000000"
}
```

---

## 5. 全链路验证

`run_real_test.py` 是端到端验证脚本，测试完整管线：

```
真实图片 → Qwen-VL 视觉分析 → 路由决策 → GraphRAG 检索 → 专家记忆注入 → 工单生成 → MCP 推送
```

### 5.1 前置条件

| 条件 | 说明 |
|------|------|
| `.env` 中 `DASHSCOPE_API_KEY` 已配置 | 真实 Qwen-VL 多模态视觉分析（不配置则自动降级为 Mock） |
| 测试图片存在 | `mock_data/images/` 目录下包含 4 张真实测试图片 |
| （可选）Neo4j Docker 已启动 + `NEO4J_USE_MOCK=false` | 真实 Neo4j 图数据库检索 |

### 5.2 运行测试

```bash
# 全链路测试 — 使用第 1 条告警（油渍泄漏）
python run_real_test.py

# 指定告警序号（1-4）
python run_real_test.py 2    # 消防通道堵塞
python run_real_test.py 3    # 未戴安全帽焊接
python run_real_test.py 4    # 化学品烟雾

# 仅测试 Qwen-VL 视觉分析（不跑全链路）
python run_real_test.py --vision-only

# 指定自定义图片
python run_real_test.py --image /path/to/your/image.jpg

# 静默模式（减少日志输出）
python run_real_test.py --quiet
```

### 5.3 预期输出（全链路通过）

```
══════════════════════════════════════════════════════════════════════
  📋 全链路结果汇总
══════════════════════════════════════════════════════════════════════
  ⏱  总耗时: 5.23s

  🔍 [检测节点] 视觉分析结果:
     risk_level:        high
     findings 数量:     2
       [0] type=oil_leak, confidence=0.92, desc=地面大面积油渍...
       [1] type=slip_hazard, confidence=0.88, desc=人员行走区域湿滑...

  🧭 [路由节点] 决策:
     next_action:       urgent
     need_cloud:        False

  📚 [GraphRAG] 知识检索上下文 (621 字符):
     ## 1. 检索到的隐患 (Hazard)
     【液压油泄漏】⚠️ 高风险 — 法规依据: GB 50016-2014...

  🧠 [记忆系统] 专家经验与反思 (156 字符):
     【历史经验参考】
     📌 专家经验 #1 (相关度: 0.75)
     立即设置警戒线并启动应急响应流程...

  📝 [工单生成] 最终工单:
     title:       【紧急】油渍泄漏 - 生产区A
     priority:    P0
     hazard_type: oil_leak

  📤 [MCP 推送] 状态:
     ticket_status:     sent

══════════════════════════════════════════════════════════════════════
  🏁 最终判定
══════════════════════════════════════════════════════════════════════
  ✅ 高风险隐患工单已成功推送至 EHS 系统。
```

### 5.4 运行单元测试

```bash
# 运行全部 121 个测试
pytest

# 按模块分运行
pytest tests/test_mcp_tools.py     # 22 用例 — MCP 工具层
pytest tests/test_neo4j_client.py  # 21 用例 — Neo4j 客户端
pytest tests/test_retriever.py     # 24 用例 — GraphRAG 检索
pytest tests/test_workflow.py      # 37 用例 — LangGraph 状态机
pytest tests/test_api.py           # 17 用例 — FastAPI 接口

# 详细输出
pytest -v
```

预期结果：

```
tests/test_mcp_tools.py     22 passed
tests/test_neo4j_client.py  21 passed
tests/test_retriever.py     24 passed
tests/test_workflow.py      37 passed
tests/test_api.py           17 passed
=============================== 121 passed in 2.05s
```

---

## 6. API 文档

### 6.1 Swagger UI

启动应用后，浏览器访问：

```
http://localhost:8000/docs
```

Swagger UI 提供：
- 交互式 API 文档（所有端点、请求/响应 Schema、可在线调用）
- 每个接口的 curl 示例
- `POST /api/v1/hazard/analyze` — 隐患研判（串联完整工作流）
- `GET /api/v1/hazard/alerts` — 告警列表（支持 `?limit=1-100`）
- `GET /api/v1/hazard/alerts/{alert_id}` — 告警详情
- `GET /health` — 健康检查

### 6.2 ReDoc

提供替代风格的 API 文档：

```
http://localhost:8000/redoc
```

### 6.3 快速 API 调用示例

```bash
# 隐患研判 — 使用 mock 告警
curl -X POST http://localhost:8000/api/v1/hazard/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "alert_id": "ALERT-001",
    "image_url": "/mock_data/images/inj_mold_leak.jpg",
    "area_type": "production"
  }' | python -m json.tool

# 获取告警列表
curl http://localhost:8000/api/v1/hazard/alerts?limit=10

# 获取告警详情
curl http://localhost:8000/api/v1/hazard/alerts/ALERT-001
```

---

## 7. 可观测性 (LangSmith)

SafeGuard-AI 集成 [LangSmith](https://smith.langchain.com) 用于全链路可观测性追踪：

- 🔍 **LangGraph 执行流**：每个节点的输入/输出、耗时、路由决策
- 🔎 **RAG 检索调试**：Neo4j Cypher 查询、Milvus 向量检索的召回效果
- 📊 **LLM 调用监控**：Token 用量、延迟、错误率

### 7.1 获取 API Key

1. 访问 [smith.langchain.com](https://smith.langchain.com) 注册/登录
2. 进入 **Settings** → **API Keys** → **Create API Key**
3. 复制生成的 Key（格式：`lsv2_pt_...`）

### 7.2 配置 .env

```ini
LANGSMITH_API_KEY=lsv2_pt_your-key-here
LANGSMITH_PROJECT=SafeGuard-AI
# LANGSMITH_ENDPOINT=https://api.smith.langchain.com   # 默认值，无需修改
```

> 配置后重启应用即可生效。追踪数据约 30 秒内出现在 LangSmith 控制台。

### 7.3 验证追踪是否启用

**Web 服务启动时**，观察日志输出：

```
✅ LangSmith tracing enabled for project: SafeGuard-AI
   LangSmith: ✅ enabled — project: SafeGuard-AI
```

若未配置 API Key：

```
⚠️  LangSmith API Key missing, tracing disabled. 请在 .env 中设置 LANGSMITH_API_KEY
   LangSmith: ⚠️  disabled (missing API Key)
```

### 7.4 在控制台查看 Trace

1. 触发一次 API 调用（Web 服务或跑测试脚本均可）：
   ```bash
   # 方式一：Web API
   curl -X POST http://localhost:8000/api/v1/hazard/analyze \
     -H "Content-Type: application/json" \
     -d '{"alert_id":"TEST","image_url":"/mock_data/images/inj_mold_leak.jpg"}'

   # 方式二：全链路测试脚本
   python run_real_test.py
   ```
2. 打开 [smith.langchain.com](https://smith.langchain.com) → 选择 Project `SafeGuard-AI`
3. 在 Traces 列表中点击最新的 Trace ID 查看完整执行流
4. 每个 Trace 包含：
   - 整体耗时、Token 用量、输入/输出
   - LangGraph 节点级别的执行详情
   - LLM 调用级别的 Prompt/Response 对
   - Neo4j/Milvus 检索的召回结果

### 7.5 Trace ID 关联

每次 API 调用都会生成唯一的 Trace ID，可在响应中通过 `metadata.run_id` 获取。
在 LangSmith 控制台中搜索该 Run ID 即可精确定位到单次请求的完整链路。

---
## 8. 常见问题

### 8.1 Docker 容器启动失败

**问题**：`docker compose up -d` 后容器状态为 `unhealthy` 或反复重启。

**排查**：

```bash
# 查看容器日志
docker compose logs neo4j
docker compose logs redis
docker compose logs milvus

# 检查端口冲突
# Neo4j:  7474, 17687
# Redis:  6379
# Milvus: 19530, 9091
netstat -ano | findstr "7474 17687 6379 19530 9091"    # Windows
lsof -i :7474 -i :17687 -i :6379 -i :19530 -i :9091    # macOS / Linux
```

**解决**：端口冲突时修改 `docker-compose.yml` 中的 host 端口映射（仅改冒号左侧）。

### 8.2 Milvus 内存不足

**问题**：Milvus 容器 OOM 或被 killed。

**解决**：
- 方案一：调高 Docker Desktop 的内存上限（Settings → Resources → Memory → ≥ 8 GB）
- 方案二：短期可不启动 Milvus（当前代码使用 Mock 关键词匹配，无需真实 Milvus）：
  ```bash
  docker compose up -d neo4j redis  # 仅启动 Neo4j + Redis
  ```

### 8.3 DashScope API Key 无效

**问题**：`run_real_test.py` 中 Qwen-VL 调用返回 `401 Unauthorized`。

**解决**：
- 检查 `.env` 中 `DASHSCOPE_API_KEY` 是否正确（需为 DashScope 真实 Key，非 DeepSeek Key）
- [阿里云 DashScope API Key 申请地址](https://dashscope.console.aliyun.com/apiKey)
- 若不配置 Key，系统自动降级为 Mock 关键词匹配（不影响工作流通畅性）

### 8.4 Mock 模式下 GraphRAG 检索命中 0 条

**问题**：API 返回的 `graph_context` 为空字符串。

**解决**：这通常是因为查询关键词与 mock 数据不匹配。确认：
- `mock_data/init_graph.cypher` 文件存在且包含中文节点名
- `mock_data/mock_memory.json` 文件存在且包含 `long_term_expert_memory` 数据
- Qwen-VL 返回的隐患类型在 `HAZARD_TYPE_ZH_MAP` 映射表中（详见 `app/core/graph/nodes.py`）

### 8.5 Windows 终端中文乱码

**问题**：PowerShell 输出中文为乱码。

**解决**：
- `run_real_test.py` 已内置 UTF-8 重配置（`sys.stdout.reconfigure(encoding="utf-8")`）
- 或手动执行：`chcp 65001` 切换终端代码页为 UTF-8
- 推荐使用 Windows Terminal 运行

### 8.6 pip 安装依赖失败

**问题**：`pip install -r requirements.txt` 报错。

**解决**：

```bash
# 升级 pip
pip install --upgrade pip

# 单独安装有问题的包，查看详细错误
pip install pymilvus>=2.4.0 --verbose

# Windows 上 opencv 可能需要 Visual C++ Redistributable
# 下载地址: https://aka.ms/vs/17/release/vc_redist.x64.exe
```

---

## 9. 生产部署流程

> **适用场景**：将 SafeGuard-AI FastAPI 应用与所有依赖服务（Neo4j、Redis、Milvus）一并容器化部署到生产环境。
>
> **⚠️ 盲测自检**：以下步骤已按"全新云服务器 + 仅 `git clone` 代码"的零基础场景验证，每一处 `localhost` 替换均已在对应步骤中显式标注。按顺序执行即可。

### 9.0 前置准备：创建生产环境配置

> **这是最容易出错的步骤！** Docker Compose 内部通过服务名通信，直接使用 `.env.example` 中的 `localhost` 地址会导致 API 容器无法连接数据库。

```bash
# 1. 复制模板
cp .env.example .env

# 2. 编辑 .env，修改以下关键项（必须！）
#    ⚠️ 数据库地址必须从 localhost 改为 Docker 服务名
```

**最小可运行配置** （直接覆盖 `.env` 中的对应行）：

```ini
# ========================================
# 🔑 必填 — API Key（必须替换为真实值）
# ========================================
LLM_API_KEY=sk-your-deepseek-api-key-here
DASHSCOPE_API_KEY=sk-your-dashscope-api-key-here

# ========================================
# 🗄️  数据库连接 — Docker 服务名（勿用 localhost！）
# ========================================
# 关键：容器内部通过 compose 服务名互相访问
#   Neo4j:  safeguard-neo4j:7687  (不是 localhost:17687)
#   Redis:  safeguard-redis:6379
#   Milvus: safeguard-milvus:19530
NEO4J_URI=bolt://safeguard-neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-neo4j-password
NEO4J_USE_MOCK=false

REDIS_URL=redis://safeguard-redis:6379/0

MILVUS_HOST=safeguard-milvus
MILVUS_PORT=19530

# ========================================
# 📊 可观测性（推荐启用）
# ========================================
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=SafeGuard-AI-Production
```

> **对照表 — 主机访问 vs 容器内访问**：
>
> | 服务 | 主机上访问 (`localhost`) | 容器内访问 (Docker 网络) |
> |------|--------------------------|---------------------------|
> | Neo4j Bolt | `bolt://localhost:17687` | `bolt://safeguard-neo4j:7687` |
> | Redis | `redis://localhost:6379/0` | `redis://safeguard-redis:6379/0` |
> | Milvus | `localhost:19530` | `safeguard-milvus:19530` |
> | API | `http://localhost:8000` | `http://safeguard-api:8000` |

### 9.1 构建镜像

```bash
# 方式一：单独构建 API 镜像
docker build -t safeguard-api:latest .

# 方式二：通过 docker compose 构建所有服务
docker compose build

# 仅构建 API 服务（跳过基础设施镜像拉取）
docker compose build safeguard-api
```

构建成功后的预期输出（注意：生产镜像不包含 mock_data）：

```
 => [runtime 1/5] FROM python:3.11-slim
 => [builder 1/5] RUN apt-get update && ...
 => [builder 2/5] RUN python -m venv /opt/venv
 => [builder 3/5] COPY requirements.txt .
 => [builder 4/5] RUN pip install --no-cache-dir -r requirements.txt
 => [runtime 2/5] RUN apt-get update && apt-get install -y ...
 => [runtime 3/5] COPY --from=builder /opt/venv /opt/venv
 => [runtime 4/5] WORKDIR /app
 => [runtime 5/5] COPY app/ app/
 => => exporting to image
 => => naming to docker.io/library/safeguard-api:latest
```

### 9.2 启动服务

```bash
# 一键启动全栈服务（Neo4j + Redis + Milvus + FastAPI）
docker compose up -d

# 或仅启动基础设施 + API（跳过不需要的服务）
docker compose up -d neo4j redis milvus safeguard-api
```

### 9.3 验证容器状态

```bash
# 查看所有容器运行状态（应全部显示 healthy）
docker compose ps
```

预期输出：

```
NAME                 STATUS                    PORTS
safeguard-neo4j      running (healthy)         0.0.0.0:7474->7474/tcp, 0.0.0.0:17687->7687/tcp
safeguard-redis      running (healthy)         0.0.0.0:6379->6379/tcp
safeguard-milvus     running (healthy)         0.0.0.0:19530->19530/tcp, 0.0.0.0:9091->9091/tcp
safeguard-api        running (healthy)         0.0.0.0:8000->8000/tcp
```

### 9.4 查看日志

```bash
# 实时跟踪 API 服务日志
docker compose logs -f safeguard-api

# 查看所有服务日志（滚动到底部）
docker compose logs --tail=100

# 查看最近 5 分钟的日志
docker compose logs --since=5m safeguard-api
```

启动成功的典型日志输出：

```
🚀 SafeGuard-AI v0.1.0 正在启动...
   LLM: https://api.deepseek.com (model: deepseek-chat)
   Neo4j: bolt://safeguard-neo4j:7687
   Redis: redis://safeguard-redis:6379/0
   Milvus: safeguard-milvus:19530
   LangSmith: ⚠️  disabled (missing API Key) — project: SafeGuard-AI
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

> **容器间通信提示**：Docker Compose 内部通过服务名通信。在容器内，`.env` 中的 `localhost` 应替换为对应的服务名（如 `safeguard-neo4j`、`safeguard-redis`、`safeguard-milvus`）。建议生产环境使用专用的 `.env.production` 文件覆盖这些地址。

### 9.5 访问 Swagger 文档

启动成功后，浏览器访问交互式 API 文档：

```
http://localhost:8000/docs
```

或访问 ReDoc 替代风格：

```
http://localhost:8000/redoc
```

### 9.6 运行健康检查

```bash
# 基础健康检查
curl http://localhost:8000/health

# 在企业内网中，可使用 Docker 内部网络地址
docker exec safeguard-api python -c "import httpx; print(httpx.get('http://localhost:8000/health').json())"
```

预期返回：

```json
{
  "status": "healthy",
  "app": "SafeGuard-AI",
  "version": "0.1.0",
  "timestamp": "2026-06-11T12:00:00.000000"
}
```

### 9.7 端到端 API 验证

```bash
# 方式一：指定公网可访问的图片 URL（推荐生产验证）
curl -X POST http://localhost:8000/api/v1/hazard/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "alert_id": "PROD-TEST-001",
    "image_url": "https://example.com/test-safety-image.jpg",
    "area_type": "production"
  }' | python -m json.tool

# 方式二：不传图片（触发 Mock 降级，验证工作流连通性）
curl -X POST http://localhost:8000/api/v1/hazard/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "alert_id": "SMOKE-TEST-001",
    "image_url": "",
    "area_type": "warehouse"
  }' | python -m json.tool

# 方式三：获取告警列表（验证 API 基本联通）
curl http://localhost:8000/api/v1/hazard/alerts?limit=5 | python -m json.tool
```

> **说明**：生产镜像已通过 `.dockerignore` 排除 `mock_data/` 目录以减小体积。如需使用项目内置测试图片验证，请在宿主机上通过 Python 虚拟环境运行全链路测试脚本（详见[第 5 章](#5-全链路验证)）。

### 9.8 初始化数据库（首次部署）

> **说明**：`scripts/` 目录已由 `.dockerignore` 排除（生产镜像不含一次性脚本）。数据初始化通过 `docker compose run` 挂载宿主机脚本目录执行，脚本使用 Docker 内部网络连接数据库，无需在宿主机安装 Python 依赖。

**前置条件**：基础设施服务已启动且健康（至少 neo4j + milvus）。

```bash
# 确认数据库服务已就绪
docker compose ps neo4j milvus
# 应显示 (healthy)

# === Neo4j 图谱初始化 ===
# --yes 跳过确认提示；--dry-run 可预览不执行
docker compose run --rm \
  -v "${PWD}/scripts:/scripts:ro" \
  -v "${PWD}/mock_data:/mock_data:ro" \
  safeguard-api \
  python /scripts/init_neo4j.py --yes

# === Milvus 专家经验向量化 ===
# --force 重建 Collection；--dry-run 可预览不执行
docker compose run --rm \
  -v "${PWD}/scripts:/scripts:ro" \
  -v "${PWD}/mock_data:/mock_data:ro" \
  safeguard-api \
  python /scripts/embed_to_milvus.py --force
```

**预期输出（Neo4j）**：

```
🔌 连接 Neo4j: bolt://safeguard-neo4j:7687
🗑️  清空现有图谱...
✅ 已清空
📄 解析 mock_data/init_graph.cypher...
   解析到 13 条 CREATE 语句
🚀 执行导入...
   [1/13] ✅ CREATE (:Hazard {...})
   ...
📊 导入完成: 13 节点 + 10 关系
```

**预期输出（Milvus）**：

```
🔌 连接 Milvus: safeguard-milvus:19530
📦 Collection: expert_memory
🚀 加载 embedding 模型: BAAI/bge-m3
   向量维度: 1024
✅ 已插入 2 条专家经验
```

> **提示**：初始化完成后，在 `.env` 中确认 `NEO4J_USE_MOCK=false`，然后重启 API 使配置生效：
> ```bash
> docker compose restart safeguard-api
> ```

### 9.9 停止与重启

```bash
# 停止所有服务（保留数据卷）
docker compose down

# 重启单个服务（代码更新后）
docker compose up -d --build safeguard-api

# 重启所有服务
docker compose restart

# ⚠️ 停止并删除所有数据卷（不可逆）
docker compose down -v
```

### 9.10 生产环境注意事项

| 类别 | 注意事项 | 影响 |
|------|----------|------|
| **密码安全** | 替换 `.env` 中所有默认密码（`NEO4J_PASSWORD`、`LLM_API_KEY`、`DASHSCOPE_API_KEY`） | 🔴 严重 |
| **Neo4j 模式** | 设置 `NEO4J_USE_MOCK=false` 启用真实图数据库检索 | 🟡 功能 |
| **API Key** | 确保 `LLM_API_KEY` 和 `DASHSCOPE_API_KEY` 为有效的生产密钥 | 🔴 严重 |
| **容器间地址** | 容器化部署时，`localhost` 需替换为 Docker 服务名 | 🟡 连通 |
| **数据持久化** | 确认 Docker 命名卷已正确挂载（`docker volume ls`） | 🔴 数据 |
| **日志轮转** | 生产环境建议接入 ELK / Loki 集中日志收集 | 🟢 运维 |
| **CORS 配置** | 生产环境应将 `allow_origins=["*"]` 限制为具体域名 | 🟡 安全 |
| **HTTPS** | 生产环境应在反向代理（Nginx/Caddy）层启用 TLS 终止 | 🟡 安全 |
| **资源限制** | 通过 Docker Compose `deploy.resources.limits` 限制容器内存/CPU | 🟢 运维 |
| **反向代理** | 建议前置 Nginx/Caddy 处理静态文件、限流、访问日志 | 🟢 运维 |

### 9.11 生产环境 .env 检查清单

部署前请逐项确认：

```ini
# ✅ 密码已替换为强密码（建议 16+ 字符随机字符串）
NEO4J_PASSWORD=<strong-random-password>

# ✅ API Key 已配置且有效
LLM_API_KEY=sk-<your-production-key>
DASHSCOPE_API_KEY=sk-<your-production-key>

# ✅ Mock 模式已关闭（生产环境必须连接真实数据库）
NEO4J_USE_MOCK=false

# ✅ 容器间地址已更新（在 docker compose 内运行时）
NEO4J_URI=bolt://safeguard-neo4j:7687
REDIS_URL=redis://safeguard-redis:6379/0
MILVUS_HOST=safeguard-milvus

# ✅ 可观测性已启用（推荐）
LANGSMITH_API_KEY=lsv2_pt_<your-langsmith-key>
LANGSMITH_PROJECT=SafeGuard-AI-Production
```

---

### 9.12 🎉 部署成功！

如果以上步骤全部通过，恭喜！SafeGuard-AI 全栈服务已成功部署。

**现在你可以**：

| 操作 | 入口 | 说明 |
|------|------|------|
| 🔍 **交互式 API 调试** | [http://localhost:8000/docs](http://localhost:8000/docs) | Swagger UI — 在线调用所有 API |
| 📖 **API 文档阅读** | [http://localhost:8000/redoc](http://localhost:8000/redoc) | ReDoc — 更易读的 API 参考 |
| 🏥 **健康检查** | `curl http://localhost:8000/health` | 监控探针（K8s liveness/readiness） |
| 📊 **全链路追踪** | [smith.langchain.com](https://smith.langchain.com) | LangSmith — 查看完整 Trace |
| 🗄️  **图数据库浏览器** | [http://localhost:7474](http://localhost:7474) | Neo4j Browser — 可视化图谱 |
| 📝 **查看实时日志** | `docker compose logs -f safeguard-api` | 生产问题排查 |

**日常运维速查**：

```bash
# 查看服务状态
docker compose ps

# 滚动更新 API（代码变更后）
docker compose up -d --build safeguard-api

# 查看 API 最近 100 行日志
docker compose logs --tail=100 safeguard-api

# 平滑重启 API
docker compose restart safeguard-api

# 停止全部服务（保留数据）
docker compose down

# 完全销毁（含数据卷 ⚠️）
docker compose down -v
```

**下一步建议**：

1. **接入 CI/CD**：将 `docker compose build` 加入 CI 流水线
2. **配置反向代理**：前置 Nginx/Caddy 提供 HTTPS 终结 + 限流
3. **K8s 迁移**：将 `docker-compose.yml` 翻译为 Helm Chart
4. **边缘节点部署**：参阅 [ARCHITECTURE.md — 边缘-云端协同架构](ARCHITECTURE.md)
5. **SFT 微调准备**：积累驳回反馈数据（`log_false_positive` MCP 工具）

---

## 📁 部署文件速查

| 文件 | 用途 |
|------|------|
| `.env.example` | 环境变量模板 |
| `.env` | 实际环境变量（从模板复制，不入 Git） |
| `Dockerfile` | API 多阶段构建定义（python:3.11-slim） |
| `.dockerignore` | Docker 构建排除规则（12 类文件） |
| `docker-compose.yml` | 一键启动全栈四服务（Neo4j + Redis + Milvus + API） |
| `docker-compose.neo4j.yml` | 独立 Neo4j 部署 |
| `docker-compose.redis.yml` | 独立 Redis 部署 |
| `docker-compose.milvus.yml` | 独立 Milvus 部署 |
| `requirements.txt` | Python 依赖清单 |
| `run_real_test.py` | 全链路真实验证脚本 |
| `scripts/init_neo4j.py` | Neo4j 图谱初始化脚本 |
| `scripts/embed_to_milvus.py` | Milvus 专家经验向量化脚本 |
| `mock_data/` | Mock 数据（JSON + Cypher + 测试图片） |

---

## 🚀 最小化部署（开发环境，3 分钟上手）

```bash
# 1. 克隆项目
cd SafeGuard-AI

# 2. 创建环境变量（全部使用默认 Mock 模式）
cp .env.example .env

# 3. 创建虚拟环境 + 安装依赖
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt

# 4. 启动应用（无需 Docker，Mock 模式零外部依赖）
python -m app.main

# 5. 验证
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/v1/hazard/analyze \
  -H "Content-Type: application/json" \
  -d '{"alert_id":"TEST","image_url":"/mock_data/images/inj_mold_leak.jpg"}'

# 6. 运行全链路验证（需配置 DASHSCOPE_API_KEY）
python run_real_test.py
```

> **提示**：Mock 模式下无需启动任何 Docker 容器即可运行完整工作流。需要真实 Neo4j 检索时才执行 `docker compose up -d` + 设置 `NEO4J_USE_MOCK=false`。
