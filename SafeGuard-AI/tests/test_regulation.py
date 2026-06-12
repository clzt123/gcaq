"""
法规变更影响分析模块测试

测试范围:
    - TextDiffer: 文本对比、相似度计算、HTML差异生成
    - ImpactAnalyzer: 影响追溯、影响等级评估
    - RegulationManager: 端到端流程
"""
import pytest

from app.core.regulation.text_differ import (
    TextDiffer,
    DiffResult,
    ClauseChange,
    ChangeType,
)
from app.core.regulation.impact_analyzer import (
    ImpactAnalyzer,
    ImpactReport,
    ImpactedEntity,
)
from app.core.regulation.regulation_manager import RegulationManager


# =========================
# 测试数据
# =========================

OLD_CLAUSE = "高处作业用安全带应每季度进行一次外观检查和静载试验，检查记录存档备查。安全带使用寿命为5年。"
NEW_CLAUSE = "高处作业用安全带应每月进行一次外观检查和静载试验，检查记录通过安全生产数字化平台存档。安全带使用寿命为3年，到期必须强制报废。"


# =========================
# 1. TextDiffer 测试
# =========================


class TestTextDiffer:
    """文本差异对比器测试"""

    def test_compare_identical_texts(self):
        """测试相同文本对比"""
        differ = TextDiffer()
        change = differ.compare_clause("安全生产", "安全生产", section_id="§1")
        assert change.change_type == ChangeType.UNCHANGED
        assert change.similarity == 1.0

    def test_compare_different_texts(self):
        """测试不同文本对比"""
        differ = TextDiffer()
        change = differ.compare_clause(OLD_CLAUSE, NEW_CLAUSE, section_id="§8.3", title="安全带管理")
        assert change.change_type == ChangeType.AMENDED
        assert change.similarity < 0.95
        assert len(change.keywords) >= 1

    def test_compare_added_clause(self):
        """测试新增条款"""
        differ = TextDiffer()
        change = differ.compare_clause("", NEW_CLAUSE, section_id="§15", title="新增条款")
        assert change.change_type == ChangeType.ADDED
        assert change.similarity == 0.0

    def test_compare_deleted_clause(self):
        """测试删除条款"""
        differ = TextDiffer()
        change = differ.compare_clause(OLD_CLAUSE, "", section_id="§8.3", title="删除条款")
        assert change.change_type == ChangeType.DELETED
        assert change.similarity == 0.0

    def test_compare_regulation_from_mock(self):
        """测试从 Mock 数据对比法规"""
        differ = TextDiffer()
        result = differ.compare_from_mock("REG-CHG-001")

        assert result is not None
        assert result.regulation_name.startswith("GB30871")
        assert result.total_sections >= 3
        assert result.changed_sections >= 3
        assert len(result.summary) > 20

    def test_compare_regulation_from_mock_default(self):
        """测试默认（第一个）Mock 法规变更"""
        differ = TextDiffer()
        result = differ.compare_from_mock()
        assert result is not None
        assert result.total_sections > 0

    def test_compare_regulation_batch(self):
        """测试批量条款对比"""
        differ = TextDiffer()
        sections = [
            {"section_id": "§1", "title": "第一条", "old_text": "AAA", "new_text": "BBB"},
            {"section_id": "§2", "title": "第二条", "old_text": "XXX", "new_text": "XXX"},
            {"section_id": "§3", "title": "第三条", "old_text": "", "new_text": "新增内容"},
        ]
        result = differ.compare_regulation("测试法规", sections)
        assert result.total_sections == 3
        assert result.changed_sections == 2

    def test_generate_html_diff(self):
        """测试 HTML 差异生成"""
        differ = TextDiffer()
        html = differ._generate_html_diff(OLD_CLAUSE, NEW_CLAUSE)
        assert "diff" in html.lower() or "<table" in html.lower()

    def test_extract_keywords(self):
        """测试关键词提取"""
        differ = TextDiffer()
        keywords = differ._extract_keywords(NEW_CLAUSE)
        assert "安全带" in keywords
        assert "数字化" in keywords

    def test_list_mock_changes(self):
        """测试列出 Mock 变更"""
        differ = TextDiffer()
        changes = differ.list_mock_changes()
        assert len(changes) == 2
        assert "GB30871" in changes[0]["regulation_name"]

    def test_compare_nonexistent_change_id(self):
        """测试不存在的变更 ID"""
        differ = TextDiffer()
        result = differ.compare_from_mock("NONEXISTENT")
        # 应返回第一个默认值（fallback行为）
        assert result is not None
        assert result.total_sections > 0


# =========================
# 2. ImpactAnalyzer 测试
# =========================


class TestImpactAnalyzer:
    """影响分析器测试"""

    @pytest.mark.asyncio
    async def test_analyze_from_diff_result(self):
        """测试从 DiffResult 分析影响"""
        differ = TextDiffer()
        diff_result = differ.compare_from_mock("REG-CHG-001")

        analyzer = ImpactAnalyzer()
        report = await analyzer.analyze(diff_result)

        assert isinstance(report, ImpactReport)
        assert report.regulation_name.startswith("GB30871")
        assert report.total_impacted >= 1
        assert report.high_impact_count + report.medium_impact_count + report.low_impact_count == report.total_impacted

    @pytest.mark.asyncio
    async def test_analyze_empty_diff(self):
        """测试空变更分析"""
        analyzer = ImpactAnalyzer()
        empty_diff = DiffResult(regulation_name="测试", changed_sections=0)
        report = await analyzer.analyze(empty_diff)

        assert report.total_impacted == 0
        assert "无需评估" in report.change_summary

    @pytest.mark.asyncio
    async def test_mock_trace(self):
        """测试 Mock 追溯"""
        analyzer = ImpactAnalyzer()
        change = ClauseChange(
            section_id="§5.2",
            title="动火作业审批",
            old_text="...",
            new_text="...数字化...",
            change_type=ChangeType.AMENDED,
            keywords=["动火作业", "数字化"],
            similarity=0.7,
        )
        entities = analyzer._mock_trace(change)
        assert len(entities) >= 1

    @pytest.mark.asyncio
    async def test_impact_level_assessment(self):
        """测试影响等级评估"""
        analyzer = ImpactAnalyzer()
        change = ClauseChange(
            section_id="§1",
            title="测试",
            change_type=ChangeType.AMENDED,
            similarity=0.7,
        )
        level = analyzer._assess_impact_level(change, "Hazard", "测试隐患")
        assert level == "high"

        level = analyzer._assess_impact_level(change, "Equipment", "测试设备")
        assert level == "medium"

    @pytest.mark.asyncio
    async def test_deduplicate(self):
        """测试实体去重"""
        analyzer = ImpactAnalyzer()
        entities = [
            ImpactedEntity("Equipment", "设备A", "medium"),
            ImpactedEntity("Equipment", "设备A", "high"),  # 同一实体但有更高等级
            ImpactedEntity("Equipment", "设备B", "low"),
        ]
        result = analyzer._deduplicate(entities)
        assert len(result) == 2  # 去重后2个
        # 设备A应保留高影响等级
        device_a = [e for e in result if e.entity_name == "设备A"]
        assert len(device_a) == 1
        assert device_a[0].impact_level == "high"

    @pytest.mark.asyncio
    async def test_suggest_action(self):
        """测试建议生成"""
        analyzer = ImpactAnalyzer()
        change = ClauseChange(
            section_id="§5.2",
            title="测试",
            change_type=ChangeType.AMENDED,
            similarity=0.7,
        )
        action = analyzer._suggest_action("Equipment", "high", change)
        assert len(action) > 5

    @pytest.mark.asyncio
    async def test_recommendations_with_high_impact(self):
        """测试高影响建议"""
        analyzer = ImpactAnalyzer()
        report = ImpactReport(regulation_name="测试法规")
        entities = [
            ImpactedEntity("Hazard", "泄漏", "high"),
            ImpactedEntity("Equipment", "注塑机", "medium"),
        ]
        diff = DiffResult(regulation_name="测试", changes=[])
        recs = analyzer._generate_recommendations(entities, diff)
        assert len(recs) >= 2


# =========================
# 3. RegulationManager 测试
# =========================


class TestRegulationManager:
    """法规管理器端到端测试"""

    @pytest.mark.asyncio
    async def test_analyze_change(self):
        """测试分析法规变更"""
        mgr = RegulationManager()
        report = await mgr.analyze_change("REG-CHG-001")

        assert report is not None
        assert isinstance(report, ImpactReport)
        assert report.total_impacted >= 1
        assert len(report.recommendations) >= 1

    @pytest.mark.asyncio
    async def test_analyze_default_change(self):
        """测试默认法规变更"""
        mgr = RegulationManager()
        report = await mgr.analyze_change()

        assert report is not None
        assert report.regulation_name is not None

    @pytest.mark.asyncio
    async def test_analyze_custom_change(self):
        """测试自定义法规变更"""
        mgr = RegulationManager()
        sections = [
            {"section_id": "§1", "title": "第一条", "old_text": "AAA", "new_text": "BBB"},
        ]
        report = await mgr.analyze_custom_change("测试法规", sections)
        assert isinstance(report, ImpactReport)
        assert "测试法规" in report.regulation_name

    def test_list_available_changes(self):
        """测试列出可用变更"""
        mgr = RegulationManager()
        changes = mgr.list_available_changes()
        assert len(changes) == 2
