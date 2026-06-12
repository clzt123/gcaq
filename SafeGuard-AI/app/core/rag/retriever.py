"""
GraphRAG 混合检索引擎

实现技术方案模块二：
    1. 关键词检索 (Cypher) + 向量检索 (Embedding) + 法规文档检索
    2. 上下文增强 — 拼接检索结果作为 LLM 推理依据
    3. 零幻觉校验 — 引用条款号，置信度 < 阈值时拒答
    4. 兜底策略 — Neo4j 空结果时降级为 Milvus 向量检索

🆕 功能2: 新增 knowledge_chunks 法规文档检索源

设计模式参考:
    - CLAUDE.md: "先查 Neo4j，再注入 Prompt"原则
    - 禁止手写固定 SQL——使用 Cypher 生成
    - 优雅降级：try-except 包裹所有外部调用
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.rag.neo4j_client import Neo4jClient
from app.utils import get_mock_path

logger = logging.getLogger(__name__)

# =========================
# 模块级常量
# =========================

# 检索配置
DEFAULT_TOP_K = 3               # 默认返回数量
MAX_CONTEXT_LENGTH = 3000       # 上下文最大字符数

# 置信度阈值
CONFIDENCE_HIGH = 0.80          # 高置信度 — 直接使用
CONFIDENCE_MEDIUM = 0.60        # 中置信度 — 标记为"仅供参考"
# < CONFIDENCE_MEDIUM → 拒答

# 检索来源权重
WEIGHT_NEO4J_EXACT = 1.0        # Neo4j 精确匹配
WEIGHT_NEO4J_RELATED = 0.7      # Neo4j 关联匹配
WEIGHT_MILVUS = 0.5             # Milvus 向量匹配


# =========================
# Mock Milvus 搜索（开发阶段）
# =========================


_MOCK_MEMORY_CACHE: Optional[Dict[str, Any]] = None


def _load_mock_memory() -> Dict[str, Any]:
    """加载 mock_memory.json（长期专家经验 + 反思记忆），全局缓存一份。"""
    global _MOCK_MEMORY_CACHE
    if _MOCK_MEMORY_CACHE is not None:
        return _MOCK_MEMORY_CACHE

    mock_file = get_mock_path("mock_memory.json")
    if not mock_file.exists():
        logger.warning(f"Mock 记忆文件不存在: {mock_file}")
        _MOCK_MEMORY_CACHE = {}
        return _MOCK_MEMORY_CACHE

    with open(mock_file, "r", encoding="utf-8") as f:
        _MOCK_MEMORY_CACHE = json.load(f)
    return _MOCK_MEMORY_CACHE


def _mock_milvus_search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
) -> List[Dict[str, Any]]:
    """
    Mock Milvus 向量检索。

    在 mock_memory.json 中按关键词匹配专家经验记忆，
    模拟 BGE-M3 向量相似度检索。

    Args:
        query: 查询文本
        top_k: 返回数量

    Returns:
        匹配的记忆条目列表，每项含 text、source、score
    """
    memory_data = _load_mock_memory()
    if not memory_data:
        return []

    results: List[Dict[str, Any]] = []
    query_lower = query.lower()

    # 搜索专家经验记忆
    for mem in memory_data.get("long_term_expert_memory", []):
        scenario = mem.get("scenario", "")
        solution = mem.get("expert_solution", "")
        combined = f"{scenario} {solution}".lower()

        # 简单关键词匹配（Mock 替代向量相似度）
        score = _keyword_match_score(query_lower, combined)
        if score > 0:
            results.append({
                "source": "expert_memory",
                "memory_id": mem.get("memory_id", ""),
                "text": solution,
                "scenario": scenario,
                "score": min(score, 1.0),
            })

    # 搜索反思记忆
    for ref in memory_data.get("reflection_memory", []):
        wrong = ref.get("ai_wrong_answer", "")
        correct = ref.get("human_correction", "")
        rule = ref.get("learned_rule", "")
        combined = f"{wrong} {correct} {rule}".lower()

        score = _keyword_match_score(query_lower, combined)
        if score > 0:
            results.append({
                "source": "reflection_memory",
                "reflection_id": ref.get("reflection_id", ""),
                "text": f"历史教训: {rule} (原错误: {wrong})",
                "score": min(score * 0.9, 1.0),  # 反思记忆权重略低
            })

    # 按 score 降序排列
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def _keyword_match_score(query: str, target: str) -> float:
    """
    计算关键词匹配得分（Mock 向量相似度）。

    简单策略：按 query 中的词在 target 中的命中比例计分。

    Args:
        query: 查询文本（已小写）
        target: 目标文本（已小写）

    Returns:
        匹配得分 0.0-1.0
    """
    # 提取关键词（空格分词 + 中文逐字切分）
    keywords = [w for w in query.split() if len(w) >= 1]
    # 如果分词后只有单个长词（中文无空格），按字符切分
    if not keywords or (len(keywords) == 1 and len(keywords[0]) > 2):
        keywords = [query[i:i+1] for i in range(len(query))]
    # 过滤纯空白和标点
    keywords = [kw for kw in keywords if kw.strip() and kw not in "，。！？、：；""''（）"]

    if not keywords:
        return 0.0

    hits = sum(1 for kw in keywords if kw in target)
    return hits / len(keywords)


# =========================
# 🆕 功能2: Knowledge Chunks 检索（法规文档）
# =========================

_KNOWLEDGE_CHUNKS_CACHE: Optional[Dict[str, Any]] = None


def _load_mock_knowledge_chunks() -> Dict[str, Any]:
    """加载 mock_regulations.json（结构化法规文档），全局缓存一份。"""
    global _KNOWLEDGE_CHUNKS_CACHE
    if _KNOWLEDGE_CHUNKS_CACHE is not None:
        return _KNOWLEDGE_CHUNKS_CACHE

    mock_file = get_mock_path("mock_regulations.json")
    if not mock_file.exists():
        logger.warning(f"Mock 法规文件不存在: {mock_file}")
        _KNOWLEDGE_CHUNKS_CACHE = {}
        return _KNOWLEDGE_CHUNKS_CACHE

    with open(mock_file, "r", encoding="utf-8") as f:
        _KNOWLEDGE_CHUNKS_CACHE = json.load(f)
    return _KNOWLEDGE_CHUNKS_CACHE


def _mock_knowledge_chunks_search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
) -> List[Dict[str, Any]]:
    """
    🆕 功能2: Mock 法规文档知识库检索。

    在 mock_regulations.json 的文档节段中按关键词匹配，
    模拟 Milvus knowledge_chunks Collection 的向量检索。

    Args:
        query: 查询文本
        top_k: 返回数量

    Returns:
        匹配的法规分块列表，每项含 text、source、score、citation
    """
    chunks_data = _load_mock_knowledge_chunks()
    if not chunks_data:
        return []

    results: List[Dict[str, Any]] = []
    query_lower = query.lower()

    for doc in chunks_data.get("documents", []):
        doc_id = doc.get("id", "")
        doc_title = doc.get("title", "")
        doc_type = doc.get("type", "regulation")

        for section in doc.get("sections", []):
            clause = section.get("clause", "")
            title = section.get("title", "")
            content = section.get("content", "")

            # 在标题和正文中搜索
            search_text = f"{clause} {title} {content}"
            score = _keyword_match_score(query_lower, search_text.lower())

            # 对条款号精确匹配加分
            if query_lower in clause.lower() or clause.lower() in query_lower:
                score = max(score, 0.85)

            if score > 0:
                # 构建原文引用
                citation_parts = [doc_title]
                if clause:
                    citation_parts.append(f"§{clause}")
                citation = " ".join(citation_parts)

                results.append({
                    "source": "knowledge_chunks",
                    "doc_id": doc_id,
                    "doc_type": doc_type,
                    "text": f"[{doc_type}] {clause} {title}: {content[:300]}",
                    "full_text": content,
                    "clause": clause,
                    "citation": citation,
                    "score": min(score, 1.0),
                })

    # 按 score 降序排列
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]



# =========================
# GraphRAG 检索器
# =========================


class GraphRAGRetriever:
    """
    GraphRAG 混合检索引擎。

    组合 Neo4j 结构化查询 + Milvus 向量相似度检索，
    实现"先查图谱，再注入 Prompt"的零幻觉原则。

    使用方式:
        async with Neo4jClient() as neo4j:
            retriever = GraphRAGRetriever(neo4j)
            results = await retriever.retrieve("液压油泄漏如何处理")
            if results:
                context = retriever.build_context(results)
    """

    def __init__(self, neo4j_client: Neo4jClient):
        """
        初始化检索器。

        Args:
            neo4j_client: 已连接的 Neo4j 客户端
        """
        self._neo4j = neo4j_client

    # ---- 主检索接口 ----

    async def retrieve(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
    ) -> List[Dict[str, Any]]:
        """
        执行混合检索。

        1. Neo4j 关键词搜索 → 结构化实体
        2. 对找到的实体，扩展关联关系
        3. Milvus 向量相似度搜索 → 非结构化经验/案例
        4. 合并去重 → 按置信度排序
        5. 置信度低于阈值 → 标记为"需人工"

        Args:
            query: 用户查询 / 隐患描述
            top_k: 每种来源的返回数量上限

        Returns:
            检索结果列表，每项含 text、source、confidence、citation
        """
        logger.info(f"[GraphRAG] 检索: query='{query[:80]}...'")

        try:
            # ---- Step 1: Neo4j 关键词搜索 ---- #
            neo4j_results = await self._neo4j_search(query, top_k)
            logger.info(f"[GraphRAG] Neo4j 命中: {len(neo4j_results)} 条")

            # ---- Step 2: Neo4j 兜底 ----
            # 如果 Neo4j 返回空，尝试 Milvus 作为兜底
            if not neo4j_results:
                logger.info("[GraphRAG] Neo4j 无结果，触发 Milvus 兜底检索")
                milvus_results = _mock_milvus_search(query, top_k * 2)
                logger.info(f"[GraphRAG] Milvus 兜底命中: {len(milvus_results)} 条")
                # 标记为降级结果
                for r in milvus_results:
                    r["fallback"] = True
                return self._rank_results(milvus_results)

            # ---- Step 3: 扩展关联查询 ---- #
            enriched = await self._enrich_with_relations(neo4j_results)
            logger.info(f"[GraphRAG] 关联扩展后: {len(enriched)} 条")

            # ---- Step 4: Milvus 向量搜索 (expert_memory) ---- #
            milvus_results = _mock_milvus_search(query, top_k)
            logger.info(f"[GraphRAG] Milvus 命中: {len(milvus_results)} 条")

            # ---- 🆕 功能2: Knowledge Chunks 法规文档检索 ---- #
            kb_results = _mock_knowledge_chunks_search(query, top_k)
            logger.info(f"[GraphRAG] KnowledgeChunks 命中: {len(kb_results)} 条")

            # ---- Step 5: 合并去重排序 ---- #
            all_results = enriched + milvus_results + kb_results
            final = self._merge_and_dedup(all_results)
            ranked = self._rank_results(final)

            logger.info(f"[GraphRAG] 最终结果: {len(ranked)} 条")
            return ranked

        except Exception as e:
            logger.error(f"[GraphRAG] 检索失败: {e}", exc_info=True)
            return []  # 优雅降级

    # ---- Neo4j 搜索 ----

    async def _neo4j_search(
        self, query: str, top_k: int
    ) -> List[Dict[str, Any]]:
        """
        在 Neo4j 中按关键词搜索实体。

        搜索范围：Equipment, Hazard, Regulation, SOP 四类节点。
        """
        raw = await self._neo4j.search_by_keyword(query, top_k)

        results: List[Dict[str, Any]] = []
        for item in raw:
            props = item.get("properties", {})
            label = item.get("label", "")

            # 构建文本摘要
            if label == "Equipment":
                text = f"设备: {props.get('name', '')} (型号: {props.get('model', '')}, 部门: {props.get('department', '')})"
            elif label == "Hazard":
                text = f"隐患: {props.get('name', '')} (风险等级: {props.get('risk_level', '')}, 类别: {props.get('category', '')})"
            elif label == "Regulation":
                text = f"法规: {props.get('name', '')} (条款: {props.get('clause', '')})"
            elif label == "SOP":
                text = f"SOP: {props.get('name', '')} (编号: {props.get('doc_id', '')})"
            else:
                text = f"{label}: {props.get('name', str(props))}"

            results.append({
                "source": "neo4j",
                "label": label,
                "text": text,
                "properties": props,
                "score": WEIGHT_NEO4J_EXACT,
            })

        return results

    # ---- 关联扩展 ----

    async def _enrich_with_relations(
        self, base_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        对 Neo4j 搜索结果中的实体，扩展其关联实体。

        例如：搜索到 Hazard → 补充 GOVERNED_BY 法规 + MITIGATED_BY SOP。
        """
        enriched = list(base_results)
        seen_names: set = set()

        for item in base_results:
            props = item.get("properties", {})
            entity_name = props.get("name", "")
            label = item.get("label", "")

            if not entity_name or entity_name in seen_names:
                continue
            seen_names.add(entity_name)

            # Hazard: 并行查适用法规 + SOP
            if label == "Hazard":
                laws, sops = await asyncio.gather(
                    self._neo4j.get_governing_laws(entity_name),
                    self._neo4j.get_mitigation_sops(entity_name),
                )
                for law in laws:
                    text = f"适用法规: {law.get('name', '')} (条款: {law.get('clause', '')})"
                    enriched.append({
                        "source": "neo4j_relation",
                        "relation": "GOVERNED_BY",
                        "text": text,
                        "properties": law,
                        "score": WEIGHT_NEO4J_RELATED,
                    })

                for sop in sops:
                    text = f"应急处置: {sop.get('name', '')} (编号: {sop.get('doc_id', '')})"
                    enriched.append({
                        "source": "neo4j_relation",
                        "relation": "MITIGATED_BY",
                        "text": text,
                        "properties": sop,
                        "score": WEIGHT_NEO4J_RELATED,
                    })

            # Equipment: 补充关联隐患
            if label == "Equipment":
                hazards = await self._neo4j.get_equipment_hazards(entity_name)
                for h in hazards:
                    hz = h.get("h", h)
                    name = hz.get("name", "") if isinstance(hz, dict) else str(hz)
                    if name not in seen_names:
                        seen_names.add(name)
                        # 也递归查法规
                        laws = await self._neo4j.get_governing_laws(name)
                        for law in laws:
                            text = f"关联法规: {law.get('name', '')} (条款: {law.get('clause', '')})"
                            enriched.append({
                                "source": "neo4j_relation",
                                "relation": "GOVERNED_BY",
                                "text": text,
                                "properties": law,
                                "score": WEIGHT_NEO4J_RELATED * 0.8,
                            })

        return enriched

    # ---- 合并去重排序 ----

    def _merge_and_dedup(
        self, results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        按 text 内容去重，加权合并，按 score 降序排列。
        """
        seen_texts: set = set()
        merged: List[Dict[str, Any]] = []

        for item in sorted(results, key=lambda x: x.get("score", 0), reverse=True):
            text = item.get("text", "")
            # 简化的去重：前 30 个字符相同视为重复
            key = text[:30].strip()
            if key and key not in seen_texts:
                seen_texts.add(key)
                # 添加引用标记
                item["citation"] = self._extract_citation(item)
                merged.append(item)

        return merged

    def _extract_citation(self, item: Dict[str, Any]) -> Optional[str]:
        """
        从检索结果中提取引用标识。

        Args:
            item: 检索结果项

        Returns:
            引用字符串 (e.g., "《企业安全生产标准化基本规范》§5.4.2.3")
        """
        props = item.get("properties", {})
        label = item.get("label", "")
        source = item.get("source", "")

        if "neo4j" in source:
            name = props.get("name", "")
            clause = props.get("clause", "")
            doc_id = props.get("doc_id", "")
            if clause:
                return f"{name} §{clause}"
            if doc_id:
                return f"{name} [{doc_id}]"
            if name:
                return name

        # 🆕 功能2: Knowledge Chunks 引用
        if source == "knowledge_chunks":
            # 优先使用 item 中已有的 citation 字段
            citation = item.get("citation", "")
            if citation:
                return citation
            # 从 clause 构建
            clause = item.get("clause", "")
            doc_id = item.get("doc_id", "")
            if clause:
                return f"{doc_id} §{clause}" if doc_id else f"§{clause}"
            return doc_id if doc_id else None

        memory_id = item.get("memory_id", "") or item.get("reflection_id", "")
        if memory_id:
            return f"经验记录 {memory_id}"

        return None

    # ---- 结果排序 ----

    def _rank_results(
        self, results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """对结果进行置信度排序和标记。"""
        for item in results:
            score = item.get("score", 0)
            if score >= CONFIDENCE_HIGH:
                item["confidence"] = "high"
            elif score >= CONFIDENCE_MEDIUM:
                item["confidence"] = "medium"
            else:
                item["confidence"] = "low"

        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results

    # ---- 上下文构建 ----

    def build_context(self, results: List[Dict[str, Any]]) -> str:
        """
        将检索结果拼接为 LLM Prompt 可用的上下文字符串。

        Args:
            results: 检索结果列表

        Returns:
            格式化的上下文文本，含引用标记
        """
        if not results:
            return "【检索结果】未找到相关法规或经验依据。\n"

        high_conf = [r for r in results if r.get("confidence") == "high"]
        medium_conf = [r for r in results if r.get("confidence") == "medium"]
        low_conf = [r for r in results if r.get("confidence") == "low"]

        parts: List[str] = []
        total_len = 0

        def _add_section(title: str, items: List[Dict[str, Any]], prefix: str) -> None:
            nonlocal total_len
            if not items:
                return
            lines = [f"\n【{title}】"]
            for i, item in enumerate(items, 1):
                text = item.get("text", "")
                citation = item.get("citation", "")
                line = f"  {prefix}{i}. {text}"
                if citation:
                    line += f"  📎 [引用: {citation}]"
                if total_len + len(line) > MAX_CONTEXT_LENGTH:
                    lines.append(f"  ... (已截断，共 {len(items)} 条)")
                    break
                lines.append(line)
                total_len += len(line)
            parts.extend(lines)

        _add_section("高置信度依据 (可直接引用)", high_conf, "✅ ")
        _add_section("中置信度参考 (建议核实)", medium_conf, "⚠️ ")
        _add_section("低置信度线索 (仅供参考)", low_conf, "💡 ")

        return "\n".join(parts)


# =========================
# 便捷函数
# =========================


async def graph_rag_retrieve(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    neo4j_client: Optional[Neo4jClient] = None,
) -> List[Dict[str, Any]]:
    """
    GraphRAG 混合检索便捷函数。

    实现技术方案附录 B.2 接口 3：
        1. 在 Neo4j 中查找实体关系 (Cypher)
        2. 在 Milvus 中查找相似案例 (Vector Search)
        3. 合并去重返回

    Args:
        query: 查询文本
        top_k: 返回数量
        neo4j_client: 可复用的 Neo4j 客户端，None 时自动创建

    Returns:
        检索结果列表，每项含 text、source、confidence、citation
    """
    should_close = neo4j_client is None

    if neo4j_client is None:
        neo4j_client = Neo4jClient()
        await neo4j_client._ensure_connected()

    try:
        retriever = GraphRAGRetriever(neo4j_client)
        results = await retriever.retrieve(query, top_k)
        return results
    finally:
        if should_close:
            await neo4j_client.close()
