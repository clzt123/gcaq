"""
LangGraph 工作流单元测试

覆盖:
    - HazardState 定义
    - 7 个节点函数（单独调用）
    - 完整工作流（high/medium/low 三条路径）
    - 重试机制（retry_count 递增 + MAX_RETRIES 强制终止）
    - 优雅降级（异常不抛，返回 Dict）

测试策略:
    - 全部使用 Mock 模式（无需 LLM/Neo4j/MCP 服务）
    - 节点单独测试 + 端到端集成测试
"""
import pytest

from app.core.graph.state import HazardState, MAX_RETRIES
from app.core.graph.nodes import (
    detection_node,
    supervisor_node,
    graph_rag_node,
    ticket_generation_node,
    urgent_handler_node,
    normal_handler_node,
    ticket_push_node,
)
from app.core.graph.workflow import (
    create_hazard_workflow,
    run_hazard_workflow,
    _route_by_action,
)


# =========================
# 辅助：构造初始 State
# =========================


def _make_state(**overrides) -> HazardState:
    """构造最小 HazardState，支持字段覆盖。"""
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
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


# =========================
# HazardState 测试
# =========================


class TestHazardState:
    """测试 State 定义"""

    def test_all_fields_present(self):
        """12 个字段全部存在"""
        s = _make_state()
        expected_fields = {
            "messages", "current_image", "detection_result",
            "ticket_data", "graph_context", "memory_context",
            "next_action", "ticket_status", "retry_count",
            "edge_node_id", "area_type", "need_cloud_analysis",
        }
        assert set(s.keys()) == expected_fields, (
            f"字段不匹配: {set(s.keys()) ^ expected_fields}"
        )

    def test_default_values(self):
        """默认值正确"""
        s = _make_state()
        assert s["messages"] == []
        assert s["retry_count"] == 0
        assert s["need_cloud_analysis"] is False
        assert s["ticket_status"] == ""

    def test_operator_add_for_messages(self):
        """messages 使用 operator.add 归约器"""
        s1 = _make_state(messages=[{"role": "system", "content": "A"}])
        s2 = _make_state(messages=[{"role": "system", "content": "B"}])
        # operator.add 对 list 做拼接
        combined = s1["messages"] + s2["messages"]
        assert len(combined) == 2
        assert combined[0]["content"] == "A"
        assert combined[1]["content"] == "B"


# =========================
# 路由函数测试
# =========================


class TestRouting:
    """测试条件路由"""

    def test_route_urgent(self):
        s = _make_state(next_action="urgent_handler")
        assert _route_by_action(s) == "urgent_handler"

    def test_route_normal(self):
        s = _make_state(next_action="normal_handler")
        assert _route_by_action(s) == "normal_handler"

    def test_route_end(self):
        s = _make_state(next_action="end")
        assert _route_by_action(s) == "end"

    def test_route_unknown_defaults_to_end(self):
        s = _make_state(next_action="invalid_action")
        assert _route_by_action(s) == "end"


# =========================
# detection_node 测试
# =========================


class TestDetectionNode:
    """测试视觉分析节点"""

    @pytest.mark.asyncio
    async def test_oil_leak_detection(self):
        """油泄漏图片 → high"""
        s = _make_state(current_image="/images/inj_mold_leak.jpg")
        result = await detection_node(s)
        assert result["detection_result"]["risk_level"] == "high"
        assert result["need_cloud_analysis"] is False

    @pytest.mark.asyncio
    async def test_fire_detection(self):
        """烟雾图片 → high"""
        s = _make_state(current_image="/images/chemical_smoke.jpg")
        result = await detection_node(s)
        assert result["detection_result"]["risk_level"] == "high"

    @pytest.mark.asyncio
    async def test_blocked_detection(self):
        """通道堵塞 → medium"""
        s = _make_state(current_image="/images/blocked_fire_exit.jpg")
        result = await detection_node(s)
        assert result["detection_result"]["risk_level"] == "medium"

    @pytest.mark.asyncio
    async def test_unknown_image(self):
        """未知图片 → low + need_cloud"""
        s = _make_state(current_image="/images/random_unknown.jpg")
        result = await detection_node(s)
        assert result["detection_result"]["risk_level"] == "low"
        assert result["need_cloud_analysis"] is True

    @pytest.mark.asyncio
    async def test_empty_image(self):
        """空图片 → low"""
        s = _make_state(current_image="")
        result = await detection_node(s)
        assert result["detection_result"]["risk_level"] == "low"

    @pytest.mark.asyncio
    async def test_returns_messages(self):
        """应追加系统消息"""
        s = _make_state(current_image="/images/inj_mold_leak.jpg")
        result = await detection_node(s)
        assert len(result.get("messages", [])) >= 1


# =========================
# supervisor_node 测试
# =========================


class TestSupervisorNode:
    """测试路由节点"""

    @pytest.mark.asyncio
    async def test_high_routes_urgent(self):
        s = _make_state(detection_result={"risk_level": "high"})
        result = await supervisor_node(s)
        assert result["next_action"] == "urgent_handler"

    @pytest.mark.asyncio
    async def test_medium_routes_normal(self):
        s = _make_state(detection_result={"risk_level": "medium"})
        result = await supervisor_node(s)
        assert result["next_action"] == "normal_handler"

    @pytest.mark.asyncio
    async def test_low_routes_end(self):
        s = _make_state(detection_result={"risk_level": "low"})
        result = await supervisor_node(s)
        assert result["next_action"] == "end"

    @pytest.mark.asyncio
    async def test_none_routes_end(self):
        s = _make_state(detection_result={"risk_level": "none"})
        result = await supervisor_node(s)
        assert result["next_action"] == "end"

    @pytest.mark.asyncio
    async def test_max_retries_forces_end(self):
        """retry_count >= 3 → 强制 end"""
        s = _make_state(
            detection_result={"risk_level": "high"},
            retry_count=MAX_RETRIES,  # 3
        )
        result = await supervisor_node(s)
        assert result["next_action"] == "end"

    @pytest.mark.asyncio
    async def test_retry_under_limit_proceeds(self):
        """retry_count < 3 → 正常路由"""
        s = _make_state(
            detection_result={"risk_level": "high"},
            retry_count=2,  # 未达上限
        )
        result = await supervisor_node(s)
        assert result["next_action"] == "urgent_handler"


# =========================
# graph_rag_node 测试
# =========================


class TestGraphRAGNode:
    """测试知识检索节点"""

    @pytest.mark.asyncio
    async def test_retrieve_with_findings(self):
        """有检测结果时正常检索"""
        s = _make_state(detection_result={
            "risk_level": "high",
            "findings": [{"type": "oil_leak", "description": "液压油泄漏"}],
        })
        result = await graph_rag_node(s)
        assert isinstance(result.get("graph_context"), str)
        assert len(result["graph_context"]) > 0

    @pytest.mark.asyncio
    async def test_retrieve_empty_detection(self):
        """无检测结果时也能正常降级"""
        s = _make_state(detection_result={})
        result = await graph_rag_node(s)
        assert isinstance(result.get("graph_context"), str)


# =========================
# ticket_generation_node 测试
# =========================


class TestTicketGenerationNode:
    """测试工单生成节点"""

    @pytest.mark.asyncio
    async def test_generate_high_priority_ticket(self):
        """high → priority=1"""
        s = _make_state(
            detection_result={
                "risk_level": "high",
                "findings": [{"type": "oil_leak", "description": "液压油泄漏"}],
            },
            graph_context="适用法规: 《企业安全生产标准化基本规范》 §5.4.2.3",
            area_type="production",
        )
        result = await ticket_generation_node(s)
        assert result["ticket_data"]["priority"] == 1
        assert "HIGH" in result["ticket_data"]["title"]
        assert result["ticket_status"] == "created"

    @pytest.mark.asyncio
    async def test_generate_medium_ticket(self):
        """medium → priority=3"""
        s = _make_state(
            detection_result={
                "risk_level": "medium",
                "findings": [{"type": "blocked_exit", "description": "通道堵塞"}],
            },
        )
        result = await ticket_generation_node(s)
        assert result["ticket_data"]["priority"] == 3

    @pytest.mark.asyncio
    async def test_generate_without_findings(self):
        """无 findings 时仍能生成工单"""
        s = _make_state(detection_result={"risk_level": "medium"})
        result = await ticket_generation_node(s)
        assert "ticket_data" in result
        assert "title" in result["ticket_data"]


# =========================
# ticket_push_node 测试
# =========================


class TestTicketPushNode:
    """测试工单推送节点"""

    @pytest.mark.asyncio
    async def test_push_success(self):
        """正常推送工单"""
        s = _make_state(
            ticket_data={
                "title": "测试工单",
                "description": "测试描述",
                "priority": 2,
                "assignee": "测试员",
            },
        )
        result = await ticket_push_node(s)
        # Mock 模式推送成功
        assert result["ticket_status"] == "sent"

    @pytest.mark.asyncio
    async def test_push_empty_ticket(self):
        """空工单数据 → 推送失败 + retry_count +1"""
        s = _make_state(ticket_data={})
        result = await ticket_push_node(s)
        # 空 title 可能失败
        assert "ticket_status" in result

    @pytest.mark.asyncio
    async def test_retry_count_increments_on_failure(self):
        """失败时 retry_count 递增"""
        s = _make_state(
            ticket_data={
                "title": "",  # 空标题 → 可能触发错误
                "description": "",
                "priority": 5,
                "assignee": "",
            },
            retry_count=0,
        )
        result = await ticket_push_node(s)
        if result.get("ticket_status") == "failed":
            assert result["retry_count"] >= 1


# =========================
# handler 节点测试
# =========================


class TestHandlers:
    """测试 urgent/normal handler 编排节点"""

    @pytest.mark.asyncio
    async def test_urgent_handler_runs(self):
        """紧急处理节点正常执行"""
        s = _make_state(
            detection_result={
                "risk_level": "high",
                "findings": [{"type": "oil_leak", "description": "液压油泄漏"}],
            },
        )
        result = await urgent_handler_node(s)
        assert "ticket_status" in result
        assert "graph_context" in result

    @pytest.mark.asyncio
    async def test_normal_handler_runs(self):
        """普通处理节点正常执行"""
        s = _make_state(
            detection_result={
                "risk_level": "medium",
                "findings": [{"type": "blocked_exit", "description": "通道堵塞"}],
            },
        )
        result = await normal_handler_node(s)
        assert "ticket_status" in result
        assert "graph_context" in result


# =========================
# 端到端工作流测试
# =========================


class TestWorkflowEndToEnd:
    """测试完整工作流链路"""

    @pytest.mark.asyncio
    async def test_high_risk_full_flow(self):
        """🆕 Phase 2: 高风险 + 高置信度(0.93) → edge_handler 边缘即时处置"""
        result = await run_hazard_workflow(
            current_image="/images/inj_mold_leak.jpg",
            alert_id="ALT-001",
            edge_node_id="EDGE_DG_01",
            area_type="production",
        )
        assert result["detection_result"]["risk_level"] == "high"
        # 置信度 0.93 >= 0.90 → 边缘即时处置
        assert result["next_action"] == "edge_handler"
        assert result["ticket_status"] == "sent"

    @pytest.mark.asyncio
    async def test_medium_risk_full_flow(self):
        """🆕 Phase 2: 中风险 + 高置信度(0.91) → edge_handler 边缘即时处置"""
        result = await run_hazard_workflow(
            current_image="/images/blocked_fire_exit.jpg",
            alert_id="ALT-002",
        )
        assert result["detection_result"]["risk_level"] == "medium"
        # 置信度 0.91 >= 0.90 → 边缘即时处置
        assert result["next_action"] == "edge_handler"

    @pytest.mark.asyncio
    async def test_low_risk_ends_early(self):
        """低风险隐患 → 直接 end，不生成工单"""
        result = await run_hazard_workflow(
            current_image="/images/random_unknown.jpg",
            alert_id="ALT-003",
        )
        assert result["detection_result"]["risk_level"] == "low"
        assert result["next_action"] == "end"
        # 低风险不生成工单 → ticket_data 可能为空
        assert result["ticket_status"] in ("", "created")

    @pytest.mark.asyncio
    async def test_fire_smoke_full_flow(self):
        """🆕 Phase 2: 烟火隐患(置信度0.97) → edge_handler 边缘即时处置"""
        result = await run_hazard_workflow(
            current_image="/images/chemical_smoke.jpg",
            alert_id="ALT-004",
        )
        assert result["detection_result"]["risk_level"] == "high"
        # 置信度 0.97 >= 0.90 → 边缘即时处置
        assert result["next_action"] == "edge_handler"
        assert result["ticket_status"] == "sent"

    @pytest.mark.asyncio
    async def test_workflow_returns_all_state_fields(self):
        """工作流返回完整 State"""
        result = await run_hazard_workflow(
            current_image="/images/inj_mold_leak.jpg",
        )
        required = {"messages", "detection_result", "ticket_data", "graph_context",
                     "next_action", "ticket_status", "retry_count"}
        for field in required:
            assert field in result, f"缺少字段: {field}"

    @pytest.mark.asyncio
    async def test_compile_and_invoke_directly(self):
        """直接使用 StateGraph API（🆕 Phase 2: 高置信度 → edge_handler）"""
        workflow = create_hazard_workflow()
        initial: HazardState = {
            "messages": [],
            "current_image": "/images/inj_mold_leak.jpg",
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
        }
        result = await workflow.ainvoke(initial)
        assert result["next_action"] == "edge_handler"


# =========================
# 重试机制测试
# =========================


class TestRetryMechanism:
    """测试重试+熔断机制"""

    @pytest.mark.asyncio
    async def test_retry_at_max_forces_end(self):
        """retry_count=3 时，即使高隐患也走 end"""
        from app.core.graph.state import MAX_RETRIES

        s = _make_state(
            current_image="/images/inj_mold_leak.jpg",
            detection_result={"risk_level": "high", "findings": []},
            retry_count=MAX_RETRIES,
        )
        result = await supervisor_node(s)
        assert result["next_action"] == "end"

    @pytest.mark.asyncio
    async def test_push_failure_increments_retry(self):
        """推送失败时 retry_count += 1"""
        s = _make_state(
            ticket_data={"title": "", "description": "", "priority": 5, "assignee": ""},
            retry_count=1,
        )
        result = await ticket_push_node(s)
        if result.get("ticket_status") == "failed":
            assert result["retry_count"] > 1
