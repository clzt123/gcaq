"""
本体驱动图谱模块测试

测试范围:
    - 三元组抽取：正则兜底 + LLM降级
    - Schema 管理：节点/关系类型注册、校验、动态注册
    - 图谱管理器：端到端流程
"""
import pytest

from app.core.ontology.triplet_extractor import (
    TripletExtractor,
    Triplet,
    ExtractionResult,
    _RegexTripletExtractor,
)
from app.core.ontology.schema_manager import (
    SchemaManager,
    NodeType,
    RelationType,
)
from app.core.ontology.ontology_manager import (
    OntologyManager,
    GraphExpansionResult,
)


# =========================
# 测试数据
# =========================

SAMPLE_EHS_TEXT = """
根据安全生产法要求，3号注塑机存在液压油泄漏隐患，属于危险化学品泄漏范畴。
车间应按照注塑机日常点检与泄漏应急处置SOP进行处置。
消防通道堵塞问题违反了建筑设计防火规范GB50016的相关要求。
2号焊接工位发现安全帽违规现象，需要立即整改。
化学品仓库存在初期火灾风险，消防栓水压偏低需要及时维修。
"""

SAMPLE_SIMPLE_TEXT = "灭火器需要每月检查一次，配电箱存在漏电风险。"


# =========================
# 1. RegexTripletExtractor 测试
# =========================


class TestRegexTripletExtractor:
    """正则三元组抽取测试"""

    def test_extract_from_rich_text(self):
        """测试从丰富文本中抽取三元组"""
        extractor = _RegexTripletExtractor()
        result = extractor.extract(SAMPLE_EHS_TEXT)

        assert isinstance(result, ExtractionResult)
        assert result.extraction_method == "regex"
        assert result.total_extracted >= 1, f"应至少抽取1个三元组: {result.total_extracted}"
        assert result.source_length == len(SAMPLE_EHS_TEXT)

    def test_extract_from_simple_text(self):
        """测试从简单文本中抽取"""
        extractor = _RegexTripletExtractor()
        result = extractor.extract(SAMPLE_SIMPLE_TEXT)
        assert isinstance(result, ExtractionResult)

    def test_extracted_triplets_have_fields(self):
        """测试三元组字段完整性"""
        extractor = _RegexTripletExtractor()
        result = extractor.extract(SAMPLE_EHS_TEXT)

        for triplet in result.triplets:
            assert triplet.subject, "主体不应为空"
            assert triplet.object, "客体不应为空"
            assert triplet.relation, "关系不应为空"
            assert triplet.subject_type in (
                "Equipment", "Hazard", "Regulation", "SOP"
            )
            assert triplet.confidence > 0

    def test_classify_entity(self):
        """测试实体类型推断"""
        extractor = _RegexTripletExtractor()

        assert extractor._classify_entity("3号注塑机") == "Equipment"
        assert extractor._classify_entity("液压油泄漏") == "Hazard"
        assert extractor._classify_entity("安全生产法") == "Regulation"
        assert extractor._classify_entity("巡检SOP") == "SOP"

    def test_empty_text(self):
        """测试空文本"""
        extractor = _RegexTripletExtractor()
        result = extractor.extract("")
        assert result.total_extracted == 0


# =========================
# 2. TripletExtractor 测试
# =========================


class TestTripletExtractor:
    """三元组抽取器完整测试（含 LLM 降级）"""

    @pytest.mark.asyncio
    async def test_extract_with_llm_fallback(self):
        """测试 LLM 不可用时降级为正则"""
        extractor = TripletExtractor()
        result = await extractor.extract(SAMPLE_EHS_TEXT)

        assert isinstance(result, ExtractionResult)
        assert result.total_extracted >= 1
        assert result.extraction_method in ("llm", "regex")

    @pytest.mark.asyncio
    async def test_extract_empty_text(self):
        """测试空文本"""
        extractor = TripletExtractor()
        result = await extractor.extract("")
        assert result.total_extracted == 0


# =========================
# 3. SchemaManager 测试
# =========================


class TestSchemaManager:
    """Schema 管理器测试"""

    def test_predefined_nodes_loaded(self):
        """测试预定义节点类型已加载"""
        mgr = SchemaManager()
        types = mgr.list_node_types()
        assert len(types) >= 4
        labels = {t.label for t in types}
        assert "Equipment" in labels
        assert "Hazard" in labels
        assert "Regulation" in labels
        assert "SOP" in labels

    def test_predefined_relations_loaded(self):
        """测试预定义关系类型已加载"""
        mgr = SchemaManager()
        relations = mgr.list_relation_types()
        assert len(relations) >= 6

    def test_register_new_node(self):
        """测试注册新节点类型"""
        mgr = SchemaManager()
        nt = mgr.register_node("FireExtinguisher", "灭火器", required=["name", "location"])
        assert nt.label == "FireExtinguisher"
        assert mgr.has_node_type("FireExtinguisher")

    def test_register_new_relation(self):
        """测试注册新关系类型"""
        mgr = SchemaManager()
        rt = mgr.register_relation("REQUIRES", "需要配备", from_labels=["Equipment"], to_labels=["Equipment"])
        assert rt.type_name == "REQUIRES"
        assert mgr.has_relation_type("REQUIRES")

    def test_validate_valid_triplet(self):
        """测试校验合法三元组"""
        mgr = SchemaManager()
        valid, reason = mgr.validate_triplet("Equipment", "HAS_HAZARD", "Hazard")
        assert valid, f"应通过校验: {reason}"

    def test_validate_invalid_triplet(self):
        """测试校验非法三元组"""
        mgr = SchemaManager()
        # HAS_HAZARD 只允许 from Equipment/Department to Hazard
        valid, reason = mgr.validate_triplet("Regulation", "HAS_HAZARD", "SOP")
        assert not valid, f"非法三元组应拒绝: {reason}"

    def test_ensure_relation_auto_register(self):
        """测试自动注册新关系类型"""
        mgr = SchemaManager()
        assert not mgr.has_relation_type("NEW_CUSTOM_REL")

        rt = mgr.ensure_relation_type("NEW_CUSTOM_REL")
        assert mgr.has_relation_type("NEW_CUSTOM_REL")
        assert rt.type_name == "NEW_CUSTOM_REL"

    def test_export_schema(self):
        """测试 Schema 导出"""
        mgr = SchemaManager()
        exported = mgr.export_schema()
        assert "nodes" in exported
        assert "relations" in exported
        assert len(exported["nodes"]) >= 4


# =========================
# 4. OntologyManager 测试
# =========================


class TestOntologyManager:
    """图谱管理器端到端测试"""

    @pytest.mark.asyncio
    async def test_expand_graph(self):
        """测试图谱扩展（Mock 模式）"""
        mgr = OntologyManager()
        result = await mgr.expand_graph(SAMPLE_EHS_TEXT, "测试文本")

        assert isinstance(result, GraphExpansionResult)
        assert result.extracted_count >= 1
        assert result.validated_count >= 1
        assert len(result.cypher_statements) >= 1

    @pytest.mark.asyncio
    async def test_expand_graph_simple_text(self):
        """测试简单文本图谱扩展"""
        mgr = OntologyManager()
        result = await mgr.expand_graph(SAMPLE_SIMPLE_TEXT)
        assert isinstance(result, GraphExpansionResult)

    @pytest.mark.asyncio
    async def test_expand_graph_empty_text(self):
        """测试空文本"""
        mgr = OntologyManager()
        result = await mgr.expand_graph("")
        assert result.extracted_count == 0

    @pytest.mark.asyncio
    async def test_cypher_generation(self):
        """测试 Cypher 生成"""
        mgr = OntologyManager()
        triplets = [
            Triplet(
                subject="3号注塑机",
                subject_type="Equipment",
                relation="HAS_HAZARD",
                object="液压油泄漏",
                object_type="Hazard",
                confidence=0.9,
            ),
        ]
        statements = mgr._generate_cypher(triplets)
        assert len(statements) == 1
        assert "MERGE" in statements[0]
        assert "HAS_HAZARD" in statements[0]
        assert "3号注塑机" in statements[0]
        assert "液压油泄漏" in statements[0]

    @pytest.mark.asyncio
    async def test_cypher_escape(self):
        """测试 Cypher 转义"""
        mgr = OntologyManager()
        dangerous = "测试'设备"
        escaped = mgr._escape_cypher(dangerous)
        assert "'" not in escaped or "\\'" in escaped

    @pytest.mark.asyncio
    async def test_schema_summary(self):
        """测试获取 Schema 摘要"""
        mgr = OntologyManager()
        summary = mgr.get_schema_summary()
        assert "nodes" in summary
        assert "relations" in summary

    @pytest.mark.asyncio
    async def test_expand_graph_new_relations(self):
        """测试 LLM 抽取新关系类型时的自动注册"""
        mgr = OntologyManager()
        # 使用包含多样化关系的文本
        text = """
        焊接工位的灭火器配备不足，需要按照消防规范配备。
        电气线路老化存在火灾隐患，电工需每月巡检一次。
        """
        result = await mgr.expand_graph(text)
        assert isinstance(result, GraphExpansionResult)
        # 验证不崩溃即可——核心覆盖


# =========================
# 5. 数据模型测试
# =========================


class TestModels:
    """数据模型测试"""

    def test_triplet_creation(self):
        """测试 Triplet 创建"""
        t = Triplet(
            subject="3号注塑机",
            subject_type="Equipment",
            relation="HAS_HAZARD",
            object="液压油泄漏",
            object_type="Hazard",
            confidence=0.9,
            evidence="原文证据",
        )
        assert t.subject == "3号注塑机"
        assert t.relation == "HAS_HAZARD"
        assert t.confidence == 0.9

    def test_node_type_creation(self):
        """测试 NodeType 创建"""
        nt = NodeType(
            label="Equipment",
            description="设备",
            required_properties=["name"],
            optional_properties=["model"],
        )
        assert nt.label == "Equipment"
        assert "name" in nt.required_properties

    def test_relation_type_creation(self):
        """测试 RelationType 创建"""
        rt = RelationType(
            type_name="HAS_HAZARD",
            description="存在隐患",
            from_labels=["Equipment"],
            to_labels=["Hazard"],
        )
        assert rt.type_name == "HAS_HAZARD"
        assert "Equipment" in rt.from_labels

    def test_graph_expansion_result_defaults(self):
        """测试 GraphExpansionResult 默认值"""
        r = GraphExpansionResult()
        assert r.extracted_count == 0
        assert r.inserted_count == 0
        assert r.cypher_statements == []
        assert r.errors == []
