# run_real_test.py — 全链路真实环境验证指南

> 最后更新: 2026-06-11

---

## 概述

`run_real_test.py` 是 SafeGuard-AI 的端到端验证脚本，测试完整的隐患研判管线：

```
真实图片 → Qwen-VL 视觉分析 → 路由决策 → GraphRAG 检索 → 专家记忆注入 → 工单生成 → MCP 推送
```

---

## 前置条件

| 条件 | 必须？ | 说明 |
|------|--------|------|
| Python 虚拟环境 + `pip install -r requirements.txt` | ✅ 必须 | 含 `dashscope`, `langgraph`, `pydantic-settings` |
| `.env` 已配置（`cp .env.example .env`） | ✅ 必须 | 连接参数使用默认值即可 |
| `.env` 中 `DASHSCOPE_API_KEY` 已配置 | ⚠️ 推荐 | 未配置则自动降级为 Mock 关键词匹配 |
| `mock_data/images/` 下存在测试图片 | ✅ 必须 | 4 张图片随项目分发 |
| **生产模式**: Docker 容器已启动 + `NEO4J_USE_MOCK=false` | 可选 | `docker compose up -d` 一键启动 Neo4j+Redis+Milvus |
| **生产模式**: 数据已导入 | 可选 | `python run_real_test.py --init-data-only` |

---

## 4 张测试图片速查

| # | 图片文件 | 告警 ID | 场景 | 隐患类型 |
|---|----------|---------|------|----------|
| 1 | [`inj_mold_leak.jpg`](mock_data/images/inj_mold_leak.jpg) | ALT-20240520-001 | SMT-A车间-3号注塑机 | 液压油泄漏 |
| 2 | [`blocked_fire_exit.jpg`](mock_data/images/blocked_fire_exit.jpg) | ALT-20240520-002 | 组装线-B区-配电箱 | 消防通道堵塞 |
| 3 | [`welding_no_helmet.jpg`](mock_data/images/welding_no_helmet.jpg) | ALT-20240520-003 | 焊接车间-C区-2号工位 | 未戴安全帽 |
| 4 | [`chemical_smoke.jpg`](mock_data/images/chemical_smoke.jpg) | ALT-20240520-004 | 化学品仓库-D区 | 化学品烟雾 |

---

## 命令行用法

### 基本语法

```bash
python run_real_test.py [告警序号] [选项]
```

### 参数说明

| 参数 | 简写 | 说明 |
|------|------|------|
| `alert_index` | *(位置参数)* | 告警序号 (1-4)，对应上表。默认 1 |
| `--image PATH` | `-i PATH` | 直接指定图片路径，覆盖 mock 数据 |
| `--vision-only` | `-v` | 仅测试 Qwen-VL 视觉分析，不跑全链路 |
| `--init-data` | — | 先执行 Neo4j + Milvus 数据导入，再跑全链路（需 Docker） |
| `--init-data-only` | — | 仅执行数据导入，不运行测试 |
| `--quiet` | `-q` | 减少日志输出（仅 WARNING 以上） |

---

## 使用示例

### 示例 1: 全链路 — 使用预设告警

```bash
# 场景 1: 油渍泄漏
python run_real_test.py 1

# 场景 2: 消防通道堵塞
python run_real_test.py 2

# 场景 3: 未戴安全帽
python run_real_test.py 3

# 场景 4: 化学品烟雾
python run_real_test.py 4
```

### 示例 2: 全链路 — 自定义图片

```bash
# 使用本地任意图片
python run_real_test.py --image ./my_test_photo.jpg

# 使用 mock_data 下的绝对路径
python run_real_test.py -i "D:\AI_Project\SafeGuard-AI\mock_data\images\blocked_fire_exit.jpg"
```

### 示例 3: 仅视觉分析

```bash
# 快速验证 DashScope API Key 和 Qwen-VL 是否正常
python run_real_test.py --vision-only

# 仅分析指定图片
python run_real_test.py -v -i ./test.jpg
```

### 示例 4: 静默模式

```bash
# CI/CD 或自动化场景，减少输出噪音
python run_real_test.py 1 --quiet
```

### 示例 5: 数据导入 + 全链路验证

```bash
# 第一步：仅导入数据（首次部署时执行）
python run_real_test.py --init-data-only

# 第二步：导入后运行全链路测试（验证真实 Neo4j/Milvus 数据可用）
python run_real_test.py 1

# 或一步到位：先导入再测试
python run_real_test.py --init-data 1
```

> **注意**: `--init-data` 要求 `.env` 中 `NEO4J_USE_MOCK=false` 且 Docker 容器已启动 (`docker compose up -d`)。

---

## 预期输出

### 第一阶段：配置摘要

启动后首先打印环境信息，确认配置是否正确：

```
══════════════════════════════════════════════════════════════════════
  ⚙️  SafeGuard-AI 全链路测试
══════════════════════════════════════════════════════════════════════
  启动时间:   2026-06-11 14:30:00
  项目根目录: D:\AI_Project\SafeGuard-AI
  LLM:        https://api.deepseek.com / deepseek-chat
  Neo4j:      bolt://localhost:17687 (mock=false)
  Redis:      redis://localhost:6379/0
  Milvus:     localhost:19530
  DashScope:  key=***a1b2

  📋 使用告警 #1: ALT-20240520-001
     位置:   SMT-A车间-3号注塑机
     描述:   检测到3号注塑机液压管路下方有明显油渍...
     图片:   /mock_data/images/inj_mold_leak.jpg

  ✅ 本地图片: D:\AI_Project\SafeGuard-AI\mock_data\images\inj_mold_leak.jpg (568000 bytes)

  🎯 模式: 全链路 (Qwen-VL → 路由 → GraphRAG → 记忆 → 工单 → MCP)
```

> **关键检查点**: 确认 `DASHSCOPE_API_KEY` 显示为 `***xxxx`（已配置）。若显示 `未配置`，Qwen-VL 将降级为 Mock。

---

### 第二阶段：视觉分析

Qwen-VL 真实调用（~3-5s），日志含彩色标记：

```
──────────────────────────────────────────────────────────────────────
  🔍 阶段 1: Qwen-VL 视觉分析
──────────────────────────────────────────────────────────────────────

  ⏱  Qwen-VL 耗时: 3.45s

  📊 分析结果:
     risk_level:  high
     findings:    2 个

     --- Finding #1 ---
     type:        oil_leak
     description: 地面大面积液压油泄漏，约2平方米...
     confidence:  0.92
     bbox:        [120, 340, 580, 620]

     --- Finding #2 ---
     type:        slip_hazard
     description: 人员行走区域湿滑，未设置警示标识
     confidence:  0.88
```

> **关键检查点**: `⏱ Qwen-VL 耗时` 应在 2-8s 内；`confidence` 通常在 0.75-0.98。

---

### 第三阶段：最终汇总（全链路模式）

```
══════════════════════════════════════════════════════════════════════
  📋 全链路结果汇总
══════════════════════════════════════════════════════════════════════
  ⏱  总耗时: 5.23s

  🔍 [检测节点] 视觉分析结果:
     risk_level:        high
     findings 数量:     2
       [0] type=oil_leak, confidence=0.92, desc=地面大面积液压油泄漏...
       [1] type=slip_hazard, confidence=0.88, desc=人员行走区域湿滑...

  🧭 [路由节点] 决策:
     next_action:       urgent
     need_cloud:        False

  📚 [GraphRAG] 知识检索上下文 (621 字符):
     ## 1. 检索到的隐患 (Hazard)
     【液压油泄漏】⚠️ 高风险 — 法规依据: GB 50016-2014...
     ## 2. 关联的标准操作程序 (SOP)
     【化学品泄漏与火灾应急处置SOP】...

  🧠 [记忆系统] 专家经验与反思 (156 字符):
     【历史经验参考 - 请结合以下经验优化处置建议】

     📌 专家经验 #1 (相关度: 0.75)
     立即设置警戒线并启动应急响应流程...

     📌 反思教训 #2 (相关度: 0.60)
     ❌ 历史错误: 未及时更换老化密封圈导致二次泄漏
     ✅ 人工修正: 更换密封圈并建立月度点检制度
     📖 学到的规则: 液压管路泄漏必须检查密封圈状态

  📝 [工单生成] 最终工单:
     title:       【紧急】油渍泄漏 - 生产区A
     description: 检测到液压油泄漏，面积约2平方米...
     priority:    P0
     assignee:    安全员-王工
     hazard_type: oil_leak
     source_node: EDGE-NODE-C03

  📤 [MCP 推送] 状态:
     ticket_status:     sent
     retry_count:       0

  💬 [消息日志] 共 8 条:
     [0] (system) 开始分析告警 ALT-20240520-001...
     [1] (ai) 视觉分析完成，检测到 2 处隐患，风险等级: high
     [2] (system) 路由决策: urgent，无需云端二次分析
     [3] (system) GraphRAG 知识检索完成，注入上下文...
     [4] (system) 专家经验检索完成，命中 2 条记忆
     [5] (ai) 工单已生成: 【紧急】油渍泄漏...
     [6] (system) 工单推送成功，ticket_id: WO-20240611-001
     [7] (ai) 处置建议: 建议立即停机并设置警戒线，启动应急响应...

══════════════════════════════════════════════════════════════════════
  🏁 最终判定
══════════════════════════════════════════════════════════════════════
  ✅ 高风险隐患工单已成功推送至 EHS 系统。
```

---

## 成功标志速查

| 标志 | 含义 |
|------|------|
| `⏱ Qwen-VL 耗时: N.NNs` | Qwen-VL 真实 API 调用成功（非 Mock 降级） |
| `📚 [GraphRAG] 知识检索上下文 (N 字符)` | N > 20 表示 Neo4j/Milvus 检索命中 |
| `🧠 [记忆系统] 专家经验与反思 (N 字符)` | N > 0 表示长期记忆检索命中 |
| `📝 [工单生成] 最终工单:` | 工单生成节点正常执行 |
| `ticket_status: sent` | MCP 推送成功（200 OK） |
| `✅ 高风险隐患工单已成功推送` | 全链路通过 |

---

## 数据导入验证

### 为什么要导入数据？

Mock 模式下，Neo4j 和 Milvus 使用内存中的模拟数据。导入真实数据后：
- **GraphRAG** 能检索到真实的法规条款（如 GB 50016-2014）和 SOP 编号
- **记忆系统** 能通过向量相似度找到最匹配的专家经验，而非简单的关键词重叠
- **API 返回的 `graph_context` 和 `memory_context`** 将包含真实数据库中的内容

### 验证前准备

```bash
# 1. 一键启动所有 Docker 容器（Neo4j + Redis + Milvus）
docker compose up -d

# 2. 确认所有服务已就绪
docker compose ps
# 预期: 3 个服务均为 healthy

# 3. 确认 .env 配置
# NEO4J_USE_MOCK=false
# DASHSCOPE_API_KEY=sk-your-real-key

# 4. 安装向量化依赖（首次）
pip install pymilvus sentence-transformers
```

### 执行数据导入

```bash
# 方式一: 仅导入（推荐首次部署）
python run_real_test.py --init-data-only
```

**预期输出**：

```
──────────────────────────────────────────────────────────────────────
  🗄️  数据导入: Neo4j 图谱
──────────────────────────────────────────────────────────────────────
  📄 解析到 14 条 Cypher 语句
  ✅ Neo4j 连接成功: bolt://localhost:17687
  🗑️  清空现有图谱数据...
  🔨 执行 14 条语句...
     ✅ 14/14 条执行成功
  📊 验证导入结果:
     Equipment: 4 个节点
     Hazard: 4 个节点
     Regulation: 3 个节点
     SOP: 2 个节点
     Relationships: 9 条边
  🎉 Neo4j 导入完成: 共 13 个节点，9 条关系
  ✅ Neo4j: 共导入 13 个节点，9 条关系

──────────────────────────────────────────────────────────────────────
  🧬 数据导入: Milvus 向量库
──────────────────────────────────────────────────────────────────────
  📝 提取到 2 条待向量化条目
  🤖 加载 BGE-M3 Embedding 模型...
  🔢 向量化 2 条文本...
     ✅ 完成，维度: 1024
  ✅ Milvus 连接成功: localhost:19530
  🆕 Collection 已创建: expert_memory
  🎉 Milvus 导入完成: 2 条 → expert_memory (总行数: 2)
  ✅ Milvus: 2 条向量 → expert_memory
     总行数: 2, 维度: 1024
```

### 验证导入结果

```bash
# 导入后运行全链路测试
python run_real_test.py 1
```

**关键验证点**：

| 检查项 | Mock 模式 | 真实模式（导入后） |
|--------|-----------|-------------------|
| `Neo4j: (mock=...)` | `mock=true` | `mock=false` |
| `📚 GraphRAG 上下文` | ~20-200 字符（内存解析） | 含真实 Cypher 查询结果 |
| `🧠 记忆系统` | 关键词重叠度 | Milvus IP 向量相似度 |
| `[Memory] 日志` | `Mock（关键词匹配）` | `Milvus 向量检索已就绪` |
| `🧠 相似度分数` | 0-1 重叠度 | 0-1 IP 内积 |

### 使用独立脚本导入

也可以用独立脚本分别执行导入：

```bash
# 仅导入 Neo4j
python scripts/init_neo4j.py --yes

# 仅导入 Milvus
python scripts/embed_to_milvus.py --force
```

---

## 常见问题

### Q: 看到 "Mock" 字样正常吗？

若日志中出现 `(Mock 降级)` 或 `_mock_analysis()`，表示 Qwen-VL/Neo4j 未配置真实后端。这不影响工作流通畅性，但结果精度不如真实 AI。若要获得真实分析，请确保：
- `.env` 中 `DASHSCOPE_API_KEY` 已配置
- Neo4j Docker 已启动 + `.env` 中 `NEO4J_USE_MOCK=false`

### Q: GraphRAG 上下文为 0 字符？

确认 `mock_data/init_graph.cypher` 和 `mock_data/mock_memory.json` 文件存在。若使用真实 Neo4j，确认已执行 Cypher 初始化脚本（参见 [DEPLOYMENT.md](DEPLOYMENT.md#34-neo4j-初始化数据可选生产真实验证时执行)）。

### Q: 如何只看某个环节？

```bash
# 只看视觉分析
python run_real_test.py -v

# 减少日志噪音
python run_real_test.py 1 -q
```

### Q: 在 CI/CD 中如何判断成功？

脚本退出码为 0 表示成功。可配合 grep：

```bash
python run_real_test.py 1 -q 2>&1 | grep -q "✅ 高风险隐患工单已成功推送"
if [ $? -eq 0 ]; then
    echo "全链路验证通过"
else
    echo "验证失败"
    exit 1
fi
```

---

## 相关文档

| 文档 | 说明 |
|------|------|
| [DEPLOYMENT.md](DEPLOYMENT.md) | 完整部署指南（Docker、.env、API 启动） |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 架构决策记录（ADR-1~13） |
| [PROGRESS.md](PROGRESS.md) | 开发进度与文件树 |
