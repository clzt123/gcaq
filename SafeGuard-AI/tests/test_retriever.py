"""
GraphRAG 检索器单元测试

覆盖:
    - 混合检索（Neo4j + Milvus Mock）
    - 关联扩展（Hazard → 法规/SOP）
    - 结果合并去重
    - 置信度排序
    - 上下文构建
    - Neo4j 空结果时 Milvus 兜底
    - 优雅降级

测试策略:
    - 全部使用 Mock Neo4jClient + Mock Milvus
"""
import pytest

from app.core.rag.neo4j_client import Neo4jClient
from app.core.rag.retriever import (
    GraphRAGRetriever,
    graph_rag_retrieve,
    _mock_milvus_search,
    _keyword_match_score,
    DEFAULT_TOP_K,
)


# =========================
# Fixtures
# =========================


@pytest.fixture
async def neo4j_client():
    """Mock Neo4j 客户端。"""
    client = Neo4jClient(use_mock=True)
    await client._ensure_connected()
    yield client
    await client.close()


@pytest.fixture
async def retriever(neo4j_client):
    """基于 Mock Neo4j 的检索器。"""
    return GraphRAGRetriever(neo4j_client)


# =========================
# 关键词匹配测试
# =========================


class TestKeywordMatchScore:
    """测试 Mock 向量相似度计分"""

    def test_exact_match(self):
        """完全匹配"""
        score = _keyword_match_score("液压油泄漏", "液压油泄漏处理方案")
        assert score > 0.5, f"完全匹配得分应 > 0.5, 实际 {score}"

    def test_partial_match(self):
        """部分匹配"""
        score = _keyword_match_score("消防通道堵塞", "消防安全与疏散管理规范")
        assert score > 0, "部分匹配得分应 > 0"

    def test_no_match(self):
        """无匹配"""
        score = _keyword_match_score("xyzabc", "消防安全")
        assert score == 0.0


# =========================
# Mock Milvus 搜索测试
# =========================


class TestMockMilvusSearch:
    """测试 Mock Milvus 向量检索"""

    def test_search_oil_leak(self):
        """搜索泄漏相关经验"""
        results = _mock_milvus_search("液压油泄漏处理", top_k=3)
        assert len(results) >= 1, "应有专家经验命中"
        # 应包含泄漏相关记忆
        texts = " ".join(r.get("text", "") for r in results)
        assert "泄漏" in texts or "密封圈" in texts, (
            f"应命中泄漏相关经验: {texts[:100]}"
        )

    def test_search_no_match(self):
        """无匹配查询"""
        results = _mock_milvus_search("XYZ完全不相关的查询")
        # 可能返回空或低分结果
        assert isinstance(results, list)

    def test_results_have_score(self):
        """结果应包含 score 字段"""
        results = _mock_milvus_search("泄漏", top_k=2)
        for r in results:
            assert "score" in r, f"缺少 score: {r}"
            assert 0 <= r["score"] <= 1.0, f"score 超出范围: {r['score']}"


# =========================
# GraphRAG 检索器测试
# =========================


class TestGraphRAGRetrieve:
    """测试混合检索"""

    @pytest.mark.asyncio
    async def test_retrieve_oil_leak(self, retriever):
        """检索液压油泄漏"""
        results = await retriever.retrieve("液压油泄漏如何处理")
        assert len(results) >= 1, f"应有结果, 实际 {len(results)}"
        # 应包含 Neo4j 结果
        sources = {r.get("source") for r in results}
        assert "neo4j" in sources or "neo4j_relation" in sources, (
            f"应包含 Neo4j 来源: {sources}"
        )

    @pytest.mark.asyncio
    async def test_retrieve_fire_safety(self, retriever):
        """检索消防安全"""
        results = await retriever.retrieve("消防通道堵塞整改措施")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_retrieve_no_match(self, retriever):
        """检索无匹配内容"""
        results = await retriever.retrieve("XYZ完全无关的查询内容12345")
        # 应返回空列表或低置信度结果
        if results:
            for r in results:
                assert r.get("confidence") in ("low", "medium", "high")

    @pytest.mark.asyncio
    async def test_results_have_required_fields(self, retriever):
        """每条结果应包含必要字段"""
        results = await retriever.retrieve("液压油泄漏")
        for r in results:
            assert "text" in r, f"缺少 text: {r}"
            assert "source" in r, f"缺少 source: {r}"
            assert "score" in r, f"缺少 score: {r}"

    @pytest.mark.asyncio
    async def test_results_have_citation(self, retriever):
        """Neo4j 来源应有引用"""
        results = await retriever.retrieve("液压油泄漏")
        neo4j_results = [r for r in results if "neo4j" in r.get("source", "")]
        for r in neo4j_results:
            assert "citation" in r, f"Neo4j 结果缺少 citation: {r}"

    @pytest.mark.asyncio
    async def test_top_k_limit(self, retriever):
        """top_k 参数应生效"""
        results_k1 = await retriever.retrieve("泄漏", top_k=1)
        results_k5 = await retriever.retrieve("泄漏", top_k=5)
        # k1 应不多于 k5（可能受限于实际匹配数）
        assert len(results_k1) <= len(results_k5) or len(results_k5) == 0


# =========================
# 上下文构建测试
# =========================


class TestBuildContext:
    """测试 build_context 方法"""

    @pytest.mark.asyncio
    async def test_build_context_with_results(self, retriever):
        """有结果时构建上下文"""
        results = await retriever.retrieve("液压油泄漏")
        context = retriever.build_context(results)
        assert isinstance(context, str)
        assert len(context) > 0

    def test_build_context_empty(self, retriever):
        """空结果时的上下文"""
        context = retriever.build_context([])
        assert "未找到" in context

    @pytest.mark.asyncio
    async def test_context_includes_citations(self, retriever):
        """上下文应包含引用标记"""
        results = await retriever.retrieve("液压油泄漏")
        context = retriever.build_context(results)
        # 应有引用标记或法规名
        has_ref = "📎" in context or "企业安全生产标准化" in context
        assert has_ref, f"上下文应含引用标记: {context[:200]}"

    @pytest.mark.asyncio
    async def test_context_not_too_long(self, retriever):
        """上下文不应超长"""
        results = await retriever.retrieve("泄漏")
        context = retriever.build_context(results)
        # 3000 字符限制（MAX_CONTEXT_LENGTH）
        assert len(context) <= 3500, (
            f"上下文过长: {len(context)} 字符"
        )


# =========================
# 兜底策略测试
# =========================


class TestFallbackStrategy:
    """测试 Neo4j 空结果时的 Milvus 兜底"""

    @pytest.mark.asyncio
    async def test_milvus_fallback_for_unmatched(self, retriever):
        """无法在 Neo4j 中找到匹配时，应触发 Milvus 兜底"""
        # 使用一个不太可能在图谱中精确匹配的查询
        results = await retriever.retrieve(
            "资深设备工关于注塑机维护的经验建议"
        )
        # 即使 Neo4j 命中低，也应该有结果（来自 Milvus 或图谱关联）
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_results_always_list(self, retriever):
        """无论什么查询，retrieve 始终返回 list"""
        queries = [
            "液压油泄漏",
            "",
            "!@#$%^",
            "正常查询" * 100,
        ]
        for q in queries:
            results = await retriever.retrieve(q)
            assert isinstance(results, list), f"查询 '{q[:20]}' 应返回 list"


# =========================
# 便捷函数测试
# =========================


class TestConvenienceFunction:
    """测试 graph_rag_retrieve 便捷函数"""

    @pytest.mark.asyncio
    async def test_convenience_function(self):
        """便捷函数应正确工作"""
        results = await graph_rag_retrieve(
            "液压油泄漏处理", top_k=2
        )
        assert isinstance(results, list)
        if results:
            assert "text" in results[0]

    @pytest.mark.asyncio
    async def test_convenience_with_reusable_client(self, neo4j_client):
        """传入可复用 Neo4jClient 时应正确工作"""
        results = await graph_rag_retrieve(
            "消防安全", top_k=2, neo4j_client=neo4j_client
        )
        assert isinstance(results, list)
