"""
SafeGuard-AI 全链路真实环境测试脚本。

验证完整管道: 真实图片 → Qwen-VL 视觉分析 → GraphRAG 检索 → 工单生成 → MCP 推送。

使用方式:
    cd SafeGuard-AI
    python run_real_test.py              # 使用第一条 mock 告警
    python run_real_test.py 1            # 指定第 N 条告警 (1-4)
    python run_real_test.py --image path/to/image.jpg   # 直接指定图片
    python run_real_test.py --init-data  # 先导入 Neo4j/Milvus 数据，再跑全链路

前置条件:
    1. .env 中 DASHSCOPE_API_KEY 已配置真实 Key（不配置则自动降级 Mock）
    2. (可选) docker compose up -d 启动基础设施 + .env 中 NEO4J_USE_MOCK=false
    3. (可选) pip install dashscope pymilvus sentence-transformers
    4. 首次部署: python run_real_test.py --init-data-only 执行数据导入
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# ---- 强制 UTF-8 输出（Windows GBK 终端兼容） ----
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# =========================
# 路径初始化（确保能从项目根目录运行）
# =========================

_PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import get_settings, setup_langsmith
from app.utils import get_mock_path, get_project_root

# LangSmith 可观测性：必须在 LangChain/LangGraph 导入之前初始化
# （后续 analyze_image_with_qwen / run_hazard_workflow 会导入 langgraph）
setup_langsmith()


# =========================
# 彩色日志格式化器
# =========================

class ColorFormatter(logging.Formatter):
    """带 ANSI 颜色的日志格式化器，突出 LLM 思考过程。"""

    COLORS = {
        "DEBUG":    "\033[36m",  # 青色
        "INFO":     "\033[32m",  # 绿色
        "WARNING":  "\033[33m",  # 黄色
        "ERROR":    "\033[31m",  # 红色
        "CRITICAL": "\033[35m",  # 紫色
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        color = self.COLORS.get(record.levelname, "")
        if record.levelno >= logging.WARNING:
            return f"{self.BOLD}{color}{msg}{self.RESET}"
        return f"{color}{msg}{self.RESET}" if color else msg


def setup_test_logging(verbose: bool = True) -> None:
    """
    配置测试专用日志系统：DEBUG 级别 + 彩色输出。

    Args:
        verbose: True 时所有关键模块设为 DEBUG，False 时仅 INFO
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG if verbose else logging.INFO)

    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    datefmt = "%H:%M:%S"
    handler.setFormatter(ColorFormatter(fmt, datefmt))
    root.addHandler(handler)

    # 关键模块统一设为 DEBUG
    target_modules = [
        "app.core.vision",
        "app.core.graph",
        "app.core.rag",
        "app.core.memory",
        "app.tools",
        "app.api",
        "app.config",
    ]
    for mod in target_modules:
        logging.getLogger(mod).setLevel(logging.DEBUG if verbose else logging.INFO)

    # 抑制第三方库噪音
    for noisy in ["urllib3", "httpx", "httpcore", "neo4j", "asyncio"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


# =========================
# 工具函数
# =========================

def resolve_image_path(image_source: str) -> Optional[Path]:
    """
    将 mock_alerts.json 中的 image_url 解析为本地绝对路径。

    支持格式:
        - /mock_data/images/xxx.jpg  →  项目根/mock_data/images/xxx.jpg
        - mock_data/images/xxx.jpg   →  同上
        - 绝对路径                       →  直接使用
        - http(s)://...                 →  返回 None（非本地文件）

    Args:
        image_source: 图片来源字符串

    Returns:
        本地文件 Path，或 None（HTTP URL / 文件不存在）
    """
    if image_source.startswith(("http://", "https://", "data:")):
        return None

    # 去掉前导 /
    cleaned = image_source.lstrip("/")
    local_path = get_project_root() / cleaned

    if local_path.exists():
        return local_path

    # 尝试 mock_data 下模糊搜索
    mock_dir = get_project_root() / "mock_data"
    filename = Path(image_source).name
    for f in mock_dir.rglob(filename):
        return f

    return None


def print_separator(title: str, char: str = "=", width: int = 72) -> None:
    """打印格式化分隔线。"""
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}\n")


def print_dict(data: Dict[str, Any], indent: int = 2) -> None:
    """美化打印字典，长字符串自动折行。"""
    for key, value in data.items():
        prefix = " " * indent
        if isinstance(value, str) and len(value) > 120:
            print(f"{prefix}{key}:")
            print(f"{prefix}  {value[:200]}...")
        elif isinstance(value, list):
            print(f"{prefix}{key}: [{len(value)} 项]")
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    print(f"{prefix}  [{i}]:")
                    print_dict(item, indent + 4)
                else:
                    print(f"{prefix}  [{i}]: {str(item)[:100]}")
        elif isinstance(value, dict):
            print(f"{prefix}{key}:")
            print_dict(value, indent + 2)
        else:
            print(f"{prefix}{key}: {value}")


# =========================
# 核心测试逻辑
# =========================

async def test_vision_analyzer_only(image_source: str) -> Dict[str, Any]:
    """
    仅测试 Qwen-VL 视觉分析（不跑全链路）。

    用于快速验证 DashScope API Key 和图片输入是否正常。

    Args:
        image_source: 图片路径或 URL

    Returns:
        detection_result 字典
    """
    from app.core.vision.analyzer import analyze_image_with_qwen

    print_separator("🔍 阶段 1: Qwen-VL 视觉分析", "─")

    t0 = datetime.now()
    result = await analyze_image_with_qwen(image_source)
    elapsed = (datetime.now() - t0).total_seconds()

    print(f"\n  ⏱  Qwen-VL 耗时: {elapsed:.2f}s")
    print(f"\n  📊 分析结果:")
    print(f"     risk_level:  {result.get('risk_level', '?')}")
    print(f"     findings:    {len(result.get('findings', []))} 个")

    for i, f in enumerate(result.get("findings", [])):
        print(f"\n     --- Finding #{i+1} ---")
        print(f"     type:        {f.get('type', '?')}")
        print(f"     description: {f.get('description', '?')}")
        print(f"     confidence:  {f.get('confidence', '?')}")
        bbox = f.get("bbox", [])
        if bbox:
            print(f"     bbox:        {bbox}")

    error = result.get("error", "")
    if error:
        print(f"\n  ⚠️  错误: {error}")

    raw = result.get("raw_response", "")
    if raw and "Mock" not in raw:
        print(f"\n  📝 原始响应 (前 500 字符):")
        print(f"     {raw[:500]}")

    return result


async def test_full_workflow(
    image_source: str,
    alert_id: str = "",
    area_type: str = "",
    edge_node_id: str = "",
) -> Dict[str, Any]:
    """
    运行完整的隐患研判工作流。

    管线: detection → supervisor → GraphRAG → Memory → TicketGen → MCP Push

    Args:
        image_source: 图片路径
        alert_id: 告警 ID
        area_type: 区域类型
        edge_node_id: 边缘节点 ID

    Returns:
        最终 HazardState 字典
    """
    from app.core.graph.workflow import run_hazard_workflow

    print_separator("🚀 全链路工作流启动", "═")

    print(f"  📋 输入参数:")
    print(f"     alert_id:    {alert_id or '(自动生成)'}")
    print(f"     image:       {image_source}")
    print(f"     area_type:   {area_type or '(未指定)'}")
    print(f"     edge_node:   {edge_node_id or '(未指定)'}")
    print()

    t0 = datetime.now()
    final_state = await run_hazard_workflow(
        current_image=image_source,
        alert_id=alert_id,
        edge_node_id=edge_node_id,
        area_type=area_type,
    )
    total_elapsed = (datetime.now() - t0).total_seconds()

    return final_state, total_elapsed


def print_workflow_result(final_state: Dict[str, Any], total_elapsed: float) -> None:
    """格式化打印全链路工作流结果。"""

    print_separator("📋 全链路结果汇总", "═")

    print(f"  ⏱  总耗时: {total_elapsed:.2f}s")
    print()

    # --- 视觉分析结果 ---
    detection = final_state.get("detection_result", {})
    print(f"  🔍 [检测节点] 视觉分析结果:")
    print(f"     risk_level:        {detection.get('risk_level', '?')}")
    findings = detection.get("findings", [])
    print(f"     findings 数量:     {len(findings)}")
    for i, f in enumerate(findings):
        print(f"       [{i}] type={f.get('type')}, confidence={f.get('confidence')}, "
              f"desc={f.get('description', '')[:60]}")
    print()

    # --- 路由决策 ---
    print(f"  🧭 [路由节点] 决策:")
    print(f"     next_action:       {final_state.get('next_action', '?')}")
    print(f"     need_cloud:        {final_state.get('need_cloud_analysis', '?')}")
    print()

    # --- GraphRAG 上下文 ---
    graph_ctx = final_state.get("graph_context", "")
    print(f"  📚 [GraphRAG] 知识检索上下文 ({len(graph_ctx)} 字符):")
    if graph_ctx:
        # 截取前 500 字符展示
        print(f"     {graph_ctx[:500]}")
        if len(graph_ctx) > 500:
            print(f"     ... (截断，共 {len(graph_ctx)} 字符)")
    else:
        print(f"     (无)")
    print()

    # --- 记忆系统上下文 ---
    mem_ctx = final_state.get("memory_context", "")
    print(f"  🧠 [记忆系统] 专家经验与反思 ({len(mem_ctx)} 字符):")
    if mem_ctx:
        print(f"     {mem_ctx[:500]}")
        if len(mem_ctx) > 500:
            print(f"     ... (截断，共 {len(mem_ctx)} 字符)")
    else:
        print(f"     (无)")
    print()

    # --- 工单内容 ---
    ticket = final_state.get("ticket_data", {})
    print(f"  📝 [工单生成] 最终工单:")
    if ticket:
        print(f"     title:       {ticket.get('title', '?')}")
        print(f"     description: {ticket.get('description', '?')[:200]}")
        print(f"     priority:    {ticket.get('priority', '?')}")
        print(f"     assignee:    {ticket.get('assignee', '(待分配)')}")
        print(f"     hazard_type: {ticket.get('hazard_type', '?')}")
        print(f"     source_node: {ticket.get('source_node', '?')}")
    else:
        print(f"     (工单未生成)")
    print()

    # --- 推送状态 ---
    print(f"  📤 [MCP 推送] 状态:")
    print(f"     ticket_status:     {final_state.get('ticket_status', '?')}")
    print(f"     retry_count:       {final_state.get('retry_count', 0)}")
    print()

    # --- 流程消息日志 ---
    messages = final_state.get("messages", [])
    print(f"  💬 [消息日志] 共 {len(messages)} 条:")
    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")[:120]
        print(f"     [{i}] ({role}) {content}")
    print()

    # --- 最终判定 ---
    risk = detection.get("risk_level", "none")
    status = final_state.get("ticket_status", "")
    print_separator("🏁 最终判定", "═")
    if risk == "high" and status == "sent":
        print("  ✅ 高风险隐患工单已成功推送至 EHS 系统。")
    elif risk == "medium" and status == "sent":
        print("  ✅ 中风险隐患工单已成功推送，等待责任人处理。")
    elif risk in ("low", "none"):
        print("  ℹ️  低风险/无隐患，仅记录日志，未生成工单。")
    elif status == "failed":
        print("  ⚠️  工单生成或推送失败，需人工介入。")
    else:
        print(f"  ℹ️  流程结束: risk={risk}, status={status}")


# =========================
# 数据导入辅助函数
# =========================


async def _init_data_neo4j(settings: Any, password: str) -> Dict[str, Any]:
    """
    将 init_graph.cypher 导入真实 Neo4j 实例。

    流程: 连接 → 清空 → 逐条执行 Cypher → 统计验证

    Args:
        settings: Settings 单例
        password: Neo4j 密码

    Returns:
        {"total_nodes": int, "total_relationships": int, "success": int, "total": int}
    """
    from neo4j import AsyncGraphDatabase

    cypher_file = get_mock_path("init_graph.cypher")
    if not cypher_file.exists():
        raise FileNotFoundError(f"Cypher 文件不存在: {cypher_file}")

    cypher_text = cypher_file.read_text(encoding="utf-8")
    statements: list[str] = []

    # 先按分号拆分
    semi_parts = cypher_text.split(";")
    for part in semi_parts:
        part = part.strip()
        if not part:
            continue
        # 过滤注释行，保留非空非注释行
        lines = [l.strip() for l in part.split("\n")
                 if l.strip() and not l.strip().startswith("//")]
        if lines:
            statements.append(" ".join(lines))

    # 如果分号拆分无结果（文件无分号），则按空行分隔
    if not statements:
        blocks = cypher_text.split("\n\n")
        for block in blocks:
            lines = [l.strip() for l in block.split("\n")
                     if l.strip() and not l.strip().startswith("//")]
            if lines:
                statements.append(" ".join(lines))

    neo_logger = logging.getLogger("run_real_test.neo4j")
    neo_logger.info(f"📄 解析到 {len(statements)} 条 Cypher 语句")

    driver = AsyncGraphDatabase.driver(
        settings.neo4j.uri,
        auth=(settings.neo4j.user, password),
    )

    try:
        await driver.verify_connectivity()
        neo_logger.info(f"✅ Neo4j 连接成功: {settings.neo4j.uri}")

        async with driver.session(database=settings.neo4j.database) as session:
            neo_logger.info("🗑️  清空现有图谱数据...")
            await session.run("MATCH (n) DETACH DELETE n")

            neo_logger.info(f"🔨 执行 {len(statements)} 条语句...")
            success_count = 0
            for i, stmt in enumerate(statements, 1):
                try:
                    await session.run(stmt)
                    success_count += 1
                except Exception as e:
                    neo_logger.error(f"   [{i}/{len(statements)}] ❌ 失败: {e}")
                    neo_logger.error(f"   语句: {stmt[:200]}")
                    raise
            neo_logger.info(f"   ✅ {success_count}/{len(statements)} 条执行成功")

            neo_logger.info("📊 验证导入结果:")
            total_nodes = 0
            for label in ["Equipment", "Hazard", "Regulation", "SOP"]:
                result = await session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt")
                record = await result.single()
                count = record["cnt"] if record else 0
                total_nodes += count
                neo_logger.info(f"   {label}: {count} 个节点")

            result = await session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
            record = await result.single()
            rel_count = record["cnt"] if record else 0
            neo_logger.info(f"   Relationships: {rel_count} 条边")

            summary = {
                "total_nodes": total_nodes,
                "total_relationships": rel_count,
                "success": success_count,
                "total": len(statements),
            }
            neo_logger.info(f"🎉 Neo4j 导入完成: 共 {total_nodes} 个节点，{rel_count} 条关系")
            return summary
    finally:
        await driver.close()


async def _init_data_milvus(settings: Any, force: bool = False) -> Dict[str, Any]:
    """
    将 mock_memory.json 专家经验向量化后写入 Milvus。

    流程: 读取 JSON → BGE-M3 向量化 → 创建/确认 Collection → 插入

    Args:
        settings: Settings 单例
        force: True 时删除已有 Collection 后重建

    Returns:
        {"collection": str, "inserted": int, "total_rows": int, "vector_dim": int}
    """
    import json as _json
    from pymilvus import MilvusClient, DataType

    milvus_logger = logging.getLogger("run_real_test.milvus")

    mem_file = get_mock_path("mock_memory.json")
    if not mem_file.exists():
        raise FileNotFoundError(f"记忆文件不存在: {mem_file}")

    with open(mem_file, "r", encoding="utf-8") as f:
        memory_data = _json.load(f)

    items: list[dict] = []
    for mem in memory_data.get("long_term_expert_memory", []):
        items.append({
            "source": "expert",
            "memory_id": mem.get("memory_id", ""),
            "embed_text": f"{mem.get('scenario', '')}\n{mem.get('expert_solution', '')}",
        })
    for ref in memory_data.get("reflection_memory", []):
        items.append({
            "source": "reflection",
            "memory_id": ref.get("reflection_id", ""),
            "embed_text": (
                f"❌ 历史错误: {ref.get('ai_wrong_answer', '')}\n"
                f"✅ 人工修正: {ref.get('human_correction', '')}\n"
                f"📖 学到的规则: {ref.get('learned_rule', '')}"
            ),
        })
    milvus_logger.info(f"📝 提取到 {len(items)} 条待向量化条目")

    milvus_logger.info("🤖 加载 BGE-M3 Embedding 模型...")
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("BAAI/bge-m3")
    except Exception:
        milvus_logger.warning("   BGE-M3 不可用，降级为 all-MiniLM-L6-v2")
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")

    texts = [item["embed_text"] for item in items]
    milvus_logger.info(f"🔢 向量化 {len(texts)} 条文本...")
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=True)
    actual_dim = embeddings.shape[1]
    milvus_logger.info(f"   ✅ 完成，维度: {actual_dim}")

    collection_name = settings.milvus.memory_collection_name
    client = MilvusClient(
        uri=f"http://{settings.milvus.host}:{settings.milvus.port}",
        timeout=30,
    )
    milvus_logger.info(f"✅ Milvus 连接成功: {settings.milvus.host}:{settings.milvus.port}")

    if client.has_collection(collection_name):
        if force:
            milvus_logger.info(f"🗑️  删除已有 Collection: {collection_name}")
            client.drop_collection(collection_name)
        else:
            milvus_logger.info(f"📦 Collection 已存在，跳过创建: {collection_name}")

    if not client.has_collection(collection_name):
        schema = client.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=4096)
        schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=actual_dim)
        schema.add_field(field_name="source", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="memory_id", datatype=DataType.VARCHAR, max_length=128)

        idx_params = client.prepare_index_params()
        idx_params.add_index(field_name="vector", metric_type="IP", index_type="IVF_FLAT", params={"nlist": 16})
        client.create_collection(collection_name, schema=schema, index_params=idx_params)
        milvus_logger.info(f"🆕 Collection 已创建: {collection_name}")

    client.load_collection(collection_name)

    data = [{
        "text": item["embed_text"],
        "vector": emb.tolist(),
        "source": item["source"],
        "memory_id": item["memory_id"],
    } for item, emb in zip(items, embeddings)]

    result = client.insert(collection_name=collection_name, data=data)
    inserted = result.get("insert_count", len(data)) if isinstance(result, dict) else result

    stats = client.get_collection_stats(collection_name)
    row_count = stats.get("row_count", 0)

    summary = {
        "collection": collection_name,
        "inserted": inserted,
        "total_rows": row_count,
        "vector_dim": actual_dim,
    }
    milvus_logger.info(f"🎉 Milvus 导入完成: {inserted} 条 → {collection_name} (总行数: {row_count})")
    return summary


async def _run_data_import(neo4j_password: str, force_milvus: bool = False) -> None:
    """
    执行完整的 Neo4j + Milvus 数据导入流程。

    Args:
        neo4j_password: Neo4j 数据库密码
        force_milvus: 是否强制重建 Milvus Collection
    """
    settings = get_settings()

    print_separator("🗄️  数据导入: Neo4j 图谱", "─")
    if settings.neo4j.use_mock:
        print("  ⚠️  NEO4J_USE_MOCK=true，跳过 Neo4j 导入。")
        print("     请在 .env 中设置 NEO4J_USE_MOCK=false")
        print("     并确保 Neo4j Docker 已启动。")
    else:
        try:
            neo4j_result = await _init_data_neo4j(settings, neo4j_password)
            print(f"  ✅ Neo4j: 共导入 {neo4j_result['total_nodes']} 个节点，{neo4j_result['total_relationships']} 条关系")
        except Exception as e:
            print(f"  ❌ Neo4j 导入失败: {e}")
            print(f"     请检查 Neo4j 是否已启动: docker compose up -d neo4j")

    print_separator("🧬 数据导入: Milvus 向量库", "─")
    try:
        milvus_result = await _init_data_milvus(settings, force=force_milvus)
        print(f"  ✅ Milvus: {milvus_result['inserted']} 条向量 → {milvus_result['collection']}")
        print(f"     总行数: {milvus_result['total_rows']}, 维度: {milvus_result['vector_dim']}")
    except Exception as e:
        print(f"  ❌ Milvus 导入失败: {e}")
        print(f"     请检查 Milvus 是否已启动: docker compose up -d milvus")
        print(f"     请确保已安装: pip install pymilvus sentence-transformers")

    print()


# =========================
# 命令行入口
# =========================

async def main():
    """主入口：解析参数 → (可选)数据导入 → 加载数据 → 执行测试。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="SafeGuard-AI 全链路真实环境测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python run_real_test.py                        # 使用第一条 mock 告警
    python run_real_test.py 2                      # 使用第二条告警 (消防通道堵塞)
    python run_real_test.py --image ./test.jpg     # 指定自定义图片
    python run_real_test.py --vision-only          # 仅测试 Qwen-VL，不跑全链路
    python run_real_test.py --init-data            # 先导入真实数据，再跑全链路
    python run_real_test.py --init-data-only       # 仅执行数据导入 (Neo4j + Milvus)
        """,
    )
    parser.add_argument(
        "alert_index",
        nargs="?",
        type=int,
        default=1,
        help="告警序号 (1-4)，默认 1",
    )
    parser.add_argument(
        "--image", "-i",
        type=str,
        default=None,
        help="直接指定图片路径（覆盖 mock 数据）",
    )
    parser.add_argument(
        "--vision-only", "-v",
        action="store_true",
        help="仅测试 Qwen-VL 视觉分析，不跑全链路",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="减少日志输出（仅 WARNING 以上）",
    )
    parser.add_argument(
        "--init-data",
        action="store_true",
        help="先执行数据导入（Neo4j + Milvus）再运行全链路测试",
    )
    parser.add_argument(
        "--init-data-only",
        action="store_true",
        help="仅执行数据导入（Neo4j + Milvus），不运行测试",
    )
    args = parser.parse_args()

    # ---- 初始化日志 ----
    setup_test_logging(verbose=not args.quiet)
    logger = logging.getLogger("run_real_test")

    # ---- 打印配置摘要 ----
    settings = get_settings()
    print_separator("⚙️  SafeGuard-AI 全链路测试")
    print(f"  启动时间:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  项目根目录: {get_project_root()}")
    print(f"  LLM:        {settings.llm.base_url} / {settings.llm.model_name}")
    print(f"  Neo4j:      {settings.neo4j.uri} (mock={settings.neo4j.use_mock})")
    print(f"  Redis:      {settings.redis.url}")
    print(f"  Milvus:     {settings.milvus.host}:{settings.milvus.port}")
    print(f"  DashScope:  key={'***' + settings.dashscope.api_key[-4:] if settings.dashscope.api_key and len(settings.dashscope.api_key) > 4 else '未配置'}")
    langsmith_key = settings.langsmith.api_key
    print(f"  LangSmith:  {'✅ enabled' if langsmith_key and langsmith_key.strip() else '⚠️  disabled (missing API Key)'}")
    print()

    # ---- 数据导入 (--init-data / --init-data-only) ----
    if args.init_data or args.init_data_only:
        neo4j_password = settings.neo4j.password
        await _run_data_import(neo4j_password, force_milvus=True)
        if args.init_data_only:
            print_separator("✅ 数据导入完成", "═")
            print("  现在可以运行全链路测试验证导入结果:")
            print("    python run_real_test.py")
            print()
            return

    # ---- 确定图片源 ----
    if args.image:
        image_source = args.image
        alert_id = "MANUAL-TEST"
        alert_desc = "手动指定图片"
        location = "手动指定"
        area_type = ""
    else:
        # 加载 mock_alerts.json
        alerts_file = get_mock_path("mock_alerts.json")
        if not alerts_file.exists():
            print(f"\n  ❌ Mock 数据文件不存在: {alerts_file}")
            sys.exit(1)

        with open(alerts_file, "r", encoding="utf-8") as f:
            alerts = json.load(f)

        idx = args.alert_index - 1
        if idx < 0 or idx >= len(alerts):
            print(f"\n  ❌ 告警序号 {args.alert_index} 无效，有效范围: 1-{len(alerts)}")
            sys.exit(1)

        alert = alerts[idx]
        image_source = alert.get("image_url", "")
        alert_id = alert.get("alert_id", "")
        alert_desc = alert.get("description", "")
        location = alert.get("location", "")

        print(f"  📋 使用告警 #{args.alert_index}: {alert_id}")
        print(f"     位置:   {location}")
        print(f"     描述:   {alert_desc}")
        print(f"     图片:   {image_source}")
        print()

    # ---- 解析图片路径 ----
    local_path = resolve_image_path(image_source)
    if local_path:
        image_source = str(local_path)
        print(f"  ✅ 本地图片: {image_source} ({local_path.stat().st_size} bytes)")
    elif image_source.startswith(("http://", "https://")):
        print(f"  🌐 远程图片: {image_source}")
    elif image_source.startswith("data:"):
        print(f"  📦 Base64 data URI (长度: {len(image_source)})")
    else:
        print(f"  ⚠️  图片不可用: {image_source}")
        print(f"      请确认 mock_data/images/ 目录下有对应的测试图片。")
        print(f"      将尝试使用文件路径直接调用 DashScope API...")
        print()

    # ---- 执行测试 ----
    if args.vision_only:
        print(f"\n  🎯 模式: 仅视觉分析\n")
        result = await test_vision_analyzer_only(image_source)

        print_separator("✅ 视觉分析测试完成")
        if result.get("error"):
            print(f"  ⚠️  存在错误: {result['error']}")
            if "Mock" in str(result.get("raw_response", "")):
                print(f"  💡 提示: 当前降级为 Mock。请检查 DASHSCOPE_API_KEY 和网络连接。")
        else:
            print(f"  ✅ Qwen-VL 真实调用成功！")
        return

    # ---- 全链路测试 ----
    print(f"\n  🎯 模式: 全链路 (Qwen-VL → 路由 → GraphRAG → 记忆 → 工单 → MCP)\n")
    print(f"  ⏳ 正在执行全链路工作流，请稍候...\n")

    final_state, elapsed = await test_full_workflow(
        image_source=image_source,
        alert_id=alert_id,
        area_type="production",  # 可从 mock 数据扩展
    )

    print_workflow_result(final_state, elapsed)


if __name__ == "__main__":
    asyncio.run(main())
