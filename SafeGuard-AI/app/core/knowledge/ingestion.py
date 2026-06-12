"""
知识入库流水线

实现技术方案功能 2 — 结构化知识库的文档入库流程：
    1. 文档解析 → 文本分块
    2. BGE-M3 向量化
    3. Milvus knowledge_chunks Collection 创建与填充
    4. 向量检索查询

支持真实 Milvus 连接和 Mock 降级（内存存储）。

使用方式:
    ingestion = KnowledgeIngestion()
    await ingestion.ingest_documents([Path("GB30871-2022.pdf")])
    # 或使用 Mock 数据:
    await ingestion.ingest_all_mock()
    # 检索:
    results = await ingestion.search("动火作业要求")
"""
import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.knowledge.document_parser import DocumentParser, DocumentChunk

logger = logging.getLogger(__name__)

# =========================
# 常量
# =========================

# BGE-M3 向量维度
BGE_M3_DIM = 1024

# Milvus knowledge_chunks Collection Schema
KNOWLEDGE_CHUNKS_SCHEMA = {
    "id": {"type": "VARCHAR", "max_length": 128, "primary": True},
    "text": {"type": "VARCHAR", "max_length": 8192},
    "vector": {"type": "FLOAT_VECTOR", "dim": BGE_M3_DIM},
    "source_doc": {"type": "VARCHAR", "max_length": 256},
    "doc_type": {"type": "VARCHAR", "max_length": 64},
    "clause": {"type": "VARCHAR", "max_length": 128},
    "chunk_index": {"type": "INT64"},
}

# 默认 Collection 名称
DEFAULT_COLLECTION = "knowledge_chunks"

# 默认检索参数
DEFAULT_SEARCH_TOP_K = 5
DEFAULT_NPROBE = 8


# =========================
# 三级 Embedding 降级链
# =========================


class _HashEmbedder:
    """
    三级降级链的最底层：MD5 Hash → 1024d 伪向量。

    当 BGE-M3 和 all-MiniLM-L6-v2 均不可用时作为最终兜底。
    """

    @staticmethod
    def encode(text: str) -> List[float]:
        """将文本转为 1024 维伪向量。"""
        md5_bytes = hashlib.md5(text.encode("utf-8")).digest()

        # 从 16 字节 MD5 生成 1024 维浮点向量
        vector = []
        for i in range(BGE_M3_DIM):
            # 使用两个不同字节组合产生变化
            byte_a = md5_bytes[i % 16]
            byte_b = md5_bytes[(i * 3 + 7) % 16]
            # 组合为 0.0-1.0 的值
            val = (byte_a * 256 + byte_b) / 65535.0
            # 映射到 [-1, 1]
            vector.append(round(val * 2.0 - 1.0, 8))

        return vector


def _load_embedding_model():
    """
    三级降级链加载 Embedding 模型。

    优先级:
        1. BGE-M3 (sentence-transformers, local_files_only)
        2. all-MiniLM-L6-v2 (轻量级替代，384d → pad 到 1024d)
        3. MD5 Hash 伪向量（最终兜底）

    Returns:
        (encode_fn, model_name, dim)
    """
    # 尝试 1: BGE-M3
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(
            "BAAI/bge-m3",
            local_files_only=True,
        )
        logger.info("[Embedding] BGE-M3 加载成功 (1024d)")
        return model.encode, "BAAI/bge-m3", 1024
    except Exception as e:
        logger.warning(f"[Embedding] BGE-M3 不可用: {e}")

    # 尝试 2: all-MiniLM-L6-v2
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(
            "sentence-transformers/all-MiniLM-L6-v2",
            local_files_only=True,
        )

        def _encode_minilm(texts):
            vecs = model.encode(texts, normalize_embeddings=True)
            # Pad 384 → 1024
            padded = []
            for v in vecs:
                p = list(v) + [0.0] * (BGE_M3_DIM - len(v))
                padded.append(p)
            return padded

        logger.info("[Embedding] all-MiniLM-L6-v2 加载成功 (384d→1024d pad)")
        return _encode_minilm, "all-MiniLM-L6-v2", 1024
    except Exception as e:
        logger.warning(f"[Embedding] MiniLM 不可用: {e}")

    # 尝试 3: MD5 Hash
    logger.info("[Embedding] 使用 MD5 Hash 伪向量 (1024d)")
    return _HashEmbedder.encode, "md5-hash", 1024


# =========================
# Milvus 连接管理
# =========================


class _MockMilvusStore:
    """
    Mock Milvus 存储 — 内存中的向量存储。

    用于开发/测试阶段无需启动 Milvus 服务的场景。
    支持基本的向量插入和检索。
    """

    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}
        self._collection_exists = False

    def create_collection(self, collection_name: str):
        """创建 Collection（Mock 无操作）。"""
        self._collection_exists = True
        logger.info(f"[MockMilvus] Collection '{collection_name}' 已创建（内存）")

    def insert(self, collection_name: str, data: List[Dict[str, Any]]):
        """插入数据。"""
        for item in data:
            chunk_id = item.get("id", "")
            self._store[chunk_id] = item
        logger.info(
            f"[MockMilvus] 插入 {len(data)} 条到 '{collection_name}' "
            f"(总计 {len(self._store)} 条)"
        )

    def search(
        self,
        collection_name: str,
        query_vector: List[float],
        top_k: int = DEFAULT_SEARCH_TOP_K,
    ) -> List[Dict[str, Any]]:
        """
        Mock 向量检索 — 使用余弦相似度排序。

        Args:
            collection_name: Collection 名称
            query_vector: 查询向量 (1024d)
            top_k: 返回数量

        Returns:
            相似度排序的结果列表
        """
        if not self._store:
            return []

        results = []
        for chunk_id, item in self._store.items():
            stored_vec = item.get("vector", [])
            if not stored_vec:
                continue
            # 内积相似度
            score = sum(a * b for a, b in zip(query_vector, stored_vec))
            # 归一化到 [0, 1]
            norm_q = sum(x * x for x in query_vector) ** 0.5
            norm_s = sum(x * x for x in stored_vec) ** 0.5
            if norm_q > 0 and norm_s > 0:
                score = score / (norm_q * norm_s)
            results.append({
                "id": chunk_id,
                "text": item.get("text", ""),
                "source_doc": item.get("source_doc", ""),
                "doc_type": item.get("doc_type", ""),
                "clause": item.get("clause", ""),
                "score": round(float(score), 6),
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]


# =========================
# 知识入库流水线
# =========================


class KnowledgeIngestion:
    """
    知识入库流水线。

    完整流程: 文档解析 → 文本分块 → 向量化 → 入库 Milvus

    使用方式:
        ingestion = KnowledgeIngestion()
        await ingestion.ingest_all_mock()
        results = await ingestion.search("动火作业安全要求")
    """

    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ):
        """
        初始化入库流水线。

        Args:
            collection_name: Milvus Collection 名称
            chunk_size: 分块大小（字符数）
            chunk_overlap: 分块重叠（字符数）
        """
        self.collection_name = collection_name
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._parser = DocumentParser(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        self._embed_fn = None
        self._embed_model_name = ""
        self._embed_dim = BGE_M3_DIM
        self._milvus: Optional[_MockMilvusStore] = None
        self._real_milvus = None
        self._use_real_milvus = False  # 追踪是否成功使用了真实 Milvus

    # ---- 嵌入模型懒加载 ----

    def _ensure_embedding(self):
        """确保嵌入模型已加载。"""
        if self._embed_fn is None:
            self._embed_fn, self._embed_model_name, self._embed_dim = _load_embedding_model()

    # ---- 数据摄入 ----

    async def ingest_documents(self, file_paths: List[Path]) -> int:
        """
        解析并摄入文档到知识库。

        Args:
            file_paths: 文档路径列表

        Returns:
            摄入的总分块数
        """
        # Step 1: 解析文档
        chunks = await self._parser.parse_batch(file_paths)
        if not chunks:
            logger.warning("[Ingestion] 无文档分块生成")
            return 0

        # Step 2: 向量化 + 入库
        count = await self._embed_and_insert(chunks)
        logger.info(
            f"[Ingestion] 摄入完成: {len(file_paths)} 份文档 → "
            f"{count} 条向量记录"
        )
        return count

    async def ingest_all_mock(self) -> int:
        """
        摄入所有 Mock 法规数据到知识库。

        Returns:
            摄入的总分块数
        """
        logger.info("[Ingestion] 摄入 Mock 法规数据...")

        # Step 1: 解析所有 Mock 文档
        chunks = await self._parser.parse_all_mock()
        if not chunks:
            logger.warning("[Ingestion] 无 Mock 文档分块生成")
            return 0

        # Step 2: 向量化 + 入库
        count = await self._embed_and_insert(chunks)
        logger.info(
            f"[Ingestion] Mock 摄入完成: {len(chunks)} 块 → {count} 条向量记录"
        )
        return count

    async def ingest_text(
        self,
        text: str,
        title: str = "",
        doc_type: str = "meeting_minutes",
    ) -> List[str]:
        """
        将纯文本分块、向量化并存入知识库。

        用于不需要文件解析的文本归档场景（会议纪要、对话记录等）。
        复用现有的分块和向量化管道。

        Args:
            text: 待入库的纯文本
            title: 文档标题（用作 source_doc 标识）
            doc_type: 文档类型标识

        Returns:
            归档的 chunk_id 列表
        """
        import uuid

        if not text or not text.strip():
            logger.warning("[Ingestion] ingest_text: 文本为空，跳过")
            return []

        # 使用 ChineseTextSplitter 分块
        from app.core.knowledge.document_parser import ChineseTextSplitter, DocumentChunk

        splitter = ChineseTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        text_chunks = splitter.split(text)

        if not text_chunks:
            logger.warning("[Ingestion] ingest_text: 分块为空，跳过")
            return []

        # 将文本块包装为 DocumentChunk
        source_doc = title or "untitled"
        chunks: List[DocumentChunk] = []
        for i, chunk_text in enumerate(text_chunks):
            chunk_id = f"TEXT_{source_doc[:30]}_{uuid.uuid4().hex[:8]}"
            chunks.append(DocumentChunk(
                chunk_id=chunk_id,
                text=chunk_text,
                source_doc=source_doc,
                doc_type=doc_type,
                clause="",
                page=1,
                chunk_index=i,
                metadata={"title": source_doc, "doc_type": doc_type},
            ))

        # 向量化 + 入库
        count = await self._embed_and_insert(chunks)
        chunk_ids = [c.chunk_id for c in chunks]

        logger.info(
            f"[Ingestion] 文本摄入完成: '{title or 'untitled'}' "
            f"({len(text)} chars) → {count} 条向量记录"
        )
        return chunk_ids

    async def _embed_and_insert(self, chunks: List[DocumentChunk]) -> int:
        """
        向量化分块并插入 Milvus。

        Args:
            chunks: DocumentChunk 列表

        Returns:
            成功插入的记录数
        """
        if not chunks:
            return 0

        self._ensure_embedding()

        # 提取文本
        texts = [c.text for c in chunks]

        # 批量向量化
        logger.info(
            f"[Ingestion] 向量化 {len(texts)} 个分块 "
            f"(model={self._embed_model_name})..."
        )

        try:
            # 注意：某些模型（如 BGE-M3 via SentenceTransformer）
            # 处理大批量时可能 OOM，分批处理
            batch_size = 32
            all_vectors: List[List[float]] = []

            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                if hasattr(self._embed_fn, '__self__'):
                    # SentenceTransformer.encode
                    vecs = self._embed_fn(batch)
                else:
                    # _HashEmbedder.encode (单文本)
                    vecs = [self._embed_fn(t) for t in batch]
                all_vectors.extend(vecs)

        except Exception as e:
            logger.error(f"[Ingestion] 向量化失败: {e}", exc_info=True)
            return 0

        # 构建插入数据
        records = []
        for chunk, vector in zip(chunks, all_vectors):
            records.append({
                "id": chunk.chunk_id,
                "text": chunk.text,
                "vector": vector.tolist() if hasattr(vector, 'tolist') else vector,
                "source_doc": chunk.source_doc,
                "doc_type": chunk.doc_type,
                "clause": chunk.clause,
                "chunk_index": chunk.chunk_index,
            })

        # 入库
        await self._insert_to_milvus(records)
        return len(records)

    async def _insert_to_milvus(self, records: List[Dict[str, Any]]):
        """
        插入记录到 Milvus。

        优先使用真实 Milvus，不可用时降级为 Mock 内存存储。

        Args:
            records: 待插入的记录列表
        """
        # 尝试真实 Milvus
        if await self._try_real_milvus_insert(records):
            return

        # Mock 降级
        if self._milvus is None:
            self._milvus = _MockMilvusStore()
            self._milvus.create_collection(self.collection_name)

        self._milvus.insert(self.collection_name, records)

    async def _try_real_milvus_insert(self, records: List[Dict[str, Any]]) -> bool:
        """
        尝试使用真实 Milvus 插入数据。

        Returns:
            True 如果成功，False 如果需要降级
        """
        try:
            from pymilvus import MilvusClient

            from app.config import get_settings

            settings = get_settings()
            host = settings.milvus.host
            port = settings.milvus.port

            client = MilvusClient(uri=f"http://{host}:{port}")

            # 检查连接
            try:
                client.list_collections()
            except Exception:
                logger.warning(
                    "[Ingestion] Milvus 服务不可用，降级为 Mock 内存存储"
                )
                return False

            # 创建 Collection（如不存在）
            collection_name = self.collection_name
            collections = client.list_collections()
            if collection_name not in collections:
                client.create_collection(
                    collection_name=collection_name,
                    dimension=BGE_M3_DIM,
                    metric_type="IP",
                    auto_id=False,
                )
                logger.info(f"[Ingestion] 创建 Milvus Collection: {collection_name}")

            # 批量插入
            client.insert(
                collection_name=collection_name,
                data=records,
            )

            logger.info(
                f"[Ingestion] Milvus 真实插入: {len(records)} 条 "
                f"→ {collection_name}"
            )
            self._use_real_milvus = True
            return True

        except ImportError:
            logger.info("[Ingestion] pymilvus 不可用，降级为 Mock 内存存储")
            return False
        except Exception as e:
            logger.warning(f"[Ingestion] 真实 Milvus 插入失败 ({e})，降级 Mock")
            return False

    # ---- 向量检索 ----

    async def search(
        self,
        query: str,
        top_k: int = DEFAULT_SEARCH_TOP_K,
        filter_doc_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        在知识库中检索与查询最相关的法规/SOP 分块。

        Args:
            query: 查询文本
            top_k: 返回数量
            filter_doc_type: 可选，按文档类型过滤 (regulation/standard/sop/guideline)

        Returns:
            相似度排序的结果列表，每项含 id、text、source_doc、clause、score
        """
        self._ensure_embedding()

        # 向量化查询
        try:
            if hasattr(self._embed_fn, '__self__'):
                query_vec = self._embed_fn([query])[0]
            else:
                query_vec = self._embed_fn(query)

            if hasattr(query_vec, 'tolist'):
                query_vec = query_vec.tolist()
        except Exception as e:
            logger.error(f"[Ingestion] 查询向量化失败: {e}")
            return []

        # 检索
        results = await self._search_milvus(query_vec, top_k)

        # 应用文档类型过滤
        if filter_doc_type:
            results = [
                r for r in results
                if r.get("doc_type", "") == filter_doc_type
            ]

        logger.info(
            f"[Ingestion] 检索完成: query='{query[:60]}...' → "
            f"{len(results)} 条 (top_k={top_k})"
        )
        return results

    async def _search_milvus(
        self, query_vector: List[float], top_k: int
    ) -> List[Dict[str, Any]]:
        """在 Milvus（真实或 Mock）中执行向量检索。"""
        # 仅在之前成功使用真实 Milvus 插入时才搜索真实 Milvus
        if self._use_real_milvus:
            real_results = await self._try_real_milvus_search(query_vector, top_k)
            if real_results is not None:
                return real_results

        # Mock 降级
        if self._milvus is None:
            return []

        return self._milvus.search(self.collection_name, query_vector, top_k)

    async def _try_real_milvus_search(
        self, query_vector: List[float], top_k: int
    ) -> Optional[List[Dict[str, Any]]]:
        """尝试真实 Milvus 检索。返回 None 表示需要降级。"""
        try:
            from pymilvus import MilvusClient

            from app.config import get_settings

            settings = get_settings()
            host = settings.milvus.host
            port = settings.milvus.port

            client = MilvusClient(uri=f"http://{host}:{port}")

            # 检查 Collection 是否存在
            collections = client.list_collections()
            if self.collection_name not in collections:
                logger.info(
                    f"[Ingestion] Collection '{self.collection_name}' 不存在于 Milvus"
                )
                return None

            results = client.search(
                collection_name=self.collection_name,
                data=[query_vector],
                limit=top_k,
                output_fields=["id", "text", "source_doc", "doc_type", "clause"],
                search_params={"nprobe": DEFAULT_NPROBE},
            )

            # 标准化结果
            output = []
            for hits in results:
                for hit in hits:
                    entity = hit.get("entity", hit)
                    output.append({
                        "id": entity.get("id", ""),
                        "text": entity.get("text", ""),
                        "source_doc": entity.get("source_doc", ""),
                        "doc_type": entity.get("doc_type", ""),
                        "clause": entity.get("clause", ""),
                        "score": round(float(hit.get("distance", 0)), 6),
                    })

            return output

        except ImportError:
            return None
        except Exception as e:
            logger.warning(f"[Ingestion] 真实 Milvus 检索失败 ({e})")
            return None

    # ---- 统计 ----

    def get_stats(self) -> Dict[str, Any]:
        """获取知识库统计信息。"""
        if self._milvus is None:
            return {"total_chunks": 0, "mode": "mock_empty"}

        total = len(self._milvus._store)
        doc_types: Dict[str, int] = {}
        source_docs: Dict[str, int] = {}

        for item in self._milvus._store.values():
            dt = item.get("doc_type", "unknown")
            doc_types[dt] = doc_types.get(dt, 0) + 1
            sd = item.get("source_doc", "unknown")
            source_docs[sd] = source_docs.get(sd, 0) + 1

        return {
            "total_chunks": total,
            "mode": "mock",
            "embedding_model": self._embed_model_name,
            "doc_types": doc_types,
            "source_docs": source_docs,
        }


# =========================
# 便捷函数
# =========================


async def ingest_knowledge_base(
    collection_name: str = DEFAULT_COLLECTION,
) -> int:
    """
    一键摄入知识库（便捷函数）。

    摄入所有 Mock 法规数据到指定的 Milvus Collection。

    Args:
        collection_name: Collection 名称

    Returns:
        摄入的向量记录数
    """
    ingestion = KnowledgeIngestion(collection_name=collection_name)
    return await ingestion.ingest_all_mock()
