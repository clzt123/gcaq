"""
多维自适应记忆管理器

统一管理短期工作记忆与长期专家经验记忆。

短期记忆:
    - 主模式: Redis List 滑动窗口缓冲（持久化 + 分布式）
    - 降级模式: collections.deque（开发环境零外部依赖）
    - 接口一致，切换对调用方透明

长期专家经验记忆:
    - 主模式: Milvus 向量相似度检索（BGE-M3 Embedding）
    - 降级模式: mock_memory.json 关键词重叠度匹配
    - use_mock 参数控制：None=自动检测 / True=强制Mock / False=强制真实

设计原则:
    - async/await 优先
    - 中文 Docstring
    - 优雅降级：真实后端不可用时自动回退 Mock，不抛异常
    - 接口签名不变：已有调用方（nodes.py / workflow.py）无需修改

ADR-10 参考: 见 ARCHITECTURE.md#adr-10-记忆系统分层设计
"""
import json
import logging
from collections import deque
from typing import Any, Dict, List, Optional

from app.utils import get_mock_path

logger = logging.getLogger(__name__)

# =========================
# 模块级常量
# =========================

DEFAULT_SHORT_TERM_WINDOW = 5       # 默认返回最近 N 轮对话
MAX_CONVERSATION_TURNS = 100        # 短期记忆最大保存轮数
DEFAULT_EXPERT_TOP_K = 3            # 专家经验默认返回数
MILVUS_SEARCH_NPROBE = 8            # Milvus 搜索时探测的聚类数
MILVUS_SEARCH_LIMIT = 20            # Milvus 搜索时内部检索上限


# =========================
# 短期记忆 — deque 实现（降级后备）
# =========================


class _ShortTermBuffer:
    """
    短期工作记忆滑动窗口缓冲（deque 实现）。

    内部使用 collections.deque(maxlen=MAX_CONVERSATION_TURNS) 实现。
    作为 Redis 不可用时的降级方案。
    接口设计与 Redis list 操作完全一致。
    """

    def __init__(self) -> None:
        self._buffer: deque[Dict[str, str]] = deque(maxlen=MAX_CONVERSATION_TURNS)

    def add(self, role: str, content: str) -> None:
        """
        追加一条对话记录。

        Args:
            role: 角色 ("system" / "human" / "ai")
            content: 消息内容
        """
        self._buffer.append({"role": role, "content": content})

    def get_recent(self, n: int = DEFAULT_SHORT_TERM_WINDOW) -> List[Dict[str, str]]:
        """
        获取最近 N 轮对话。

        Args:
            n: 返回轮数（默认 5）

        Returns:
            最近 N 条消息列表
        """
        items = list(self._buffer)[-n:]
        return items

    def get_context_str(self, n: int = DEFAULT_SHORT_TERM_WINDOW) -> str:
        """
        获取最近 N 轮对话的格式化文本（注入 LLM Prompt 用）。

        Args:
            n: 返回轮数

        Returns:
            格式化的对话上下文字符串
        """
        items = self.get_recent(n)
        if not items:
            return ""
        lines = [f"[{m['role']}]: {m['content']}" for m in items]
        return "\n".join(lines)

    def clear(self) -> None:
        """清空全部对话历史。"""
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)


# =========================
# 短期记忆 — Redis 实现
# =========================


class _RedisShortTermBuffer:
    """
    短期工作记忆滑动窗口缓冲（Redis 实现）。

    使用 Redis List (LPUSH + LTRIM + LRANGE) 实现滑动窗口。
    接口与 _ShortTermBuffer 完全一致，切换对调用方透明。

    Redis 数据结构:
        Key: safeguard:short_term:<session_id>
        Type: List
        容量: LTRIM 限制为 MAX_CONVERSATION_TURNS
    """

    def __init__(self, redis_url: str, session_id: str = "default") -> None:
        """
        Args:
            redis_url: Redis 连接 URL
            session_id: 会话 ID（预留，未来支持多会话隔离）
        """
        self._session_id = session_id
        self._key = f"safeguard:short_term:{session_id}"

        import redis
        self._client = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,   # 快速失败，避免阻塞降级
            socket_timeout=2,
        )
        # 验证连接
        self._client.ping()
        logger.info(f"[Memory] Redis 短期记忆已就绪: {redis_url} (key={self._key})")

    def add(self, role: str, content: str) -> None:
        """
        追加一条对话记录到 Redis List 头部。

        Args:
            role: 角色
            content: 消息内容
        """
        import json as _json
        entry = _json.dumps({"role": role, "content": content}, ensure_ascii=False)
        self._client.lpush(self._key, entry)
        self._client.ltrim(self._key, 0, MAX_CONVERSATION_TURNS - 1)

    def get_recent(self, n: int = DEFAULT_SHORT_TERM_WINDOW) -> List[Dict[str, str]]:
        """
        从 Redis List 尾部获取最近 N 轮对话。

        Args:
            n: 返回轮数

        Returns:
            最近 N 条消息列表（按时间正序）
        """
        import json as _json
        # LRANGE 从尾部取 n 条（最早插入的在尾部）
        entries = self._client.lrange(self._key, 0, n - 1)
        # Redis list 是倒序的（最新在头部），需反转
        entries.reverse()
        return [_json.loads(e) for e in entries]

    def get_context_str(self, n: int = DEFAULT_SHORT_TERM_WINDOW) -> str:
        """
        获取最近 N 轮对话的格式化文本。

        Args:
            n: 返回轮数

        Returns:
            格式化的对话上下文字符串
        """
        items = self.get_recent(n)
        if not items:
            return ""
        lines = [f"[{m['role']}]: {m['content']}" for m in items]
        return "\n".join(lines)

    def clear(self) -> None:
        """清空全部对话历史（删除 Redis Key）。"""
        self._client.delete(self._key)

    def __len__(self) -> int:
        return self._client.llen(self._key)


# =========================
# 长期专家经验记忆 — Mock 关键词匹配（降级后备）
# =========================


class _ExpertMemoryStore:
    """
    长期专家经验记忆存储（Mock 实现）。

    Mock 模式: 关键词匹配 mock_memory.json。
    作为 Milvus 不可用时的降级方案。
    """

    def __init__(self, use_mock: Optional[bool] = None) -> None:
        """
        Args:
            use_mock: 是否强制 Mock 模式。None 时自动使用 Mock（当前默认）。
        """
        self._use_mock = use_mock if use_mock is not None else True
        self._cache: Optional[Dict[str, Any]] = None

    def _load(self) -> Dict[str, Any]:
        """加载 Mock 记忆数据（全局缓存）。"""
        if self._cache is not None:
            return self._cache

        mock_file = get_mock_path("mock_memory.json")
        if not mock_file.exists():
            logger.warning(f"[Memory] Mock 记忆文件不存在: {mock_file}")
            self._cache = {}
            return self._cache

        with open(mock_file, "r", encoding="utf-8") as f:
            self._cache = json.load(f)
        return self._cache

    def retrieve(
        self,
        query: str,
        top_k: int = DEFAULT_EXPERT_TOP_K,
    ) -> List[Dict[str, Any]]:
        """
        检索与查询相关的专家经验与反思记录（Mock 模式）。

        基于查询词与 scenario/ai_wrong_answer 的关键词重叠度匹配。

        Args:
            query: 查询文本（隐患类型 + 描述）
            top_k: 返回数量上限

        Returns:
            记忆条目列表，每项:
                {"source": "expert"/"reflection",
                 "memory_id": str,
                 "text": str,
                 "score": float}
        """
        data = self._load()
        if not data:
            return []

        results: List[Dict[str, Any]] = []
        query_lower = query.lower()

        # 检索专家经验
        for mem in data.get("long_term_expert_memory", []):
            scenario = mem.get("scenario", "")
            score = _keyword_overlap_score(query_lower, scenario.lower())
            if score > 0:
                results.append({
                    "source": "expert",
                    "memory_id": mem.get("memory_id", ""),
                    "scenario": scenario,
                    "text": mem.get("expert_solution", ""),
                    "score": score,
                })

        # 检索反思记忆
        for ref in data.get("reflection_memory", []):
            wrong = ref.get("ai_wrong_answer", "")
            score = _keyword_overlap_score(query_lower, wrong.lower())
            if score > 0:
                results.append({
                    "source": "reflection",
                    "memory_id": ref.get("reflection_id", ""),
                    "text": (
                        f"❌ 历史错误: {wrong}\n"
                        f"✅ 人工修正: {ref.get('human_correction', '')}\n"
                        f"📖 学到的规则: {ref.get('learned_rule', '')}"
                    ),
                    "score": score * 0.8,
                })

        # 按 score 降序，取 top_k
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:top_k]

    def build_memory_context(self, memory_items: List[Dict[str, Any]]) -> str:
        """
        将检索到的记忆条目拼接为 LLM Prompt 上下文。

        Args:
            memory_items: retrieve() 返回的记忆列表

        Returns:
            格式化的记忆上下文字符串
        """
        if not memory_items:
            return ""

        lines = ["【历史经验参考 - 请结合以下经验优化处置建议】"]
        for i, item in enumerate(memory_items, 1):
            source_label = "专家经验" if item["source"] == "expert" else "反思教训"
            lines.append(f"\n📌 {source_label} #{i} (相关度: {item['score']:.2f})")
            lines.append(item["text"])
        lines.append("")

        return "\n".join(lines)


# =========================
# 本地 Hash Embedding（HuggingFace 不可用时的降级方案）
# =========================


class _HashEmbedder:
    """
    基于 MD5 哈希的本地文本向量化器。

    在 HuggingFace 不可达时作为降级方案，无需任何网络访问。
    使用确定性哈希种子 + numpy 生成归一化向量，
    保证相同文本产生相同向量（可复现）。

    Attributes:
        dim: 向量维度（默认 256）
    """

    def __init__(self, dim: int = 256) -> None:
        import numpy as _np
        self._dim = dim
        self._np = _np

    def embed(self, text: str) -> List[float]:
        """将文本转为归一化向量。"""
        import hashlib
        # MD5 digest → int seed → reproducible random vector
        seed = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16) % (2 ** 31)
        rng = self._np.random.RandomState(seed)
        vec = rng.randn(self._dim).astype(float)
        norm = self._np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()


# =========================
# 长期专家经验记忆 — Milvus 向量检索
# =========================


class _MilvusExpertStore:
    """
    长期专家经验记忆存储（Milvus 向量检索实现）。

    使用 BGE-M3 模型将查询文本转为向量，在 Milvus Collection 中
    检索 Top-K 相似条目。使用 MilvusClient (PyMilvus 3.x) API。

    接口与 _ExpertMemoryStore 完全一致，切换对调用方透明。
    """

    # 类级缓存：Embedding 模型单例
    _embed_model: Any = None

    def __init__(self, milvus_settings: Any) -> None:
        """
        Args:
            milvus_settings: MilvusSettings 配置实例

        Raises:
            ConnectionError: Milvus 不可用时抛出，由 MemoryManager 捕获并降级
        """
        from pymilvus import MilvusClient

        self._settings = milvus_settings
        self._collection_name = milvus_settings.memory_collection_name
        self._search_top_k = getattr(milvus_settings, "search_top_k", 10)
        self._metric_type = getattr(milvus_settings, "metric_type", "IP")

        # 建立 Milvus 连接 (MilvusClient 使用 HTTP API)
        host = milvus_settings.host
        port = milvus_settings.port
        self._client = MilvusClient(uri=f"http://{host}:{port}", timeout=10)

        # 验证 Collection 存在
        if not self._client.has_collection(self._collection_name):
            raise ConnectionError(
                f"Milvus Collection '{self._collection_name}' 不存在。"
                f" 请先运行: python scripts/embed_to_milvus.py"
            )

        # 加载 Collection 到内存
        self._client.load_collection(self._collection_name)
        # 获取实体数
        stats = self._client.get_collection_stats(self._collection_name)
        row_count = stats.get("row_count", 0)
        logger.info(
            f"[Memory] Milvus 向量检索已就绪: "
            f"{host}:{port} "
            f"(collection={self._collection_name}, entities={row_count})"
        )

    async def retrieve(
        self,
        query: str,
        top_k: int = DEFAULT_EXPERT_TOP_K,
    ) -> List[Dict[str, Any]]:
        """
        Milvus 向量相似度检索。

        流程:
            1. 将 query 文本用 BGE-M3 转为 Embedding
            2. 在 Milvus Collection 中搜索 Top-K 相似向量
            3. 返回标准化格式的记忆条目

        Args:
            query: 查询文本
            top_k: 返回数量上限

        Returns:
            记忆条目列表（格式与 _ExpertMemoryStore.retrieve() 一致）
        """
        # Step 1: 文本 → 向量
        query_embedding = self._embed_query(query)

        # Step 2: Milvus 向量搜索
        search_params = {"metric_type": self._metric_type, "params": {"nprobe": MILVUS_SEARCH_NPROBE}}

        try:
            results = self._client.search(
                collection_name=self._collection_name,
                data=[query_embedding],
                anns_field="vector",
                search_params=search_params,
                limit=min(MILVUS_SEARCH_LIMIT, top_k * 3),
                output_fields=["text", "source", "memory_id"],
            )
        except Exception as e:
            logger.error(f"[Memory] Milvus 搜索失败: {e}")
            return []

        # Step 3: 转换为标准格式
        items: List[Dict[str, Any]] = []
        if results and results[0]:
            for hit in results[0]:
                entity = hit.get("entity", {})
                items.append({
                    "source": entity.get("source", "expert"),
                    "memory_id": entity.get("memory_id", ""),
                    "text": entity.get("text", ""),
                    "score": round(float(hit.get("distance", 0)), 4),
                })

        # 去重 (按 text 内容)
        seen = set()
        unique_items = []
        for item in items:
            key = item["text"][:100]
            if key not in seen:
                seen.add(key)
                unique_items.append(item)

        return unique_items[:top_k]

    def build_memory_context(self, memory_items: List[Dict[str, Any]]) -> str:
        """
        将检索到的记忆条目拼接为 LLM Prompt 上下文。

        Args:
            memory_items: retrieve() 返回的记忆列表

        Returns:
            格式化的记忆上下文字符串
        """
        if not memory_items:
            return ""

        lines = ["【历史经验参考 - 请结合以下经验优化处置建议】"]
        for i, item in enumerate(memory_items, 1):
            source_label = "专家经验" if item["source"] == "expert" else "反思教训"
            lines.append(f"\n📌 {source_label} #{i} (相似度: {item['score']:.4f})")
            lines.append(item["text"])
        lines.append("")

        return "\n".join(lines)

    # ---- Embedding 模型管理 (私有) ----

    # hash embedding 的默认维度（与 embed_to_milvus.py 离线模式一致）
    _HASH_VEC_DIM = 256

    @classmethod
    def _get_embed_model(cls):
        """
        懒加载 Embedding 模型（类级单例）。

        优先级: BGE-M3 → all-MiniLM-L6-v2 → 本地 hash 降级。
        本地 hash 降级保证在无网络/防火墙环境下 Milvus 检索仍可用。

        Returns:
            SentenceTransformer 实例，或 hash-embed 函数，或 None
        """
        if cls._embed_model is not None:
            return cls._embed_model

        # 依次尝试 HuggingFace 模型（仅限本地缓存，避免网络超时阻塞）
        candidates = ["BAAI/bge-m3", "all-MiniLM-L6-v2"]
        for model_name in candidates:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"[Memory] 尝试加载本地模型: {model_name} ...")
                cls._embed_model = SentenceTransformer(
                    model_name,
                    local_files_only=True,  # 仅本地缓存，无网络则立即失败
                )
                dim = cls._embed_model.get_sentence_embedding_dimension()
                logger.info(f"[Memory] ✅ 模型就绪，向量维度: {dim}")
                return cls._embed_model
            except Exception as e:
                logger.warning(f"[Memory] {model_name} 本地不可用: {e}")
                continue

        # 本地 hash 降级：MD5→random seed→normalized vector
        logger.warning(
            f"[Memory] ⚠️  HuggingFace 不可达，启用本地 hash Embedding "
            f"(dim={cls._HASH_VEC_DIM})。检索精度有限，建议在有网络时运行 "
            f"python scripts/embed_to_milvus.py 替换为 BGE-M3 向量。"
        )
        cls._embed_model = _HashEmbedder(cls._HASH_VEC_DIM)
        return cls._embed_model

    @classmethod
    def _embed_query(cls, query: str) -> List[float]:
        """
        将查询文本转为向量。

        Args:
            query: 查询文本

        Returns:
            向量列表
        """
        model = cls._get_embed_model()
        if model is None:
            raise RuntimeError("Embedding模型 不可用")
        # 兼容 SentenceTransformer 和 _HashEmbedder
        if hasattr(model, "encode"):
            embedding = model.encode(
                [query],
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return embedding[0].tolist()
        else:
            # _HashEmbedder 实例
            return model.embed(query)


# =========================
# 关键词重叠度评分
# =========================


def _keyword_overlap_score(query: str, target: str) -> float:
    """
    计算查询与目标文本的关键词重叠度（0-1）。

    Mock 模式下用于检索匹配。

    Args:
        query: 查询文本
        target: 目标文本

    Returns:
        重叠度分数
    """
    if not query or not target:
        return 0.0

    # 提取查询中的中文关键词（2-4 字词组）
    keywords = set()
    for i in range(len(query)):
        if ord(query[i]) > 127:
            if i + 1 < len(query) and ord(query[i + 1]) > 127:
                keywords.add(query[i:i + 2])
            if i + 2 < len(query) and ord(query[i + 2]) > 127:
                keywords.add(query[i:i + 3])

    if not keywords:
        keywords = set(c for c in query if ord(c) > 127)

    hits = sum(1 for kw in keywords if kw in target)
    return hits / len(keywords) if keywords else 0.0


# =========================
# 统一记忆管理器
# =========================


class MemoryManager:
    """
    多维自适应记忆管理器（生产版本）。

    组合短期工作记忆（Redis / deque 降级）与长期专家经验（Milvus / Mock 降级），
    为工作流节点提供统一的记忆读写接口。

    **公共 API（签名不变，已有调用方兼容）:**

        manager = MemoryManager()
        manager.add_conversation("human", "检测到液压油泄漏")
        recent = manager.get_short_term_context()
        expert = await manager.retrieve_expert_memory("油泄漏 密封圈")
        ctx = manager.build_memory_context(expert)

    降级策略:
        - Redis 不可用 → _ShortTermBuffer (deque)
        - Milvus 不可用 → _ExpertMemoryStore (JSON 关键词匹配)
        - Embedding 模型不可用 → _ExpertMemoryStore (JSON 关键词匹配)
    """

    def __init__(self, use_mock: Optional[bool] = None) -> None:
        """
        初始化记忆管理器（自动检测 + 优雅降级）。

        检测与降级逻辑（按优先级）:
            1. 尝试连接 Redis → 失败则降级为 deque
            2. 尝试连接 Milvus → 失败则降级为关键词匹配
            3. use_mock=True → 强制跳过所有真实后端

        Args:
            use_mock: 是否强制 Mock 模式。
                None  — 自动检测（先尝试真实后端，失败降级）
                True  — 强制 Mock（deque + JSON 关键词匹配）
                False — 强制真实后端（连接失败则抛异常）
        """
        from app.config import get_settings

        settings = get_settings()

        # ---- 短期记忆 ----
        if use_mock is True:
            # 强制 Mock
            logger.info("[Memory] 强制 Mock 模式: 短期记忆使用 deque")
            self._short_term = _ShortTermBuffer()
        else:
            # 自动检测：尝试 Redis → 降级 deque
            self._short_term = self._init_short_term(settings)

        # ---- 长期专家经验 ----
        if use_mock is True:
            # 强制 Mock
            logger.info("[Memory] 强制 Mock 模式: 长期记忆使用关键词匹配")
            self._expert = _ExpertMemoryStore(use_mock=True)
        elif use_mock is False:
            # 强制真实后端
            self._expert = self._init_milvus_expert(settings)
        else:
            # 自动检测：尝试 Milvus → 降级 Mock
            self._expert = self._init_expert_with_fallback(settings)

    # ---- 短期记忆初始化 ----

    @staticmethod
    def _init_short_term(settings: Any):
        """
        尝试初始化 Redis 短期记忆，失败则降级 deque。

        Args:
            settings: Settings 配置单例

        Returns:
            _RedisShortTermBuffer 或 _ShortTermBuffer 实例
        """
        try:
            buffer = _RedisShortTermBuffer(settings.redis.url)
            logger.info("[Memory] ✅ 短期记忆: Redis 模式")
            return buffer
        except Exception as e:
            logger.warning(
                f"[Memory] ⚠️  Redis 不可用 ({e})，"
                f"短期记忆降级为 deque（内存模式）"
            )
            return _ShortTermBuffer()

    # ---- 长期记忆初始化 ----

    @staticmethod
    def _init_milvus_expert(settings: Any):
        """
        强制初始化 Milvus 专家经验存储。

        Args:
            settings: Settings 配置单例

        Returns:
            _MilvusExpertStore 实例

        Raises:
            ConnectionError: Milvus 不可用
        """
        return _MilvusExpertStore(settings.milvus)

    @staticmethod
    def _init_expert_with_fallback(settings: Any):
        """
        尝试初始化 Milvus 专家经验，失败则降级 Mock。

        降级触发条件:
            - Milvus 服务不可达
            - expert_memory Collection 不存在
            - Embedding 模型不可用
            - pymilvus / sentence-transformers 未安装

        Returns:
            _MilvusExpertStore 或 _ExpertMemoryStore 实例
        """
        try:
            return _MilvusExpertStore(settings.milvus)
        except ImportError as e:
            logger.warning(
                f"[Memory] ⚠️  pymilvus 或 sentence-transformers 未安装 ({e})，"
                f"长期记忆降级为 Mock（关键词匹配）"
            )
            return _ExpertMemoryStore(use_mock=True)
        except ConnectionError as e:
            logger.warning(
                f"[Memory] ⚠️  Milvus 不可用 ({e})，"
                f"长期记忆降级为 Mock（关键词匹配）"
            )
            return _ExpertMemoryStore(use_mock=True)
        except Exception as e:
            logger.warning(
                f"[Memory] ⚠️  Milvus 初始化异常 ({type(e).__name__}: {e})，"
                f"长期记忆降级为 Mock（关键词匹配）"
            )
            return _ExpertMemoryStore(use_mock=True)

    # =========================
    # 短期记忆 — 公共 API（签名不变）
    # =========================

    def add_conversation(self, role: str, content: str) -> None:
        """追加一条对话记录到短期记忆。"""
        self._short_term.add(role, content)

    def get_short_term_context(self, n: int = DEFAULT_SHORT_TERM_WINDOW) -> str:
        """获取最近 N 轮对话的格式化文本。"""
        return self._short_term.get_context_str(n)

    def clear_short_term(self) -> None:
        """清空短期对话历史。"""
        self._short_term.clear()

    # =========================
    # 长期专家经验 — 公共 API（签名不变）
    # =========================

    async def retrieve_expert_memory(
        self,
        query: str,
        top_k: int = DEFAULT_EXPERT_TOP_K,
    ) -> List[Dict[str, Any]]:
        """
        检索相关专家经验与反思记忆。

        根据初始化时选择的存储后端（Milvus 或 Mock），同步或异步执行检索。

        Args:
            query: 查询文本
            top_k: 返回数量上限

        Returns:
            标准化的记忆条目列表:
                {"source": "expert"/"reflection",
                 "memory_id": str,
                 "text": str,
                 "score": float}
        """
        result = self._expert.retrieve(query, top_k)
        # Milvus 检索本身是同步的（pymilvus API），但为未来 gRPC 预留 async
        if hasattr(result, "__await__"):
            return await result
        return result

    def build_memory_context(self, items: List[Dict[str, Any]]) -> str:
        """
        将检索结果拼接为 LLM Prompt 上下文。

        Args:
            items: retrieve_expert_memory() 返回的记忆列表

        Returns:
            格式化的 Prompt 上下文字符串
        """
        return self._expert.build_memory_context(items)

    # =========================
    # 便利属性
    # =========================

    @property
    def short_term_size(self) -> int:
        """短期记忆中保存的对话轮数。"""
        return len(self._short_term)

    @property
    def storage_mode(self) -> Dict[str, str]:
        """
        返回当前各存储后端的模式信息（调试用）。

        Returns:
            {"short_term": "redis"|"deque", "expert": "milvus"|"mock"}
        """
        return {
            "short_term": "redis" if isinstance(self._short_term, _RedisShortTermBuffer) else "deque",
            "expert": "milvus" if isinstance(self._expert, _MilvusExpertStore) else "mock",
        }
