"""
MCP Server 标准化协议实现

实现技术方案功能 13 + 19：
    13. 标准 MCP Server 协议 + 动火证实时验证 + 审计日志
    19. EHS/HR/MES 独立适配器 + Hystrix 熔断器模式

熔断器状态机:
    CLOSED → (failures >= threshold) → OPEN
    OPEN   → (timeout elapsed)        → HALF_OPEN
    HALF_OPEN → (success)             → CLOSED
    HALF_OPEN → (failure)             → OPEN

使用方式:
    breaker = CircuitBreaker(failure_threshold=5, timeout=60)
    adapter = EHSAdapter(breaker)
    result = await adapter.check_permit("PERMIT-001")
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# =========================
# 熔断器
# =========================


class CircuitState(str, Enum):
    """熔断器状态"""
    CLOSED = "closed"           # 正常
    OPEN = "open"               # 熔断
    HALF_OPEN = "half_open"     # 半开（探测恢复）


@dataclass
class CircuitBreaker:
    """
    Hystrix 风格熔断器。

    三态切换逻辑:
        - CLOSED: 正常计数失败。达到 failure_threshold → OPEN
        - OPEN: 拒绝所有请求。timeout 秒后 → HALF_OPEN
        - HALF_OPEN: 允许探测请求。成功 → CLOSED；失败 → OPEN

    Attributes:
        failure_threshold: 失败次数阈值
        timeout: OPEN→HALF_OPEN 的超时秒数
        half_open_max_requests: HALF_OPEN 状态下允许的探测请求数
    """

    name: str
    failure_threshold: int = 5
    timeout: float = 60.0
    half_open_max_requests: int = 3

    # 状态追踪
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    last_state_change: float = field(default_factory=time.time)
    half_open_requests: int = 0

    def __post_init__(self):
        self.last_state_change = time.time()

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        通过熔断器调用函数。

        Args:
            func: 异步可调用对象
            *args, **kwargs: 传递给 func 的参数

        Returns:
            func 的返回值

        Raises:
            CircuitBreakerOpenError: 熔断器开启时
            原函数的异常
        """
        # 状态检查
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._transition_to(CircuitState.HALF_OPEN)
            else:
                raise CircuitBreakerOpenError(
                    f"[{self.name}] 熔断器开启中，"
                    f"剩余 {self._remaining_open_seconds():.0f} 秒"
                )

        # HALF_OPEN 限流
        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_requests >= self.half_open_max_requests:
                raise CircuitBreakerOpenError(
                    f"[{self.name}] 半开状态探测请求已达上限"
                )
            self.half_open_requests += 1

        # 执行调用
        try:
            result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        """调用成功回调。"""
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            logger.info(f"[{self.name}] HALF_OPEN 探测成功 → CLOSED")
            self._transition_to(CircuitState.CLOSED)

    def _on_failure(self):
        """调用失败回调。"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            logger.warning(f"[{self.name}] HALF_OPEN 探测失败 → OPEN")
            self._transition_to(CircuitState.OPEN)
        elif self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
            logger.warning(
                f"[{self.name}] 失败 {self.failure_count}/{self.failure_threshold} → OPEN"
            )
            self._transition_to(CircuitState.OPEN)

    def _transition_to(self, new_state: CircuitState):
        """状态切换。"""
        old = self.state
        self.state = new_state
        self.last_state_change = time.time()
        self.half_open_requests = 0

        # 更新全局监控指标
        try:
            from app.core.observability.metrics import MetricsCollector
            state_map = {CircuitState.CLOSED: 0, CircuitState.OPEN: 1, CircuitState.HALF_OPEN: 2}
            MetricsCollector.get_instance().set_gauge(
                "safeguard_circuit_breaker_state",
                state_map.get(new_state, 0),
                {"breaker": self.name},
            )
        except ImportError:
            pass

    def _should_attempt_reset(self) -> bool:
        """检查是否应该尝试重连（OPEN → HALF_OPEN）。"""
        return (time.time() - self.last_state_change) >= self.timeout

    def _remaining_open_seconds(self) -> float:
        """距离 HALF_OPEN 还剩多少秒。"""
        elapsed = time.time() - self.last_state_change
        return max(0.0, self.timeout - elapsed)

    def force_close(self):
        """强制重置熔断器（仅测试用）。"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.half_open_requests = 0
        self.last_state_change = time.time()


class CircuitBreakerOpenError(Exception):
    """熔断器开启异常"""
    pass


# =========================
# MCP 适配器基类
# =========================


class BaseAdapter:
    """MCP 适配器基类 — 定义标准的工具接口。"""

    def __init__(self, name: str, breaker: Optional[CircuitBreaker] = None):
        self.name = name
        self.breaker = breaker or CircuitBreaker(name=name)
        self._call_count = 0
        self._error_count = 0

    async def _safe_call(self, func: Callable, *args, **kwargs) -> Any:
        """通过熔断器安全调用。"""
        self._call_count += 1
        try:
            return await self.breaker.call(func, *args, **kwargs)
        except CircuitBreakerOpenError:
            self._error_count += 1
            raise
        except Exception as e:
            self._error_count += 1
            raise


# =========================
# EHS 适配器（环境健康安全）
# =========================


class EHSAdapter(BaseAdapter):
    """
    EHS 系统适配器。

    对接企业 EHS 管理系统，提供：
        - check_permit: 动火证/特种作业证实时验证
        - create_ticket: 创建隐患工单
        - get_equipment_status: 获取设备安全状态
    """

    def __init__(self, breaker: Optional[CircuitBreaker] = None):
        super().__init__("EHSAdapter", breaker)

    async def check_permit(self, permit_id: str) -> Dict[str, Any]:
        """
        动火证/特种作业证实时验证。

        Args:
            permit_id: 许可证编号

        Returns:
            验证结果
        """
        return await self._safe_call(self._check_permit_impl, permit_id)

    async def _check_permit_impl(self, permit_id: str) -> Dict[str, Any]:
        """check_permit 真实实现（Mock）。"""
        logger.info(f"[EHS] 验证许可证: {permit_id}")

        # Mock 验证逻辑
        valid_permits = {
            "PERMIT-2024-001": {"type": "动火作业", "status": "valid", "expiry": "2026-06-15"},
            "PERMIT-2024-002": {"type": "受限空间", "status": "valid", "expiry": "2026-06-20"},
            "PERMIT-2024-EXP": {"type": "动火作业", "status": "expired", "expiry": "2026-05-01"},
        }

        if permit_id in valid_permits:
            permit = valid_permits[permit_id]
            return {
                "permit_id": permit_id,
                "valid": permit["status"] == "valid",
                "permit_type": permit["type"],
                "status": permit["status"],
                "expiry_date": permit["expiry"],
                "message": (
                    "许可证有效" if permit["status"] == "valid"
                    else "许可证已过期"
                ),
            }
        else:
            return {
                "permit_id": permit_id,
                "valid": False,
                "status": "not_found",
                "message": "许可证不存在",
            }

    async def create_ticket(self, title: str, description: str,
                           priority: int = 3, assignee: str = "") -> Dict[str, Any]:
        """创建 EHS 工单。"""
        return await self._safe_call(
            self._create_ticket_impl, title, description, priority, assignee
        )

    async def _create_ticket_impl(self, title: str, description: str,
                                  priority: int, assignee: str) -> Dict[str, Any]:
        logger.info(f"[EHS] 创建工单: {title}")
        return {
            "ticket_id": f"EHS-TKT-{int(time.time())}",
            "title": title,
            "status": "created",
            "priority": priority,
            "assignee": assignee or "待分配",
            "created_at": datetime.now().isoformat(),
        }


# =========================
# HR 适配器（人力资源）
# =========================


class HRAdapter(BaseAdapter):
    """
    HR 系统适配器。

    对接企业 HR 管理系统，提供：
        - verify_certificate: 员工资质验证
        - get_employee_info: 获取员工信息
        - sync_cert_expiry: 同步证书过期状态
    """

    def __init__(self, breaker: Optional[CircuitBreaker] = None):
        super().__init__("HRAdapter", breaker)

    async def verify_certificate(self, employee_id: str, cert_type: str) -> Dict[str, Any]:
        """验证员工资质。"""
        return await self._safe_call(self._verify_cert_impl, employee_id, cert_type)

    async def _verify_cert_impl(self, employee_id: str, cert_type: str) -> Dict[str, Any]:
        logger.info(f"[HR] 验证资质: {employee_id}/{cert_type}")

        # Mock 验证
        mock_certs = {
            ("EMP_001", "熔化焊接与热切割作业证"): {
                "valid": True, "expiry": "2029-06-01", "status": "valid",
            },
            ("EMP_004", "电工进网作业许可证"): {
                "valid": False, "expiry": "2026-05-15", "status": "expired",
            },
        }

        key = (employee_id, cert_type)
        if key in mock_certs:
            cert = mock_certs[key]
            return {
                "employee_id": employee_id,
                "cert_type": cert_type,
                "valid": cert["valid"],
                "status": cert["status"],
                "expiry_date": cert["expiry"],
                "message": "资质有效" if cert["valid"] else "资质已过期",
            }

        return {
            "employee_id": employee_id,
            "cert_type": cert_type,
            "valid": False,
            "status": "not_found",
            "message": "未找到该资质记录",
        }

    async def get_employee_info(self, employee_id: str) -> Dict[str, Any]:
        """获取员工信息。"""
        return await self._safe_call(self._get_emp_impl, employee_id)

    async def _get_emp_impl(self, employee_id: str) -> Dict[str, Any]:
        logger.info(f"[HR] 查询员工: {employee_id}")
        return {
            "employee_id": employee_id,
            "status": "active",
            "sync_time": datetime.now().isoformat(),
        }


# =========================
# MES 适配器（制造执行系统）
# =========================


class MESAdapter(BaseAdapter):
    """
    MES 系统适配器。

    对接企业 MES 系统，提供：
        - get_equipment_status: 获取设备运行状态
        - get_maintenance_schedule: 获取维保计划
        - report_downtime: 上报停机事件
    """

    def __init__(self, breaker: Optional[CircuitBreaker] = None):
        super().__init__("MESAdapter", breaker)

    async def get_equipment_status(self, equipment_id: str) -> Dict[str, Any]:
        """获取设备运行状态。"""
        return await self._safe_call(self._get_equip_status_impl, equipment_id)

    async def _get_equip_status_impl(self, equipment_id: str) -> Dict[str, Any]:
        logger.info(f"[MES] 查询设备状态: {equipment_id}")

        # Mock 数据
        mock_status = {
            "EQ_HP_001": {"status": "running", "health": "warning", "next_maintenance": "2026-06-15"},
            "EQ_CP_002": {"status": "running", "health": "good", "next_maintenance": "2026-11-15"},
            "EQ_PV_003": {"status": "running", "health": "maintenance_due", "next_maintenance": "2026-06-08"},
        }

        if equipment_id in mock_status:
            status = mock_status[equipment_id]
            return {
                "equipment_id": equipment_id,
                "running_status": status["status"],
                "health": status["health"],
                "next_maintenance": status["next_maintenance"],
                "message": f"设备状态: {status['health']}",
            }

        return {
            "equipment_id": equipment_id,
            "running_status": "unknown",
            "health": "unknown",
            "message": "设备未在 MES 中注册",
        }

    async def report_downtime(self, equipment_id: str, hours: float,
                             reason: str = "") -> Dict[str, Any]:
        """上报停机事件。"""
        return await self._safe_call(self._report_downtime_impl, equipment_id, hours, reason)

    async def _report_downtime_impl(self, equipment_id: str, hours: float,
                                    reason: str) -> Dict[str, Any]:
        logger.info(f"[MES] 上报停机: {equipment_id}, {hours}h")
        return {
            "event_id": f"DT-{int(time.time())}",
            "equipment_id": equipment_id,
            "downtime_hours": hours,
            "reason": reason,
            "reported_at": datetime.now().isoformat(),
            "status": "recorded",
        }


# =========================
# MCP Server 协议框架
# =========================


class AuditLogger:
    """
    审计日志记录器。

    持久化所有 MCP 工具调用记录到 t_ticket_audit 表。

    使用方式:
        audit = AuditLogger()
        audit.log("check_permit", {"permit_id": "xxx"}, result)
        records = audit.get_records(hours=24)
    """

    def __init__(self, log_dir=None):
        if log_dir is None:
            log_dir = Path(__file__).parent.parent.parent.parent / "logs"
        else:
            log_dir = Path(log_dir)
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._records: List[Dict[str, Any]] = []

    def log(self, tool_name: str, params: Dict[str, Any], result: Dict[str, Any]):
        """记录一次工具调用。"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
            "params": params,
            "result": result,
            "success": "error" not in result,
        }
        self._records.append(record)

        # 写入审计日志文件
        try:
            log_file = self.log_dir / f"audit_{datetime.now().strftime('%Y%m%d')}.jsonl"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"[Audit] 写入审计日志失败: {e}")

    def get_records(self, hours: int = 24) -> List[Dict[str, Any]]:
        """获取最近 N 小时的审计记录。"""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            r for r in self._records
            if datetime.fromisoformat(r["timestamp"]) >= cutoff
        ]

    def get_stats(self) -> Dict[str, Any]:
        """审计统计。"""
        if not self._records:
            return {"total": 0}

        tools = {}
        success = 0
        for r in self._records:
            tools[r["tool"]] = tools.get(r["tool"], 0) + 1
            if r["success"]:
                success += 1

        return {
            "total": len(self._records),
            "success_rate": round(success / len(self._records), 4),
            "by_tool": tools,
        }


class MCPServer:
    """
    MCP Server 协议框架。

    管理多个适配器并提供统一的工具调用接口。
    所有调用均经过熔断器保护并记录审计日志。

    使用方式:
        server = MCPServer()
        server.register_adapter("ehs", EHSAdapter())
        result = await server.call_tool("ehs", "check_permit", {"permit_id": "xxx"})
    """

    def __init__(self):
        self._adapters: Dict[str, BaseAdapter] = {}
        self._audit = AuditLogger()

    @property
    def audit(self) -> AuditLogger:
        return self._audit

    def register_adapter(self, name: str, adapter: BaseAdapter):
        """注册适配器。"""
        self._adapters[name] = adapter
        logger.info(f"[MCPServer] 注册适配器: {name}")

    def get_adapter(self, name: str) -> Optional[BaseAdapter]:
        """获取适配器。"""
        return self._adapters.get(name)

    async def call_tool(self, adapter_name: str, tool_name: str,
                        params: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用 MCP 工具。

        Args:
            adapter_name: 适配器名称
            tool_name: 工具名称
            params: 工具参数

        Returns:
            工具执行结果
        """
        adapter = self._adapters.get(adapter_name)
        if not adapter:
            result = {"error": f"适配器不存在: {adapter_name}"}
            self._audit.log(f"{adapter_name}.{tool_name}", params, result)
            return result

        method = getattr(adapter, tool_name, None)
        if not method:
            result = {"error": f"工具不存在: {adapter_name}.{tool_name}"}
            self._audit.log(f"{adapter_name}.{tool_name}", params, result)
            return result

        try:
            result = await method(**params)
            self._audit.log(f"{adapter_name}.{tool_name}", params, result)
            return result
        except CircuitBreakerOpenError as e:
            result = {"error": str(e), "circuit_open": True}
            self._audit.log(f"{adapter_name}.{tool_name}", params, result)
            return result
        except Exception as e:
            result = {"error": str(e)}
            self._audit.log(f"{adapter_name}.{tool_name}", params, result)
            return result
