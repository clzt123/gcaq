"""
Milvus 专家经验向量化与导入脚本。

读取 mock_data/mock_memory.json 中的专家经验与反思记忆文本，
使用 BGE-M3 (或 sentence-transformers) 模型生成 Embedding，
写入 Milvus Collection。

使用方式:
    cd SafeGuard-AI
    python scripts/embed_to_milvus.py                     # 默认: mock_memory.json → 写入 Milvus
    python scripts/embed_to_milvus.py --input custom.json # 指定自定义 JSON
    python scripts/embed_to_milvus.py --dry-run           # 仅预览 Embedding，不写入
    python scripts/embed_to_milvus.py --force             # 删除已有 Collection 后重建

前置条件:
    1. .env 中 MILVUS_HOST/MILVUS_PORT 已配置
    2. Milvus Docker 已启动 (docker compose up -d milvus)
    3. pip install pymilvus sentence-transformers
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# 将项目根目录加入 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import get_settings
from app.utils import get_mock_path

logger = logging.getLogger(__name__)

# =========================
# 常量
# =========================

# 默认 Collection Schema 字段名
FIELD_ID = "id"
FIELD_TEXT = "text"
FIELD_VECTOR = "vector"
FIELD_SOURCE = "source"        # "expert" | "reflection"
FIELD_MEMORY_ID = "memory_id"

# Memory 专用 Collection 名（与 config 中 knowledge_chunks 区分）
DEFAULT_MEMORY_COLLECTION = "expert_memory"


# =========================
# 日志配置
# =========================

def setup_logging() -> None:
    """配置带颜色的控制台日志。"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)

    class _ColoredFormatter(logging.Formatter):
        COLORS = {
            "DEBUG": "\033[36m",
            "INFO": "\033[32m",
            "WARNING": "\033[33m",
            "ERROR": "\033[31m",
        }
        RESET = "\033[0m"

        def format(self, record: logging.LogRecord) -> str:
            msg = super().format(record)
            color = self.COLORS.get(record.levelname, "")
            return f"{color}{msg}{self.RESET}" if color else msg

    handler.setFormatter(_ColoredFormatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


# =========================
# Embedding 模型加载
# =========================

_embedding_model: Any = None


def get_embedding_model(model_name: str = "BAAI/bge-m3"):
    """
    懒加载 sentence-transformers 模型（全局缓存）。

    优先尝试 BGE-M3，不可用时降级为 all-MiniLM-L6-v2。

    Args:
        model_name: HuggingFace 模型名称

    Returns:
        sentence-transformers SentenceTransformer 实例
    """
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model

    try:
        from sentence_transformers import SentenceTransformer
        logger.info(f"🤖 加载 Embedding 模型: {model_name} ...")
        _embedding_model = SentenceTransformer(model_name)
        logger.info(f"   ✅ 加载成功，向量维度: {_embedding_model.get_sentence_embedding_dimension()}")
        return _embedding_model
    except Exception as e:
        logger.warning(f"   ⚠️  {model_name} 加载失败: {e}")
        # 降级为轻量模型
        fallback = "all-MiniLM-L6-v2"
        logger.info(f"   🔄 降级为: {fallback}")
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer(fallback)
        logger.info(f"   ✅ 加载成功，向量维度: {_embedding_model.get_sentence_embedding_dimension()}")
        return _embedding_model


def embed_texts(texts: List[str], model_name: str = "BAAI/bge-m3") -> List[List[float]]:
    """
    批量将文本转为向量嵌入。

    Args:
        texts: 文本列表
        model_name: 模型名称

    Returns:
        向量列表 (每项为 float 列表)
    """
    model = get_embedding_model(model_name)
    logger.info(f"🔢 正在向量化 {len(texts)} 条文本...")
    t0 = time.time()

    # sentence-transformers 默认启用 normalize_embeddings
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    elapsed = time.time() - t0
    logger.info(f"   ✅ 完成，耗时 {elapsed:.2f}s ({len(texts)/elapsed:.1f} 条/秒)")

    # 转为 Python list[list[float]]
    return embeddings.tolist()


# =========================
# JSON 数据提取
# =========================

def extract_memory_texts(memory_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    从 mock_memory.json 中提取所有待向量化的文本条目。

    对每条记录提取用于 Embedding 的合并文本（scenario + expert_solution 拼接
    或 ai_wrong_answer + human_correction 拼接）。

    Args:
        memory_data: mock_memory.json 的解析结果

    Returns:
        条目列表，每项含:
            - source: "expert" | "reflection"
            - memory_id: 原始 ID
            - embed_text: 用于向量化的合并文本
            - metadata: 原始完整数据
    """
    items: List[Dict[str, Any]] = []

    # 专家经验
    for mem in memory_data.get("long_term_expert_memory", []):
        scenario = mem.get("scenario", "")
        solution = mem.get("expert_solution", "")
        embed_text = f"{scenario}\n{solution}"
        items.append({
            "source": "expert",
            "memory_id": mem.get("memory_id", ""),
            "embed_text": embed_text,
            "metadata": {
                "scenario": scenario,
                "expert_solution": solution,
            },
        })

    # 反思记忆
    for ref in memory_data.get("reflection_memory", []):
        wrong = ref.get("ai_wrong_answer", "")
        correction = ref.get("human_correction", "")
        rule = ref.get("learned_rule", "")
        embed_text = f"❌ 历史错误: {wrong}\n✅ 人工修正: {correction}\n📖 学到的规则: {rule}"
        items.append({
            "source": "reflection",
            "memory_id": ref.get("reflection_id", ""),
            "embed_text": embed_text,
            "metadata": {
                "ai_wrong_answer": wrong,
                "human_correction": correction,
                "learned_rule": rule,
            },
        })

    return items


# =========================
# Milvus Collection 管理
# =========================

def ensure_collection(
    client: Any,
    collection_name: str,
    vector_dim: int,
    force_recreate: bool = False,
) -> None:
    """
    确保 Milvus Collection 存在，不存在则创建。

    使用 MilvusClient (PyMilvus 3.x) API。

    Args:
        client: MilvusClient 实例
        collection_name: Collection 名称
        vector_dim: 向量维度
        force_recreate: True 时先删后建
    """
    from pymilvus import DataType

    # 检查 Collection 是否存在
    if client.has_collection(collection_name):
        if force_recreate:
            logger.info(f"🗑️  删除已有 Collection: {collection_name}")
            client.drop_collection(collection_name)
        else:
            logger.info(f"📦 Collection 已存在: {collection_name}")
            client.load_collection(collection_name)
            stats = client.get_collection_stats(collection_name)
            logger.info(f"   ✅ 已加载，当前行数: {stats.get('row_count', 0)}")
            return

    # 创建 Schema (使用 MilvusClient.create_collection)
    # 注意: MilvusClient.create_collection 接受简化的 schema 格式
    schema = client.create_schema(
        auto_id=True,
        enable_dynamic_field=False,
    )
    schema.add_field(field_name=FIELD_ID, datatype=DataType.INT64, is_primary=True)
    schema.add_field(field_name=FIELD_TEXT, datatype=DataType.VARCHAR, max_length=4096)
    schema.add_field(field_name=FIELD_VECTOR, datatype=DataType.FLOAT_VECTOR, dim=vector_dim)
    schema.add_field(field_name=FIELD_SOURCE, datatype=DataType.VARCHAR, max_length=32)
    schema.add_field(field_name=FIELD_MEMORY_ID, datatype=DataType.VARCHAR, max_length=128)

    # 创建索引参数
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name=FIELD_VECTOR,
        metric_type="IP",
        index_type="IVF_FLAT",
        params={"nlist": 16},
    )

    client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params,
        description="SafeGuard-AI 专家经验记忆",
    )
    logger.info(f"🆕 Collection 已创建: {collection_name} (dim={vector_dim}, index=IVF_FLAT)")

    client.load_collection(collection_name)
    logger.info(f"   ✅ Collection 已加载到内存。")


def insert_to_milvus(
    client: Any,
    collection_name: str,
    items: List[Dict[str, Any]],
    embeddings: List[List[float]],
) -> int:
    """
    将文本和向量批量插入 Milvus Collection。

    使用 MilvusClient (PyMilvus 3.x) API。

    Args:
        client: MilvusClient 实例
        collection_name: Collection 名称
        items: extract_memory_texts() 返回的条目列表
        embeddings: embed_texts() 返回的向量列表

    Returns:
        插入行数
    """
    if len(items) != len(embeddings):
        raise ValueError(
            f"条目数与向量数不匹配: {len(items)} vs {len(embeddings)}"
        )

    # 构建插入数据
    data = []
    for i, (item, emb) in enumerate(zip(items, embeddings)):
        data.append({
            FIELD_TEXT: item["embed_text"],
            FIELD_VECTOR: emb,
            FIELD_SOURCE: item["source"],
            FIELD_MEMORY_ID: item["memory_id"],
        })

    t0 = time.time()
    result = client.insert(collection_name=collection_name, data=data)
    elapsed = time.time() - t0

    # MilvusClient.insert 返回 insert_count 或 {"insert_count": n}
    if isinstance(result, dict):
        inserted = result.get("insert_count", len(data))
    else:
        inserted = result

    stats = client.get_collection_stats(collection_name)
    row_count = stats.get("row_count", 0)
    logger.info(
        f"💾 已插入 {inserted} 行 → 耗时 {elapsed:.2f}s "
        f"(Collection 总行数: {row_count})"
    )
    return inserted


# =========================
# Dry-run 预览
# =========================

def dry_run_preview(items: List[Dict[str, Any]], embeddings: List[List[float]]) -> None:
    """打印 Dry-run 预览信息。"""
    print(f"\n{'='*60}")
    print(f"  Dry-run 预览")
    print(f"{'='*60}")
    print(f"  条目总数:    {len(items)}")
    print(f"  向量维度:    {len(embeddings[0]) if embeddings else 'N/A'}")
    print()

    for i, (item, emb) in enumerate(zip(items, embeddings)):
        print(f"--- 条目 {i+1} ---")
        print(f"  来源:       {item['source']}")
        print(f"  memory_id:  {item['memory_id']}")
        print(f"  文本(前120): {item['embed_text'][:120]}...")
        print(f"  向量(前5维): {emb[:5]}")
        print()

    print(f"{'='*60}")
    print(f"  ✅ Dry-run 完成（未连接 Milvus）。")


# =========================
# 命令行入口
# =========================

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="SafeGuard-AI Milvus 专家经验向量化导入",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python scripts/embed_to_milvus.py                     # 默认模式
    python scripts/embed_to_milvus.py --dry-run           # 仅预览
    python scripts/embed_to_milvus.py --force             # 重建 Collection
    python scripts/embed_to_milvus.py --input custom.json
        """,
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help="自定义 JSON 文件路径（默认: mock_data/mock_memory.json）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅解析 JSON、生成 Embedding 并打印预览，不连接 Milvus",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="删除已有 Collection 后重建",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default="BAAI/bge-m3",
        help="HuggingFace Embedding 模型名称（默认: BAAI/bge-m3）",
    )
    parser.add_argument(
        "--collection", "-c",
        type=str,
        default=DEFAULT_MEMORY_COLLECTION,
        help=f"Milvus Collection 名称（默认: {DEFAULT_MEMORY_COLLECTION}）",
    )
    args = parser.parse_args()

    setup_logging()

    # ---- 加载配置 ----
    settings = get_settings()
    milvus_conf = settings.milvus

    # ---- 确定输入文件 ----
    if args.input:
        input_file = Path(args.input)
    else:
        input_file = get_mock_path("mock_memory.json")

    if not input_file.exists():
        logger.error(f"❌ 输入文件不存在: {input_file}")
        sys.exit(1)

    logger.info(f"📂 输入文件: {input_file}")

    # ---- 读取 JSON ----
    with open(input_file, "r", encoding="utf-8") as f:
        memory_data = json.load(f)

    items = extract_memory_texts(memory_data)
    logger.info(f"📝 提取到 {len(items)} 条待向量化条目:")
    for item in items:
        logger.info(f"   [{item['source']}] {item['memory_id']} — {item['embed_text'][:60]}...")

    if not items:
        logger.warning("⚠️  无数据可导入。")
        return

    # ---- 生成 Embedding ----
    # Dry-run 模式下用较轻量模型加速预览
    preview_model = "all-MiniLM-L6-v2" if args.dry_run else args.model
    embeddings = embed_texts(
        [item["embed_text"] for item in items],
        model_name=preview_model,
    )

    # ---- Dry-run ----
    if args.dry_run:
        dry_run_preview(items, embeddings)
        return

    # ---- 连接 Milvus 并写入 ----
    # 使用实际 embedding 维度（而非 config 中的默认值）
    actual_dim = len(embeddings[0])
    logger.info(f"📐 实际向量维度: {actual_dim} (config 默认: {milvus_conf.vector_dim})")

    # 建立 MilvusClient 连接
    from pymilvus import MilvusClient
    client = MilvusClient(
        uri=f"http://{milvus_conf.host}:{milvus_conf.port}",
        timeout=30,
    )
    logger.info(f"✅ Milvus 连接成功: {milvus_conf.host}:{milvus_conf.port}")

    ensure_collection(
        client=client,
        collection_name=args.collection,
        vector_dim=actual_dim,
        force_recreate=args.force,
    )

    inserted = insert_to_milvus(client, args.collection, items, embeddings)

    stats = client.get_collection_stats(args.collection)
    row_count = stats.get("row_count", 0)

    print(f"\n{'='*60}")
    print(f"🎉 向量化导入完成！")
    print(f"   Collection: {args.collection}")
    print(f"   导入行数:   {inserted}")
    print(f"   总行数:     {row_count}")
    print(f"   向量维度:   {actual_dim}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
