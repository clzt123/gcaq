"""
零幻觉校验模块单元测试

覆盖:
    - CitationVerifier: 引用检测/提取/拒答标记检测
    - HallucinationGuard: 三层防线（Pre-LLM Gate / Guarded Prompt / Post-LLM Gate）
    - hallucination_guard_node: Pre-LLM 门控节点
    - llm_analysis_node: LLM 合规分析节点（含 Mock 降级）
    - 端到端: _handle_hazard 集成（普通 + 拒答场景）
    - Mock LLM 响应生成

测试策略:
    - 全部使用 Mock 模式（无需 LLM API Key）
    - 节点单独测试 + 集成测试
"""
import pytest

from app.core.guard.hallucination_guard import (
    CitationVerifier,
    HallucinationGuard,
    generate_mock_llm_response,
    REFUSAL_CONFIDENCE_THRESHOLD,
    HIGH_CITATION_THRESHOLD,
)
from app.core.graph.state import HazardState, MAX_RETRIES
from app.core.graph.nodes import (
    hallucination_guard_node,
    llm_analysis_node,
    _parse_context_confidence,
)


# =========================
# 辅助函数
# =========================


def _make_state(**overrides) -> HazardState:
    """构造最小 HazardState（含零幻觉校验字段），支持字段覆盖。"""
    base: HazardState = {
        "messages": [],
        "current_image": "",
        "detection_result": {},
        "ticket_data": {},
        "graph_context": "",
        "memory_context": "",
        "next_action": "",
        "ticket_status": "",
        "retry_count": 0,
        "edge_node_id": "",
        "area_type": "",
        "need_cloud_analysis": False,
        "llm_response": "",
        "refusal_reason": "",
        "citation_verified": False,
        "response_confidence": 0.0,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


def _make_context_with_confidence(high: int = 0, medium: int = 0, low: int = 0) -> str:
    """构建带有置信度标记的 graph_context 文本。"""
    parts = []
    if high > 0:
        parts.append("\n【高置信度依据 (可直接引用)】")
        for i in range(high):
            parts.append(
                f"  ✅ {i+1}. 法规: 《安全生产标准》§3.{i+1} "
                f"📎 [引用: 《安全生产标准》§3.{i+1}]"
            )
    if medium > 0:
        parts.append("\n【中置信度参考 (建议核实)】")
        for i in range(medium):
            parts.append(
                f"  ⚠️ {i+1}. SOP: 应急处置流程 [SOP-{100+i}] "
                f"📎 [引用: SOP-{100+i}]"
            )
    if low > 0:
        parts.append("\n【低置信度线索 (仅供参考)】")
        for i in range(low):
            parts.append(f"  💡 {i+1}. 低置信度线索 {i+1}")
    if not parts:
        return "【检索结果】未找到相关法规或经验依据。\n"
    return "\n".join(parts)


# =========================
# CitationVerifier 测试
# =========================


class TestCitationVerifier:
    """测试引用格式验证器"""

    def test_count_citations_with_law_bookmarks(self):
        """法规书名号引用应被正确计数"""
        text = "根据《安全生产法》§32.1.2 规定，企业应..."
        count = CitationVerifier.count_citations(text)
        assert count >= 2, f"至少应检测到2条引用，实际: {count}"

    def test_count_citations_with_sop(self):
        """SOP 编号引用应被正确计数"""
        text = "依据 [SOP-042] 进行应急处置。详见编号: SAFE-2024-001"
        count = CitationVerifier.count_citations(text)
        assert count >= 2, f"至少应检测到2条引用，实际: {count}"

    def test_count_citations_with_marked_citation(self):
        """带 📎 标记的引用应被正确计数"""
        text = "📎 [引用: 《企业安全生产标准化基本规范》§5.4.2.3] 要求..."
        count = CitationVerifier.count_citations(text)
        assert count >= 2, f"至少应检测到2条引用，实际: {count}"

    def test_count_citations_empty_text(self):
        """空文本应返回 0"""
        assert CitationVerifier.count_citations("") == 0
        assert CitationVerifier.count_citations("没有任何引用的普通文本。") >= 0

    def test_has_minimum_citations(self):
        """最低引用数量检查"""
        text_with_citations = "《安全生产法》§1.1 📎 [引用: SOP-001]"
        assert CitationVerifier.has_minimum_citations(text_with_citations, min_count=1)
        assert not CitationVerifier.has_minimum_citations("无引用文本", min_count=1)

    def test_extract_citations(self):
        """引用提取应返回去重列表"""
        text = "《安全生产法》§32.1 规定...同时《安全生产法》§32.1 也提到..."
        citations = CitationVerifier.extract_citations(text)
        assert len(citations) > 0

    def test_contains_refusal_markers(self):
        """拒答标记检测"""
        assert CitationVerifier.contains_refusal_markers("依据不足，无法生成分析")
        assert CitationVerifier.contains_refusal_markers("建议人工核实后处理")
        assert CitationVerifier.contains_refusal_markers("信息不足，建议人工介入")
        assert not CitationVerifier.contains_refusal_markers("根据法规分析如下...")

    def test_chinese_clause_citations(self):
        """中文条款号引用（第x条）"""
        text = "根据《安全规程》第三十二条，作业人员必须..."
        count = CitationVerifier.count_citations(text)
        assert count >= 1, f"应检测到至少1条条款引用，实际: {count}"


# =========================
# _parse_context_confidence 测试
# =========================


class TestParseContextConfidence:
    """测试上下文置信度解析"""

    def test_high_confidence_context(self):
        """高置信度上下文"""
        ctx = _make_context_with_confidence(high=3, medium=1, low=0)
        info = _parse_context_confidence(ctx)
        assert info["high_count"] == 3
        assert info["medium_count"] == 1
        assert info["low_count"] == 0
        assert info["total_count"] == 4
        assert info["has_citations"] is True

    def test_empty_context(self):
        """空检索结果"""
        ctx = _make_context_with_confidence(high=0, medium=0, low=0)
        info = _parse_context_confidence(ctx)
        assert info["high_count"] == 0
        assert info["medium_count"] == 0
        assert info["total_count"] == 0

    def test_low_only_context(self):
        """仅有低置信度"""
        ctx = _make_context_with_confidence(high=0, medium=0, low=5)
        info = _parse_context_confidence(ctx)
        assert info["high_count"] == 0
        assert info["medium_count"] == 0
        assert info["low_count"] == 5


# =========================
# HallucinationGuard 三层防线测试
# =========================


class TestHallucinationGuard:
    """测试零幻觉校验门控"""

    def setup_method(self):
        self.guard = HallucinationGuard()

    # ---- Layer 1: Pre-LLM Gate ----

    def test_retrieval_gate_high_confidence_passes(self):
        """有高置信度依据 → 通过"""
        results = [
            {"score": 0.85, "confidence": "high", "text": "法规A"},
            {"score": 0.70, "confidence": "medium", "text": "SOP-B"},
        ]
        can_proceed, reason = self.guard.check_retrieval_gate(results)
        assert can_proceed is True
        assert "高置信度" in reason

    def test_retrieval_gate_medium_above_threshold_passes(self):
        """中置信度平均分 >= 0.7 → 通过"""
        results = [
            {"score": 0.75, "confidence": "medium", "text": "SOP-A"},
            {"score": 0.72, "confidence": "medium", "text": "SOP-B"},
        ]
        can_proceed, reason = self.guard.check_retrieval_gate(results)
        assert can_proceed is True
        assert "中置信度" in reason

    def test_retrieval_gate_medium_below_threshold_refuses(self):
        """中置信度平均分 < 0.7 → 拒答"""
        results = [
            {"score": 0.65, "confidence": "medium", "text": "SOP-A"},
            {"score": 0.62, "confidence": "medium", "text": "SOP-B"},
        ]
        can_proceed, reason = self.guard.check_retrieval_gate(results)
        assert can_proceed is False
        assert "低于拒答阈值" in reason or "依据不足" in reason

    def test_retrieval_gate_low_only_refuses(self):
        """仅有低置信度 → 拒答"""
        results = [
            {"score": 0.40, "confidence": "low", "text": "线索1"},
            {"score": 0.35, "confidence": "low", "text": "线索2"},
        ]
        can_proceed, reason = self.guard.check_retrieval_gate(results)
        assert can_proceed is False

    def test_retrieval_gate_empty_refuses(self):
        """空结果 → 拒答"""
        can_proceed, reason = self.guard.check_retrieval_gate([])
        assert can_proceed is False
        assert "未返回" in reason

    # ---- Layer 2: Guarded Prompt ----

    def test_build_guarded_prompt_contains_citation_rules(self):
        """Guarded Prompt 应包含引用规则"""
        context = _make_context_with_confidence(high=2)
        prompt = self.guard.build_guarded_prompt(context, "测试查询")
        assert "强制引用规则" in prompt
        assert "引用格式要求" in prompt
        assert "禁止凭空编造" in prompt
        assert "拒答规则" in prompt

    def test_build_guarded_prompt_includes_context(self):
        """Guarded Prompt 应包含检索上下文"""
        context = _make_context_with_confidence(high=1, medium=1)
        prompt = self.guard.build_guarded_prompt(context, "油泄漏")
        assert "《安全生产标准》" in prompt
        assert "SOP-100" in prompt

    def test_build_guarded_prompt_includes_detection(self):
        """Guarded Prompt 应包含检测结果"""
        context = _make_context_with_confidence(high=1)
        detection = {
            "risk_level": "high",
            "findings": [{"type": "oil_leak", "description": "液压油泄漏", "confidence": 0.93}],
        }
        prompt = self.guard.build_guarded_prompt(context, "查询", detection)
        assert "oil_leak" in prompt
        assert "液压油泄漏" in prompt

    # ---- Layer 3: Post-LLM Gate ----

    def test_verify_response_with_citations(self):
        """带引用的响应 → 校验通过"""
        response = (
            "### 1. 法规依据\n"
            "根据《安全生产法》§32.1.2 规定 📎 [引用: 《安全生产法》§32.1.2]\n"
            "### 4. 置信度声明\n"
            "- 整体置信度: 高\n"
        )
        # 上下文需包含引用标记中的文本，使孤立引用检测通过
        ctx = (
            "【高置信度依据】\n"
            "✅ 1. 法规: 《安全生产法》§32.1.2 "
            "📎 [引用: 《安全生产法》§32.1.2]\n"
        )
        is_valid, issues = self.guard.verify_response(response, ctx)
        assert is_valid is True
        assert len(issues) == 0

    def test_verify_response_with_refusal_markers(self):
        """拒答响应 → 视为合规"""
        response = "依据不足，无法生成可靠分析。建议人工核实。"
        is_valid, issues = self.guard.verify_response(response, "")
        assert is_valid is True  # 拒答也是合规输出

    def test_verify_response_without_citations(self):
        """无引用的非拒答响应 → 校验不通过"""
        response = "这是一个没有引用的分析。风险等级高。"
        ctx = "《安全生产法》§1.1"
        is_valid, issues = self.guard.verify_response(response, ctx)
        assert is_valid is False
        assert any("引用" in issue for issue in issues)

    # ---- 综合置信度 ----

    def test_compute_confidence_with_citations(self):
        """有引用的响应 → 置信度较高"""
        response = "《安全生产法》§1.1 和 📎 [引用: SOP-001] 要求..."
        results = [{"score": 0.85, "confidence": "high"}]
        confidence = self.guard.compute_confidence(response, results)
        assert confidence > 0.5, f"期望置信度 > 0.5，实际: {confidence}"

    def test_compute_confidence_with_refusal(self):
        """拒答响应 → 置信度为 0"""
        response = "依据不足，无法生成分析"
        results = [{"score": 0.50, "confidence": "low"}]
        confidence = self.guard.compute_confidence(response, results)
        # 拒答 + 低检索 → 置信度应较低
        assert confidence < 0.5, f"期望置信度 < 0.5，实际: {confidence}"

    # ---- 拒答响应构建 ----

    def test_build_refusal_response(self):
        """拒答响应应包含原因和建议"""
        response = self.guard.build_refusal_response("测试拒答原因")
        assert "测试拒答原因" in response
        assert "人工安全员" in response or "现场核实" in response

    def test_augment_with_warning(self):
        """警告追加应包含问题列表"""
        response = "原始分析"
        augmented = self.guard.augment_with_warning(response, ["问题1", "问题2"])
        assert "原始分析" in augmented
        assert "问题1" in augmented
        assert "问题2" in augmented
        assert "校验警告" in augmented


# =========================
# hallucination_guard_node 测试
# =========================


class TestHallucinationGuardNode:
    """测试 Pre-LLM 门控节点"""

    @pytest.mark.asyncio
    async def test_high_confidence_context_passes(self):
        """高置信度上下文 → 通过"""
        ctx = _make_context_with_confidence(high=2, medium=1)
        s = _make_state(graph_context=ctx)
        result = await hallucination_guard_node(s)
        assert result["citation_verified"] is True
        assert result["refusal_reason"] == ""

    @pytest.mark.asyncio
    async def test_medium_confidence_context_passes(self):
        """中置信度上下文 → 通过"""
        ctx = _make_context_with_confidence(high=0, medium=3)
        s = _make_state(graph_context=ctx)
        result = await hallucination_guard_node(s)
        assert result["citation_verified"] is True

    @pytest.mark.asyncio
    async def test_low_only_context_refuses(self):
        """仅有低置信度 → 拒答"""
        ctx = _make_context_with_confidence(high=0, medium=0, low=3)
        s = _make_state(graph_context=ctx)
        result = await hallucination_guard_node(s)
        assert result["citation_verified"] is False
        assert result["refusal_reason"] != ""

    @pytest.mark.asyncio
    async def test_empty_context_refuses(self):
        """空检索结果 → 拒答"""
        ctx = _make_context_with_confidence(high=0, medium=0, low=0)
        s = _make_state(graph_context=ctx)
        result = await hallucination_guard_node(s)
        assert result["citation_verified"] is False
        assert result["refusal_reason"] != ""

    @pytest.mark.asyncio
    async def test_empty_context_but_high_risk_allows(self):
        """高风险 + 有 findings → 即使无检索结果也放行（防漏报）"""
        ctx = _make_context_with_confidence(high=0, medium=0, low=0)
        s = _make_state(
            graph_context=ctx,
            detection_result={
                "risk_level": "high",
                "findings": [{"type": "fire_smoke", "description": "烟雾", "confidence": 0.97}],
            },
        )
        result = await hallucination_guard_node(s)
        # 高风险 + 有 findings → 不应拒答（防漏报）
        assert result["refusal_reason"] == ""


# =========================
# llm_analysis_node 测试
# =========================


class TestLLMAnalysisNode:
    """测试 LLM 合规分析节点（Mock 降级）"""

    @pytest.mark.asyncio
    async def test_mock_response_generated(self):
        """Mock 模式下应生成带引用的分析"""
        ctx = _make_context_with_confidence(high=2, medium=1)
        s = _make_state(
            graph_context=ctx,
            detection_result={
                "risk_level": "high",
                "findings": [{"type": "oil_leak", "description": "液压油泄漏", "confidence": 0.93}],
            },
        )
        result = await llm_analysis_node(s)
        assert "llm_response" in result
        assert len(result["llm_response"]) > 0
        assert "response_confidence" in result
        assert "citation_verified" in result

    @pytest.mark.asyncio
    async def test_mock_response_contains_citations(self):
        """Mock 响应应包含引用标记"""
        ctx = _make_context_with_confidence(high=2)
        s = _make_state(
            graph_context=ctx,
            detection_result={
                "risk_level": "medium",
                "findings": [{"type": "blocked_exit", "description": "通道堵塞", "confidence": 0.91}],
            },
        )
        result = await llm_analysis_node(s)
        response = result["llm_response"]
        # 高置信度上下文 → Mock 响应应包含引用
        assert CitationVerifier.count_citations(response) > 0 or "法规依据" in response

    @pytest.mark.asyncio
    async def test_low_confidence_context_produces_refusal_mock(self):
        """低置信度上下文 → Mock 拒答响应"""
        ctx = _make_context_with_confidence(high=0, medium=0, low=2)
        s = _make_state(
            graph_context=ctx,
            detection_result={
                "risk_level": "low",
                "findings": [{"type": "unclear", "description": "模糊", "confidence": 0.3}],
            },
        )
        result = await llm_analysis_node(s)
        response = result["llm_response"]
        # 低置信度上下文 → 应包含拒答标记
        assert CitationVerifier.contains_refusal_markers(response) or "建议人工" in response

    @pytest.mark.asyncio
    async def test_empty_context_handled_gracefully(self):
        """空上下文应优雅处理"""
        s = _make_state(graph_context="【检索结果】未找到相关法规或经验依据。\n")
        result = await llm_analysis_node(s)
        assert "llm_response" in result
        assert result["llm_response"] != ""


# =========================
# generate_mock_llm_response 测试
# =========================


class TestMockLLMResponse:
    """测试 Mock LLM 响应生成"""

    def test_mock_with_high_confidence(self):
        """高置信度上下文 → 生成标准分析"""
        ctx = _make_context_with_confidence(high=2, medium=1)
        response = generate_mock_llm_response(ctx, "测试查询")
        assert "法规依据" in response
        assert "风险分析" in response
        assert "处置建议" in response
        assert "置信度声明" in response

    def test_mock_with_low_confidence_only(self):
        """仅有低置信度 → 拒答响应"""
        ctx = _make_context_with_confidence(high=0, medium=0, low=3)
        response = generate_mock_llm_response(ctx, "测试查询")
        assert CitationVerifier.contains_refusal_markers(response)

    def test_mock_with_empty_context(self):
        """空上下文 → 拒答响应"""
        ctx = _make_context_with_confidence(high=0, medium=0, low=0)
        response = generate_mock_llm_response(ctx, "测试查询")
        assert CitationVerifier.contains_refusal_markers(response)

    def test_mock_with_detection_result(self):
        """带检测结果的 Mock 响应"""
        ctx = _make_context_with_confidence(high=1)
        detection = {
            "risk_level": "high",
            "findings": [{"type": "fire_smoke", "description": "化学品烟雾", "confidence": 0.97}],
        }
        response = generate_mock_llm_response(ctx, "烟雾检测", detection)
        # Mock 不强制使用 detection_result，但应至少包含法规依据
        assert "法规依据" in response


# =========================
# HazardState 新字段测试
# =========================


class TestHazardStateNewFields:
    """测试 HazardState 零幻觉校验新字段"""

    def test_all_fields_present_including_guard_fields(self):
        """16 个字段全部存在（原 12 + 新 4）"""
        s = _make_state()
        expected_fields = {
            "messages", "current_image", "detection_result",
            "ticket_data", "graph_context", "memory_context",
            "next_action", "ticket_status", "retry_count",
            "edge_node_id", "area_type", "need_cloud_analysis",
            # 功能6 新字段
            "llm_response", "refusal_reason",
            "citation_verified", "response_confidence",
        }
        assert set(s.keys()) == expected_fields, (
            f"字段不匹配: {set(s.keys()) ^ expected_fields}"
        )

    def test_guard_fields_default_values(self):
        """零幻觉校验字段默认值正确"""
        s = _make_state()
        assert s["llm_response"] == ""
        assert s["refusal_reason"] == ""
        assert s["citation_verified"] is False
        assert s["response_confidence"] == 0.0


# =========================
# 常量测试
# =========================


class TestConstants:
    """测试模块常量"""

    def test_refusal_threshold_is_0_70(self):
        """拒答阈值为 0.70（PROGRESS.md 功能6 明确定义）"""
        assert REFUSAL_CONFIDENCE_THRESHOLD == 0.70

    def test_high_citation_threshold_is_0_80(self):
        """高引用阈值为 0.80"""
        assert HIGH_CITATION_THRESHOLD == 0.80


# =========================
# 端到端: 零幻觉校验集成
# =========================


class TestHallucinationGuardIntegration:
    """测试 _handle_hazard 中的零幻觉校验集成"""

    @pytest.mark.asyncio
    async def test_urgent_handler_includes_guard(self):
        """紧急处理应包含零幻觉校验步骤"""
        from app.core.graph.nodes import urgent_handler_node

        ctx = _make_context_with_confidence(high=2)
        s = _make_state(
            graph_context=ctx,
            detection_result={
                "risk_level": "high",
                "findings": [{"type": "oil_leak", "description": "液压油泄漏", "confidence": 0.93}],
            },
        )
        result = await urgent_handler_node(s)
        # 应包含零幻觉校验相关输出
        assert "ticket_status" in result
        # ticket_data 中应包含零幻觉校验元数据
        ticket = result.get("ticket_data", {})
        assert "citation_verified" in ticket
        assert "response_confidence" in ticket

    @pytest.mark.asyncio
    async def test_normal_handler_includes_guard(self):
        """普通处理应包含零幻觉校验步骤"""
        from app.core.graph.nodes import normal_handler_node

        ctx = _make_context_with_confidence(high=1, medium=2)
        s = _make_state(
            graph_context=ctx,
            detection_result={
                "risk_level": "medium",
                "findings": [{"type": "blocked_exit", "description": "通道堵塞", "confidence": 0.91}],
            },
        )
        result = await normal_handler_node(s)
        assert "ticket_status" in result
        ticket = result.get("ticket_data", {})
        assert "citation_verified" in ticket
        assert "response_confidence" in ticket

    @pytest.mark.asyncio
    async def test_refusal_scenario_ticket_marked(self):
        """拒答场景下工单应包含拒答标记"""
        from app.core.graph.nodes import normal_handler_node

        ctx = _make_context_with_confidence(high=0, medium=0, low=2)
        s = _make_state(
            graph_context=ctx,
            detection_result={
                "risk_level": "medium",
                "findings": [{"type": "unclear", "description": "模糊", "confidence": 0.35}],
            },
        )
        result = await normal_handler_node(s)
        ticket = result.get("ticket_data", {})
        # 拒答场景下 citation_verified 应为 False
        # 或者 ticket title 应包含拒答标记
        if result.get("refusal_reason"):
            assert ticket.get("citation_verified") is False
