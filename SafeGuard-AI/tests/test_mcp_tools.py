"""
MCP 工具层单元测试

覆盖全部 5 个 MCP 工具函数：
    - create_ehs_ticket
    - verify_certificate
    - get_equipment_status
    - log_false_positive
    - edge_pre_screen

测试原则：
    - 使用 Mock 数据，不依赖外部服务
    - 通过 StructuredTool.ainvoke() 调用（LangChain @tool 标准接口）
    - 覆盖正常路径与异常降级路径
"""
import pytest

from app.tools.mcp_tools import (
    create_ehs_ticket,
    verify_certificate,
    get_equipment_status,
    log_false_positive,
    edge_pre_screen,
    get_system_health,
    get_all_tools,
    get_tool_by_name,
    _reload_mock_data,
    MCP_TOOLS,
    EDGE_TOOLS,
    CLOUD_TOOLS,
)


# =========================
# Fixtures
# =========================


@pytest.fixture(autouse=True)
def _reset_mock_data():
    """每个测试前重新加载 Mock 数据，确保测试隔离。"""
    _reload_mock_data()


# =========================
# 工具注册表测试
# =========================


class TestToolRegistry:
    """测试工具注册表功能"""

    def test_all_tools_registered(self):
        """验证 6 个工具已全部注册（🆕 Phase 2: +get_system_health）"""
        tools = get_all_tools()
        tool_names = {t.name for t in tools}
        expected = {
            "create_ehs_ticket",
            "verify_certificate",
            "get_equipment_status",
            "log_false_positive",
            "edge_pre_screen",
            "get_system_health",
        }
        assert tool_names == expected, f"工具注册表不完整: {tool_names}"

    def test_get_tool_by_name_exist(self):
        """按名称查找已注册工具"""
        tool = get_tool_by_name("create_ehs_ticket")
        assert tool is not None
        assert tool.name == "create_ehs_ticket"

    def test_get_tool_by_name_not_exist(self):
        """查找不存在的工具返回 None"""
        tool = get_tool_by_name("non_existent_tool")
        assert tool is None

    def test_mcp_tools_list_not_empty(self):
        """MCP_TOOLS 列表非空"""
        assert len(MCP_TOOLS) == 6


# =========================
# create_ehs_ticket 测试
# =========================


class TestCreateEHSTicket:
    """测试 create_ehs_ticket 工具"""

    @pytest.mark.asyncio
    async def test_create_ticket_success(self):
        """正常创建工单，返回包含 ticket_id、status 的完整响应"""
        result = await create_ehs_ticket.ainvoke({
            "title": "测试工单-液压油泄漏",
            "description": "3号注塑机下方发现油渍",
            "priority": 2,
            "assignee": "王建国",
        })

        assert "error" not in result, f"不应包含错误: {result}"
        assert result.get("ticket_id") == "EHS-20240520-089"
        assert result.get("status") == "Created"
        assert result.get("assigned_to") == "设备维修组-王建国"
        assert result.get("input_title") == "测试工单-液压油泄漏"
        assert result.get("input_priority") == 2

    @pytest.mark.asyncio
    async def test_create_ticket_long_description_compression(self):
        """description > 2000 字符时自动截断"""
        long_desc = "X" * 2500
        result = await create_ehs_ticket.ainvoke({
            "title": "长描述测试",
            "description": long_desc,
            "priority": 3,
            "assignee": "测试员",
        })

        assert "error" not in result
        assert result.get("ticket_id") == "EHS-20240520-089"

    @pytest.mark.asyncio
    async def test_create_ticket_minimal(self):
        """最小参数创建工单（无 evidence_image）"""
        result = await create_ehs_ticket.ainvoke({
            "title": "最小工单",
            "description": "简要描述",
            "priority": 5,
            "assignee": "测试员",
        })

        assert "error" not in result
        assert result.get("priority") == "High"

    @pytest.mark.asyncio
    async def test_create_ticket_with_image(self):
        """带现场图片创建工单"""
        result = await create_ehs_ticket.ainvoke({
            "title": "带图工单",
            "description": "描述",
            "priority": 1,
            "assignee": "紧急组",
            "evidence_image": "base64_encoded_image_data",
        })

        assert "error" not in result
        assert result.get("ticket_id") == "EHS-20240520-089"


# =========================
# verify_certificate 测试
# =========================


class TestVerifyCertificate:
    """测试 verify_certificate 工具"""

    @pytest.mark.asyncio
    async def test_verify_qualified(self):
        """验证合格员工资质"""
        result = await verify_certificate.ainvoke({
            "employee_id": "EMP-8842",
            "required_type": "高压管路维修",
        })

        assert "error" not in result
        assert result.get("is_qualified") is True
        assert result.get("name") == "王建国"
        assert result.get("cert_expiry") == "2027-12-31"

    @pytest.mark.asyncio
    async def test_verify_with_expiry_date(self):
        """证书包含到期日字段"""
        result = await verify_certificate.ainvoke({
            "employee_id": "EMP-8842",
            "required_type": "welder",
        })

        assert "error" not in result
        assert "cert_expiry" in result
        assert isinstance(result.get("is_qualified"), bool)


# =========================
# get_equipment_status 测试
# =========================


class TestGetEquipmentStatus:
    """测试 get_equipment_status 工具"""

    @pytest.mark.asyncio
    async def test_get_status_success(self):
        """正常查询设备状态"""
        result = await get_equipment_status.ainvoke({
            "equipment_id": "EQ-SMT-A-003",
        })

        assert "error" not in result
        assert result.get("status") == "Running"
        assert result.get("equipment_id") == "EQ-SMT-A-003"
        assert result.get("runtime_hours") == 1985

    @pytest.mark.asyncio
    async def test_maintenance_warning(self):
        """运行时长 1985h >= 1900 大修阈值时发出预警"""
        result = await get_equipment_status.ainvoke({
            "equipment_id": "EQ-SMT-A-003",
        })

        assert "runtime_warning" in result, (
            f"运行时长 {result.get('runtime_hours')}h 应触发大修预警"
        )

    @pytest.mark.asyncio
    async def test_returns_all_required_fields(self):
        """返回所有必要字段"""
        result = await get_equipment_status.ainvoke({
            "equipment_id": "EQ-SMT-A-003",
        })

        for field in ("status", "runtime_hours", "last_maintenance", "next_maintenance_due"):
            assert field in result, f"缺少必要字段: {field}"


# =========================
# log_false_positive 测试
# =========================


class TestLogFalsePositive:
    """测试 log_false_positive 工具"""

    @pytest.mark.asyncio
    async def test_log_false_positive_success(self):
        """正常记录误报反馈"""
        result = await log_false_positive.ainvoke({
            "emp_id": "EMP-1001",
            "image_id": "IMG-20240520-042",
            "feedback_type": "false_positive",
            "comment": "此区域为装饰性反光条，并非真实油渍。",
        })

        assert "error" not in result
        assert result.get("status") == "recorded"
        assert "log_id" in result
        assert result.get("feedback_type") == "false_positive"

    @pytest.mark.asyncio
    async def test_log_irrelevant_feedback(self):
        """记录不相关反馈"""
        result = await log_false_positive.ainvoke({
            "emp_id": "EMP-2002",
            "image_id": "IMG-20240520-099",
            "feedback_type": "irrelevant",
            "comment": "此监控区域已停用。",
        })

        assert "error" not in result
        assert result.get("status") == "recorded"
        assert result.get("feedback_type") == "irrelevant"

    @pytest.mark.asyncio
    async def test_invalid_feedback_type_rejected(self):
        """无效的 feedback_type 被拒绝"""
        result = await log_false_positive.ainvoke({
            "emp_id": "EMP-1001",
            "image_id": "IMG-001",
            "feedback_type": "invalid_type",
            "comment": "test",
        })

        assert result.get("status") == "rejected"
        assert "error" in result


# =========================
# edge_pre_screen 测试
# =========================


class TestEdgePreScreen:
    """测试 edge_pre_screen 工具"""

    @pytest.mark.asyncio
    async def test_no_image_triggers_cloud(self):
        """无图像数据时返回中等置信度 → 触发云端精算"""
        result = await edge_pre_screen.ainvoke({"image_chunk": None})

        assert result.get("status") == "pending_cloud"
        assert result.get("need_cloud_analysis") is True
        assert 0.7 <= result.get("confidence", 0) <= 0.95

    @pytest.mark.asyncio
    async def test_with_image_high_confidence(self):
        """有图像数据时返回高置信度 → 直接判定"""
        result = await edge_pre_screen.ainvoke({
            "image_chunk": "mock_base64_image_data",
            "model_type": "yolov10n",
        })

        assert result.get("status") == "edge_resolved"
        assert result.get("need_cloud_analysis") is False
        assert result.get("confidence", 0) > 0.95

    @pytest.mark.asyncio
    async def test_custom_model_type(self):
        """使用自定义模型类型"""
        result = await edge_pre_screen.ainvoke({
            "image_chunk": "data",
            "model_type": "yolov8s",
        })

        assert result.get("model_type") == "yolov8s"


# =========================
# 异常降级测试
# =========================


class TestGracefulDegradation:
    """测试外部工具调用失败时的优雅降级"""

    @pytest.mark.asyncio
    async def test_verify_certificate_returns_result_structure(self):
        """资质验证应始终返回包含 is_qualified 的 dict"""
        result = await verify_certificate.ainvoke({
            "employee_id": "EMP-9999",
            "required_type": "unknown",
        })

        assert "is_qualified" in result
        assert "name" in result

    @pytest.mark.asyncio
    async def test_get_equipment_status_unknown_id(self):
        """查询不存在设备时仍返回有效 dict（兜底行为）"""
        result = await get_equipment_status.ainvoke({
            "equipment_id": "NON-EXISTENT-EQ",
        })

        assert "status" in result

    @pytest.mark.asyncio
    async def test_all_tools_return_dict(self):
        """
        验证所有工具都返回 dict 类型（而非异常抛出），
        确保 LangGraph 节点调用时不会因异常中断整个工作流。
        """
        test_cases = [
            (create_ehs_ticket, {
                "title": "test",
                "description": "test",
                "priority": 1,
                "assignee": "test",
            }),
            (verify_certificate, {
                "employee_id": "EMP-0001",
                "required_type": "test",
            }),
            (get_equipment_status, {"equipment_id": "EQ-0001"}),
            (log_false_positive, {
                "emp_id": "E001",
                "image_id": "I001",
                "feedback_type": "false_positive",
                "comment": "test",
            }),
            (edge_pre_screen, {"image_chunk": None}),
        ]

        for tool_func, kwargs in test_cases:
            result = await tool_func.ainvoke(kwargs)
            assert isinstance(result, dict), (
                f"工具 '{tool_func.name}' 应返回 dict，实际返回 {type(result)}"
            )
