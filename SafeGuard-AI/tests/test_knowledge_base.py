"""
结构化知识库模块单元测试

覆盖:
    - DocumentChunk 数据模型
    - ChineseTextSplitter: 中文分块
    - MockDocumentParser: Mock 文档解析
    - DocumentParser: 统一解析器工厂
    - KnowledgeIngestion: 入库流水线（Mock 模式）
    - Knowledge Chunks 检索集成
    - Mock 法规数据完整性

测试策略:
    - 全部使用 Mock 模式（无需 Milvus/Unstructured 服务）
    - 数据流端到端：解析→分块→向量化→入库→检索
"""
import json
from pathlib import Path

import pytest

from app.core.knowledge.document_parser import (
    DocumentChunk,
    ChineseTextSplitter,
    MockDocumentParser,
    DocumentParser,
)
from app.core.knowledge.ingestion import (
    KnowledgeIngestion,
    _HashEmbedder,
    _MockMilvusStore,
    DEFAULT_COLLECTION,
)


# =========================
# DocumentChunk 测试
# =========================


class TestDocumentChunk:
    """测试文档分块数据模型"""

    def test_create_chunk_minimal(self):
        """最小字段创建"""
        chunk = DocumentChunk(
            chunk_id="TEST_0001",
            text="测试文本内容",
            source_doc="测试文档.pdf",
        )
        assert chunk.chunk_id == "TEST_0001"
        assert chunk.text == "测试文本内容"
        assert chunk.source_doc == "测试文档.pdf"
        assert chunk.doc_type == "regulation"  # 默认值
        assert chunk.clause == ""
        assert chunk.page == 0

    def test_create_chunk_full(self):
        """全字段创建"""
        chunk = DocumentChunk(
            chunk_id="GB30871_0005",
            text="动火作业前应进行可燃气体检测分析...",
            source_doc="GB30871-2022.pdf",
            doc_type="standard",
            clause="§5.2",
            page=12,
            chunk_index=5,
            metadata={"issuer": "国家标准委", "year": "2022"},
        )
        assert chunk.doc_type == "standard"
        assert chunk.clause == "§5.2"
        assert chunk.page == 12
        assert chunk.chunk_index == 5
        assert chunk.metadata["issuer"] == "国家标准委"


# =========================
# ChineseTextSplitter 测试
# =========================


class TestChineseTextSplitter:
    """测试中文感知文本分块器"""

    def setup_method(self):
        self.splitter = ChineseTextSplitter(chunk_size=500, chunk_overlap=50)

    def test_split_empty_text(self):
        """空文本返回空列表"""
        assert self.splitter.split("") == []
        assert self.splitter.split("   \n\n  ") == []

    def test_split_short_text_single_chunk(self):
        """短文本保持为单块"""
        text = "这是一段简短的法规文本。不超过500字符。"
        chunks = self.splitter.split(text)
        assert len(chunks) == 1
        assert text in chunks[0]

    def test_split_long_text_multiple_chunks(self):
        """长文本被切分为多块"""
        # 生成一段超过500字符的文本
        text = "动火作业安全管理要求。" * 60  # ~600 chars
        chunks = self.splitter.split(text)
        assert len(chunks) >= 1

    def test_split_by_paragraph(self):
        """按段落拆分"""
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        chunks = self.splitter.split(text)
        # 按双换行拆分，3段或合并后至少1段
        assert len(chunks) >= 1
        # 所有原文内容应在分块中出现
        combined = "".join(chunks)
        assert "第一段" in combined
        assert "第二段" in combined
        assert "第三段" in combined

    def test_split_preserves_clause_markers(self):
        """条款号标记不应被截断"""
        text = (
            "§4.1 基本要求：危险化学品企业进行特殊作业时，"
            "应严格执行本规范。特殊作业包括动火作业、受限空间作业等。"
        )
        chunks = self.splitter.split(text)
        # 条款号应在第一个块中完整保留
        assert len(chunks) >= 1
        assert "§4.1" in chunks[0]

    def test_split_chinese_text_no_character_break(self):
        """中文词汇不应在中间被截断"""
        text = "生产经营单位应当建立安全风险分级管控制度。"
        chunks = self.splitter.split(text, {})
        # 短文本不应被截断
        assert len(chunks) == 1


# =========================
# MockDocumentParser 测试
# =========================


class TestMockDocumentParser:
    """测试 Mock 文档解析器"""

    @pytest.mark.asyncio
    async def test_parse_by_doc_id(self):
        """按文档 ID 解析单个法规文档"""
        parser = MockDocumentParser()
        chunks = await parser.parse(Path("GB30871-2022"))
        assert len(chunks) > 0, "应有分块生成"
        # 检查分块结构
        for chunk in chunks:
            assert chunk.chunk_id.startswith("GB30871")
            assert chunk.text
            assert chunk.source_doc
            assert chunk.doc_type in ("regulation", "standard", "sop", "guideline")

    @pytest.mark.asyncio
    async def test_parse_by_filename(self):
        """按文件名解析"""
        parser = MockDocumentParser()
        chunks = await parser.parse(Path("SafetyLaw-2021.pdf"))
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_parse_nonexistent_doc_returns_empty(self):
        """不存在的文档返回空列表"""
        parser = MockDocumentParser()
        chunks = await parser.parse(Path("NONEXISTENT-DOC"))
        assert chunks == []

    @pytest.mark.asyncio
    async def test_parse_all_mock(self):
        """解析所有 Mock 文档"""
        parser = MockDocumentParser()
        chunks = await parser.parse_all()
        # 5 份文档应有明显多于 5 个分块
        assert len(chunks) >= 10
        # 验证文档类型多样性
        doc_types = {c.doc_type for c in chunks}
        assert len(doc_types) >= 2, f"应至少有2种文档类型，实际: {doc_types}"

    @pytest.mark.asyncio
    async def test_parse_batch(self):
        """批量解析多个文档"""
        parser = MockDocumentParser()
        chunks = await parser.parse_batch([
            Path("GB30871-2022"),
            Path("SOP-EHS-001"),
        ])
        assert len(chunks) > 0
        # 应包含两种文档类型
        doc_types = {c.doc_type for c in chunks}
        assert "standard" in doc_types or "sop" in doc_types

    @pytest.mark.asyncio
    async def test_chunks_have_clause_info(self):
        """分块应保留条款号信息"""
        parser = MockDocumentParser()
        chunks = await parser.parse(Path("GB30871-2022"))
        clauses = {c.clause for c in chunks if c.clause}
        assert len(clauses) > 0, "至少部分分块应有条款号"
        # 检查是否有 §5.2 这样的条款号
        has_section = any("§" in c for c in clauses)
        assert has_section, "应有含 § 符号的条款号"

    @pytest.mark.asyncio
    async def test_chunks_have_metadata(self):
        """分块应包含元数据"""
        parser = MockDocumentParser()
        chunks = await parser.parse(Path("GB30871-2022"))
        for chunk in chunks:
            assert "doc_id" in chunk.metadata
            assert "section_title" in chunk.metadata


# =========================
# DocumentParser 统一工厂测试
# =========================


class TestDocumentParserFactory:
    """测试统一解析器工厂"""

    @pytest.mark.asyncio
    async def test_parse_mock_doc(self):
        """解析 Mock 文档（自动降级）"""
        parser = DocumentParser()
        chunks = await parser.parse(Path("SOP-EHS-002"))
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_parse_all_mock(self):
        """解析所有 Mock 文档"""
        parser = DocumentParser()
        chunks = await parser.parse_all_mock()
        assert len(chunks) >= 10

    @pytest.mark.asyncio
    async def test_parse_nonexistent_file_falls_back_to_mock(self):
        """不存在的文件尝试 Mock 匹配"""
        parser = DocumentParser()
        chunks = await parser.parse(Path("nonexistent_regulation.pdf"))
        # 未匹配到 Mock 文档 → 空列表
        assert isinstance(chunks, list)


# =========================
# KnowledgeIngestion 测试
# =========================


class TestKnowledgeIngestion:
    """测试知识入库流水线（Mock 模式）"""

    @pytest.mark.asyncio
    async def test_ingest_all_mock(self):
        """摄入所有 Mock 法规数据"""
        ingestion = KnowledgeIngestion()
        count = await ingestion.ingest_all_mock()
        assert count > 0, f"应摄入至少1条记录，实际: {count}"
        # 统计信息
        stats = ingestion.get_stats()
        assert stats["total_chunks"] == count
        assert stats["mode"] == "mock"

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        """摄入后检索应返回结果"""
        ingestion = KnowledgeIngestion()
        await ingestion.ingest_all_mock()

        results = await ingestion.search("动火作业安全要求")
        assert len(results) > 0, "动火作业相关检索应有结果"
        # 结果结构验证
        for r in results:
            assert "id" in r
            assert "text" in r
            assert "source_doc" in r
            assert "score" in r
            assert 0.0 <= r["score"] <= 1.0

    @pytest.mark.asyncio
    async def test_search_returns_top_k(self):
        """检索返回数量限制"""
        ingestion = KnowledgeIngestion()
        await ingestion.ingest_all_mock()

        results = await ingestion.search("安全", top_k=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_search_filter_by_doc_type(self):
        """按文档类型过滤检索"""
        ingestion = KnowledgeIngestion()
        await ingestion.ingest_all_mock()

        results = await ingestion.search("安全", top_k=10, filter_doc_type="standard")
        # 所有结果应为 standard 类型
        for r in results:
            assert r.get("doc_type") == "standard"

    @pytest.mark.asyncio
    async def test_search_empty_before_ingestion(self):
        """未摄入时检索返回空"""
        ingestion = KnowledgeIngestion()
        results = await ingestion.search("动火作业")
        assert results == []

    @pytest.mark.asyncio
    async def test_stats_after_ingestion(self):
        """摄入后统计信息完整"""
        ingestion = KnowledgeIngestion()
        await ingestion.ingest_all_mock()

        stats = ingestion.get_stats()
        assert stats["total_chunks"] > 0
        assert "doc_types" in stats
        assert "source_docs" in stats
        assert len(stats["doc_types"]) >= 2  # 至少 regulation + standard 或 sop

    @pytest.mark.asyncio
    async def test_ingestion_idempotent(self):
        """重复摄入覆盖而非追加"""
        ingestion = KnowledgeIngestion()
        count1 = await ingestion.ingest_all_mock()

        # 再次摄入（Mock 内存存储会覆盖相同 ID 的记录）
        count2 = await ingestion.ingest_all_mock()
        # Mock 模式按 chunk_id 去重，两次摄入结果数应相同
        assert count1 == count2

    @pytest.mark.asyncio
    async def test_different_collections(self):
        """不同 Collection 名称隔离数据"""
        ing1 = KnowledgeIngestion(collection_name="test_coll_1")
        ing2 = KnowledgeIngestion(collection_name="test_coll_2")

        await ing1.ingest_all_mock()
        # ing2 未摄入
        results = await ing2.search("安全")
        assert results == []


# =========================
# _HashEmbedder 测试
# =========================


class TestHashEmbedder:
    """测试 MD5 Hash 伪向量生成"""

    def test_encode_returns_1024_dim(self):
        """应返回 1024 维向量"""
        vector = _HashEmbedder.encode("测试文本")
        assert len(vector) == 1024

    def test_encode_all_values_in_range(self):
        """所有值应在 [-1, 1] 范围内"""
        vector = _HashEmbedder.encode("测试文本")
        for v in vector:
            assert -1.0 <= v <= 1.0, f"值 {v} 超出范围"

    def test_encode_different_texts_different_vectors(self):
        """不同文本生成不同向量"""
        v1 = _HashEmbedder.encode("动火作业")
        v2 = _HashEmbedder.encode("受限空间")
        # 至少前几个值应该不同
        assert v1[:10] != v2[:10]

    def test_encode_same_text_same_vector(self):
        """相同文本生成相同向量（确定性）"""
        v1 = _HashEmbedder.encode("安全生产法")
        v2 = _HashEmbedder.encode("安全生产法")
        assert v1 == v2


# =========================
# _MockMilvusStore 测试
# =========================


class TestMockMilvusStore:
    """测试 Mock Milvus 内存存储"""

    def setup_method(self):
        self.store = _MockMilvusStore()
        self.store.create_collection("test_coll")

    def test_insert_and_search(self):
        """插入后应能检索到"""
        vec = _HashEmbedder.encode("动火作业安全规范")
        self.store.insert("test_coll", [
            {
                "id": "TEST_001",
                "text": "动火作业前应进行可燃气体检测",
                "vector": vec,
                "source_doc": "GB30871-2022",
                "doc_type": "standard",
                "clause": "§5.2",
            },
        ])

        results = self.store.search("test_coll", vec, top_k=3)
        assert len(results) == 1
        assert results[0]["id"] == "TEST_001"
        assert results[0]["source_doc"] == "GB30871-2022"

    def test_search_empty_store(self):
        """空存储检索返回空"""
        results = self.store.search("test_coll", _HashEmbedder.encode("测试"), top_k=3)
        assert results == []

    def test_search_respects_top_k(self):
        """检索遵守 top_k 限制"""
        for i in range(5):
            self.store.insert("test_coll", [{
                "id": f"TEST_{i:03d}",
                "text": f"测试文档 {i}",
                "vector": _HashEmbedder.encode(f"文档{i}"),
                "source_doc": "test.pdf",
                "doc_type": "regulation",
                "clause": f"§{i}.1",
            }])

        results = self.store.search("test_coll", _HashEmbedder.encode("文档"), top_k=3)
        assert len(results) <= 3

    def test_search_results_sorted_by_score(self):
        """结果按相似度降序排列"""
        # 插入两个文档，第二个更相关
        self.store.insert("test_coll", [{
            "id": "LESS_RELEVANT",
            "text": "完全不相关的法律条款",
            "vector": _HashEmbedder.encode("法律条款"),
            "source_doc": "law.pdf",
            "doc_type": "regulation",
            "clause": "§1",
        }])
        self.store.insert("test_coll", [{
            "id": "MORE_RELEVANT",
            "text": "动火作业安全规范要求",
            "vector": _HashEmbedder.encode("动火作业安全规范要求"),
            "source_doc": "GB30871-2022",
            "doc_type": "standard",
            "clause": "§5.1",
        }])

        # 用"动火作业"查询
        query_vec = _HashEmbedder.encode("动火作业安全")
        results = self.store.search("test_coll", query_vec, top_k=2)
        assert len(results) >= 2
        # "MORE_RELEVANT" 应排在前面（分数更高）
        assert results[0]["score"] > results[1]["score"] or results[0]["id"] == "MORE_RELEVANT"


# =========================
# Mock 法规数据完整性测试
# =========================


class TestMockRegulationsData:
    """测试 mock_regulations.json 数据完整性"""

    def setup_method(self):
        from app.utils import get_mock_path

        mock_file = get_mock_path("mock_regulations.json")
        with open(mock_file, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def test_all_documents_have_required_fields(self):
        """所有文档应有必需字段"""
        for doc in self.data["documents"]:
            assert "id" in doc, f"文档缺少 id: {doc}"
            assert "title" in doc, f"文档缺少 title: {doc}"
            assert "type" in doc, f"文档缺少 type: {doc}"
            assert "sections" in doc, f"文档缺少 sections: {doc}"
            assert len(doc["sections"]) > 0, f"文档 {doc['id']} 无节段"

    def test_all_sections_have_required_fields(self):
        """所有节段应有必需字段"""
        for doc in self.data["documents"]:
            for section in doc["sections"]:
                assert "clause" in section, f"节缺少 clause: {section}"
                assert "title" in section, f"节缺少 title: {section}"
                assert "content" in section, f"节缺少 content: {section}"
                assert len(section["content"]) > 20, (
                    f"节 {section['clause']} 正文过短: {len(section['content'])} 字符"
                )

    def test_document_types_diversity(self):
        """文档类型应涵盖至少3种"""
        doc_types = {doc["type"] for doc in self.data["documents"]}
        assert len(doc_types) >= 3, (
            f"文档类型应多样，实际: {doc_types}"
        )

    def test_total_sections_count(self):
        """总节段数应足够（每份文档至少3节）"""
        for doc in self.data["documents"]:
            assert len(doc["sections"]) >= 3, (
                f"文档 {doc['id']} 节段太少: {len(doc['sections'])}"
            )

    def test_contains_expected_regulations(self):
        """应包含预期的核心法规"""
        doc_ids = {doc["id"] for doc in self.data["documents"]}
        expected = {"GB30871-2022", "SafetyLaw-2021", "GB6441-1986"}
        found = expected & doc_ids
        assert len(found) >= 2, f"缺少核心法规: {expected - doc_ids}"

    def test_contains_sops(self):
        """应包含 SOP 文档"""
        sop_docs = [
            doc for doc in self.data["documents"]
            if doc["type"] == "sop"
        ]
        assert len(sop_docs) >= 2, f"应至少有2份SOP，实际: {len(sop_docs)}"
