"""
MCP Server 标准化模块单元测试

覆盖:
    - CircuitBreaker: 三态切换 + 熔断逻辑
    - EHSAdapter: check_permit / create_ticket
    - HRAdapter: verify_certificate
    - MESAdapter: get_equipment_status / report_downtime
    - MCPServer: 工具注册/调用/审计
    - AuditLogger: 审计日志
"""
import pytest

from app.core.mcp_server.server import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerOpenError,
    EHSAdapter,
    HRAdapter,
    MESAdapter,
    MCPServer,
    AuditLogger,
)


class TestCircuitBreaker:
    """测试熔断器"""

    def test_initial_state_closed(self):
        breaker = CircuitBreaker(name="test")
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_success_call_passes(self):
        breaker = CircuitBreaker(name="test")

        async def good(): return "ok"

        result = await breaker.call(good)
        assert result == "ok"
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_increments_count(self):
        breaker = CircuitBreaker(name="test", failure_threshold=3)

        async def bad(): raise ValueError("fail")

        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(bad)

        assert breaker.failure_count == 2
        assert breaker.state == CircuitState.CLOSED  # 未达阈值

    @pytest.mark.asyncio
    async def test_threshold_exceeded_opens_circuit(self):
        breaker = CircuitBreaker(name="test", failure_threshold=2, timeout=999)

        async def bad(): raise ValueError("fail")

        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(bad)

        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_calls(self):
        breaker = CircuitBreaker(name="test", failure_threshold=1, timeout=999)

        async def bad(): raise ValueError("fail")

        with pytest.raises(ValueError):
            await breaker.call(bad)

        assert breaker.state == CircuitState.OPEN

        async def good(): return "ok"

        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call(good)

    @pytest.mark.asyncio
    async def test_half_open_to_closed_on_success(self):
        breaker = CircuitBreaker(name="test", failure_threshold=1, timeout=0.01)

        async def bad(): raise ValueError("fail")

        with pytest.raises(ValueError):
            await breaker.call(bad)

        assert breaker.state == CircuitState.OPEN

        # 等待超时
        import asyncio
        await asyncio.sleep(0.02)

        async def good(): return "recovered"

        result = await breaker.call(good)
        assert result == "recovered"
        assert breaker.state == CircuitState.CLOSED

    def test_force_close(self):
        breaker = CircuitBreaker(name="test")
        breaker.state = CircuitState.OPEN
        breaker.failure_count = 10
        breaker.force_close()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0


class TestEHSAdapter:
    """测试 EHS 适配器"""

    @pytest.mark.asyncio
    async def test_check_valid_permit(self):
        adapter = EHSAdapter()
        result = await adapter.check_permit("PERMIT-2024-001")
        assert result["valid"] is True
        assert result["permit_type"] == "动火作业"

    @pytest.mark.asyncio
    async def test_check_expired_permit(self):
        adapter = EHSAdapter()
        result = await adapter.check_permit("PERMIT-2024-EXP")
        assert result["valid"] is False
        assert result["status"] == "expired"

    @pytest.mark.asyncio
    async def test_check_nonexistent_permit(self):
        adapter = EHSAdapter()
        result = await adapter.check_permit("NONEXISTENT")
        assert result["valid"] is False
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_create_ticket(self):
        adapter = EHSAdapter()
        result = await adapter.create_ticket("测试工单", "测试描述", priority=2)
        assert result["status"] == "created"
        assert "ticket_id" in result


class TestHRAdapter:
    """测试 HR 适配器"""

    @pytest.mark.asyncio
    async def test_verify_valid_cert(self):
        adapter = HRAdapter()
        result = await adapter.verify_certificate("EMP_001", "熔化焊接与热切割作业证")
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_verify_expired_cert(self):
        adapter = HRAdapter()
        result = await adapter.verify_certificate("EMP_004", "电工进网作业许可证")
        assert result["valid"] is False
        assert result["status"] == "expired"


class TestMESAdapter:
    """测试 MES 适配器"""

    @pytest.mark.asyncio
    async def test_get_equipment_status(self):
        adapter = MESAdapter()
        result = await adapter.get_equipment_status("EQ_HP_001")
        assert result["running_status"] == "running"
        assert result["health"] == "warning"

    @pytest.mark.asyncio
    async def test_report_downtime(self):
        adapter = MESAdapter()
        result = await adapter.report_downtime("EQ_HP_001", 4.0, "密封圈更换")
        assert result["status"] == "recorded"


class TestMCPServer:
    """测试 MCP Server"""

    @pytest.mark.asyncio
    async def test_register_and_call(self):
        server = MCPServer()
        server.register_adapter("ehs", EHSAdapter())

        result = await server.call_tool("ehs", "check_permit", {"permit_id": "PERMIT-2024-001"})
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_unknown_adapter(self):
        server = MCPServer()
        result = await server.call_tool("nonexistent", "tool", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        server = MCPServer()
        server.register_adapter("ehs", EHSAdapter())
        result = await server.call_tool("ehs", "nonexistent_tool", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_audit_logging(self):
        server = MCPServer()
        server.register_adapter("ehs", EHSAdapter())
        await server.call_tool("ehs", "check_permit", {"permit_id": "PERMIT-2024-001"})

        stats = server.audit.get_stats()
        assert stats["total"] >= 1


class TestAuditLogger:
    """测试审计日志"""

    def test_log_and_retrieve(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = AuditLogger(log_dir=tmpdir)
            audit.log("check_permit", {"permit_id": "P1"}, {"valid": True})
            audit.log("create_ticket", {"title": "T1"}, {"status": "created"})

            records = audit.get_records(hours=24)
            assert len(records) == 2

    def test_stats(self):
        audit = AuditLogger()
        audit._records.clear()
        audit.log("tool_a", {}, {"result": "ok"})
        audit.log("tool_a", {}, {"error": "fail"})

        stats = audit.get_stats()
        assert stats["total"] == 2
        assert stats["success_rate"] == 0.5
