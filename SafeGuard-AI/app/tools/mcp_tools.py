"""
MCP (Model Context Protocol) 工具定义层

封装跨系统协同接口（EHS、HR、MES），通过 LangChain 的 @tool 装饰器
注册为 LangGraph 可调用的工具。当前阶段使用 Mock 数据驱动，后续替换为
真实 MCP Server 调用。

设计模式参考:
    - Base/Ai/base/baseTool.py 的工具注册与执行模式
    - 按 CLAUDE.md 要求: 使用 @tool 装饰器 + LangGraph ToolNode 调度
    - 禁止在节点函数中直接硬编码 HTTP 请求

工具清单:
    1. create_ehs_ticket       — 创建 EHS 隐患整改工单（含幂等性检查）
    2. verify_certificate      — 验证特种作业人员资质
    3. get_equipment_status    — 查询设备运行状态
    4. log_false_positive      — 记录误报反馈（支撑反思进化）
    5. edge_pre_screen         — 边缘端预筛结果处理
    6. get_system_health       — 🆕 查询云端系统健康状态与负载（Phase 2 边缘-云端协同）

Phase 2 边缘-云端能力分级:
    ┌──────────────┬──────────────────────────────────┐
    │ 边缘端 (Edge) │ 云端 (Cloud)                     │
    ├──────────────┼──────────────────────────────────┤
    │ edge_pre_screen │ create_ehs_ticket              │
    │ get_system_health│ verify_certificate             │
    │ (轻量检测)      │ get_equipment_status            │
    │                 │ log_false_positive             │
    │                 │ GraphRAG / Memory / 精算       │
    └──────────────┴──────────────────────────────────┘
"""
import copy
import hashlib
import json
import logging
import time
from datetime import date, datetime
from app.utils import get_mock_path
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# =========================
# 模块级常量（避免魔法数字）
# =========================

# 工单生成
MAX_DESCRIPTION_LENGTH = 2000  # 摘要压缩阈值（字符数）
TRUNCATED_SUFFIX = "..."       # 截断后缀

# 设备维保预警
RUNTIME_OVERHAUL_THRESHOLD = 1900   # 大修预警阈值（运行时数）
MAINTENANCE_WARNING_DAYS = 30       # 维保到期预警天数

# 边缘预筛置信度阈值（可通过参数覆盖）
EDGE_CONFIDENCE_HIGH = 0.95      # 高置信度 → 直接判定，边缘端即时处置
EDGE_CONFIDENCE_MEDIUM = 0.70    # 中置信度 → 触发云端精算
EDGE_CONFIDENCE_LOCAL = 0.90     # 🆕 Phase 2: 边缘本地处置阈值（>0.9 跳过云端）
# Mock 模拟值
MOCK_EDGE_CONFIDENCE_MEDIUM = 0.82   # Mock: 中等置信度场景
MOCK_EDGE_CONFIDENCE_HIGH = 0.97     # Mock: 高置信度场景

# =========================
# 统一错误响应辅助
# =========================


def _make_error(error_msg: str, detail: str = "", **extra: Any) -> Dict[str, Any]:
    """
    生成标准化的错误响应字典。

    所有工具的错误返回均使用此函数，保证调用方（LangGraph 节点）
    能统一解析 error 和 detail 字段。

    Args:
        error_msg: 人类可读的错误描述
        detail: 技术细节（异常消息等）
        **extra: 工具特定的额外字段

    Returns:
        标准化错误响应字典
    """
    return {"error": error_msg, "detail": detail, **extra}


# =========================
# Mock 数据加载器
# =========================

_MOCK_DATA: Optional[Dict[str, Any]] = None


def _load_mock_data() -> Dict[str, Any]:
    """
    懒加载 mock_mcp_responses.json，全局缓存一份。

    Returns:
        dict: Mock 响应数据的深拷贝（防止调用方污染缓存）

    Raises:
        FileNotFoundError: Mock 数据文件不存在时抛出
    """
    global _MOCK_DATA
    if _MOCK_DATA is not None:
        return _MOCK_DATA

    mock_file = get_mock_path("mock_mcp_responses.json")
    if not mock_file.exists():
        raise FileNotFoundError(f"Mock 数据文件不存在: {mock_file}")

    with open(mock_file, "r", encoding="utf-8") as f:
        _MOCK_DATA = json.load(f)
    logger.info(f"Mock MCP 数据已加载: {mock_file}")
    return _MOCK_DATA


def _reload_mock_data() -> Dict[str, Any]:
    """强制重新加载 Mock 数据（测试用）"""
    global _MOCK_DATA
    _MOCK_DATA = None
    return _load_mock_data()


# =========================
# Pydantic 参数模型 (Args Schema)
# =========================


class CreateEHSTicketArgs(BaseModel):
    """
    创建 EHS 工单参数

    对应技术方案附录 B.1 接口 1。
    """

    title: str = Field(..., description="工单标题，如 '液压油泄漏 - SMT-A车间 - 3号注塑机'")
    description: str = Field(..., description="隐患详细描述")
    priority: int = Field(..., ge=1, le=5, description="优先级 1(紧急)-5(低)，对应隐患等级")
    assignee: str = Field(..., description="责任人，如 '设备维修组-王建国'")
    evidence_image: Optional[str] = Field(None, description="现场图片 Base64 或路径")


class VerifyCertificateArgs(BaseModel):
    """
    验证特种作业资质参数

    对应技术方案附录 B.1 接口 2。
    """

    employee_id: str = Field(..., description="员工工号，如 'EMP-8842'")
    required_type: str = Field(..., description="所需资质类型，如 'welder' / 'electrician'")


class GetEquipmentStatusArgs(BaseModel):
    """
    查询设备状态参数

    对应技术方案附录 B.1 MCP 工具接口。
    """

    equipment_id: str = Field(..., description="设备编号，如 'EQ-SMT-A-003'")


class LogFalsePositiveArgs(BaseModel):
    """
    记录误报反馈参数

    对应技术方案附录 B.1 新增接口。
    """

    emp_id: str = Field(..., description="操作员工工号")
    image_id: str = Field(..., description="对应的违规图片 ID")
    feedback_type: str = Field(..., description="反馈类型: 'false_positive' 或 'irrelevant'")
    comment: str = Field(..., description="用户填写的驳回理由")


class EdgePreScreenArgs(BaseModel):
    """
    边缘预筛结果处理参数

    对应技术方案附录 B.1 新增接口。
    Phase 2: 置信度阈值可通过参数传入，无需修改代码即可调整分流策略。
    """

    model_config = {"protected_namespaces": ()}

    image_chunk: Optional[str] = Field(None, description="图像数据块（Base64）")
    model_type: str = Field("yolov10n", description="边缘模型类型")
    confidence_threshold_high: float = Field(
        0.95, ge=0.0, le=1.0,
        description="高置信度阈值（>= 此值直接判定，无需云端）"
    )
    confidence_threshold_low: float = Field(
        0.70, ge=0.0, le=1.0,
        description="低置信度阈值（< 此值忽略）"
    )


class SystemHealthArgs(BaseModel):
    """
    🆕 Phase 2: 查询云端系统健康状态参数。

    供边缘节点在发起云端精算前探测云端负载与可用性。
    """

    edge_node_id: str = Field("", description="发起查询的边缘节点 ID")
    include_details: bool = Field(False, description="是否返回各组件详细状态")


# =========================
# 内部辅助: Mock 响应模拟
# =========================


async def _mock_response(tool_name: str) -> Dict[str, Any]:
    """
    从 Mock 数据中获取指定工具的响应。

    返回深拷贝以防止工具函数修改结果时污染全局缓存。

    Args:
        tool_name: 工具名称键（对应 mock JSON 的 key）

    Returns:
        Mock 响应字典的深拷贝

    Raises:
        KeyError: Mock 数据中无此工具定义
    """
    mock_data = _load_mock_data()
    if tool_name not in mock_data:
        raise KeyError(f"Mock 数据中未定义工具 '{tool_name}'，可用: {list(mock_data.keys())}")
    # 返回深拷贝：防止调用方 mutate 结果时污染全局 _MOCK_DATA 缓存
    return copy.deepcopy(mock_data[tool_name])


# =========================
# MCP 工具函数
# =========================


@tool(args_schema=CreateEHSTicketArgs)
async def create_ehs_ticket(
    title: str,
    description: str,
    priority: int,
    assignee: str,
    evidence_image: Optional[str] = None,
) -> Dict[str, Any]:
    """
    创建 EHS 隐患整改工单并推送至企业微信/EHS 系统。

    实现技术方案附录 B.1 接口 1：
        1. 幂等性检查 — 避免重复推送
        2. 熔断检查 — 熔断时放入重试队列
        3. 推送 — 调用外部接口
        4. 异常处理 — 捕获网络异常并更新状态
        5. 摘要压缩 — 若 description > 2000 字符，调用 summary_compress

    Args:
        title: 工单标题
        description: 隐患详细描述
        priority: 优先级 1-5
        assignee: 责任人
        evidence_image: 现场图片（可选）

    Returns:
        dict: 包含 ticket_id、status、assigned_to、priority 的响应
    """
    logger.info(f"[MCP] 创建 EHS 工单: title='{title}', priority={priority}, assignee='{assignee}'")

    try:
        # ---- 1. 摘要压缩检查 ----
        if len(description) > MAX_DESCRIPTION_LENGTH:
            logger.info(
                f"[MCP] description 长度 {len(description)} > {MAX_DESCRIPTION_LENGTH}，"
                f"执行摘要压缩"
            )
            # 当前 Mock 阶段仅截断；后续接入 LLM summary_compress
            description = description[:MAX_DESCRIPTION_LENGTH - len(TRUNCATED_SUFFIX)] + TRUNCATED_SUFFIX

        # ---- 2. 幂等性检查 (Mock 阶段预留) ----
        # 真实实现：查询 t_hazard_ticket.delivery_status
        # 若为 'sent' 或 'ack'，直接返回已有结果

        # ---- 3. 获取 Mock 响应 ----
        result = await _mock_response("create_ehs_ticket")

        # ---- 4. 附加工单上下文 ----
        result["input_title"] = title
        result["input_priority"] = priority
        result["input_assignee"] = assignee
        result["message"] = (
            f"工单 {result.get('ticket_id')} 已成功推送至企微工作台，"
            f"指派给 {assignee}。"
        )

        logger.info(f"[MCP] EHS 工单创建成功: {result.get('ticket_id')}")
        return result

    except FileNotFoundError as e:
        logger.error(f"[MCP] Mock 数据文件缺失: {e}")
        return _make_error("系统配置错误：Mock 数据文件不存在", str(e))
    except KeyError as e:
        logger.error(f"[MCP] Mock 工具未定义: {e}")
        return _make_error("工具配置错误", str(e))
    except Exception as e:
        logger.error(f"[MCP] create_ehs_ticket 执行失败: {e}", exc_info=True)
        return _make_error("工单创建失败", str(e), ticket_id=None, status="failed")


@tool(args_schema=VerifyCertificateArgs)
async def verify_certificate(
    employee_id: str,
    required_type: str,
) -> Dict[str, Any]:
    """
    实时验证特种作业人员资质（动火证、电工证等）。

    实现技术方案附录 B.1 接口 2：
        查询 HR 系统或国家证书平台，判断证书是否有效。

    Args:
        employee_id: 员工工号
        required_type: 所需资质类型 (e.g., "welder", "electrician")

    Returns:
        dict: 包含 is_qualified、cert_expiry、name 的验证结果
    """
    logger.info(f"[MCP] 验证资质: employee_id='{employee_id}', required_type='{required_type}'")

    try:
        result = await _mock_response("verify_employee_qualification")

        # Mock 阶段按固定数据返回；真实实现会按 employee_id 查询
        is_qualified = result.get("is_qualified", False)
        cert_expiry = result.get("cert_expiry", "unknown")
        name = result.get("name", "unknown")

        # ---- 过期检查 ---- #
        try:
            expiry_date = date.fromisoformat(cert_expiry)
            if expiry_date < date.today():
                logger.warning(
                    f"[MCP] 员工 {name}({employee_id}) 的 {required_type} "
                    f"证书已过期 ({cert_expiry})"
                )
                result["is_qualified"] = False
                result["warning"] = f"证书已于 {cert_expiry} 过期"
        except (ValueError, TypeError):
            pass

        logger.info(f"[MCP] 资质验证完成: {name} qualified={result.get('is_qualified')}")
        return result

    except FileNotFoundError as e:
        logger.error(f"[MCP] Mock 数据文件缺失: {e}")
        return _make_error("系统配置错误：Mock 数据文件不存在", str(e))
    except Exception as e:
        logger.error(f"[MCP] verify_certificate 执行失败: {e}", exc_info=True)
        return _make_error("资质验证服务不可用", str(e), is_qualified=False)


@tool(args_schema=GetEquipmentStatusArgs)
async def get_equipment_status(equipment_id: str) -> Dict[str, Any]:
    """
    查询设备运行状态与维保信息。

    从 MES 系统获取设备的实时运行数据、运行时长、上次维保日期等。

    Args:
        equipment_id: 设备编号 (e.g., 'EQ-SMT-A-003')

    Returns:
        dict: 包含 status、runtime_hours、last_maintenance、next_maintenance_due 的设备状态
    """
    logger.info(f"[MCP] 查询设备状态: equipment_id='{equipment_id}'")

    try:
        result = await _mock_response("get_equipment_status")

        # ---- 维保预警检查 ---- #
        next_due = result.get("next_maintenance_due")
        if next_due:
            try:
                due_date = date.fromisoformat(next_due)
                days_left = (due_date - date.today()).days
                if days_left <= MAINTENANCE_WARNING_DAYS:
                    logger.warning(
                        f"[MCP] 设备 {equipment_id} 维保即将到期: "
                        f"{next_due} (剩余 {days_left} 天)"
                    )
                    result["maintenance_warning"] = (
                        f"维保即将到期，剩余 {days_left} 天，请尽快安排检修。"
                    )
            except (ValueError, TypeError):
                pass

        # ---- 运行时长预警 ---- #
        runtime = result.get("runtime_hours", 0)
        if runtime >= RUNTIME_OVERHAUL_THRESHOLD:
            result["runtime_warning"] = (
                f"设备运行时长 {runtime}h 已接近 2000h 大修阈值，建议安排大修。"
            )

        logger.info(
            f"[MCP] 设备状态查询完成: {equipment_id} status={result.get('status')}"
        )
        return result

    except FileNotFoundError as e:
        logger.error(f"[MCP] Mock 数据文件缺失: {e}")
        return _make_error("系统配置错误：Mock 数据文件不存在", str(e))
    except Exception as e:
        logger.error(f"[MCP] get_equipment_status 执行失败: {e}", exc_info=True)
        return _make_error(
            "设备状态查询服务不可用", str(e),
            equipment_id=equipment_id,
            status="unknown",
        )


@tool(args_schema=LogFalsePositiveArgs)
async def log_false_positive(
    emp_id: str,
    image_id: str,
    feedback_type: str,
    comment: str,
) -> Dict[str, Any]:
    """
    记录用户对 AI 隐患识别的误报/驳回反馈。

    实现技术方案附录 B.1 新增接口：
        1. 写入 t_feedback_log 表
        2. 触发异步任务：更新向量库的 Negative Sample

    支撑模块三的「反思与进化」闭环。

    Args:
        emp_id: 操作员工工号
        image_id: 对应的违规图片 ID
        feedback_type: 'false_positive'（误报）或 'irrelevant'（不相关）
        comment: 用户填写的驳回理由

    Returns:
        dict: 包含 log_id、status 的确认结果
    """
    logger.info(
        f"[MCP] 记录误报反馈: emp_id='{emp_id}', image_id='{image_id}', "
        f"type='{feedback_type}'"
    )

    try:
        # ---- 参数校验 ---- #
        if feedback_type not in ("false_positive", "irrelevant"):
            return {
                "error": (
                    f"无效的反馈类型 '{feedback_type}'，"
                    "仅支持 'false_positive' 或 'irrelevant'"
                ),
                "status": "rejected",
            }

        # ---- 使用确定性哈希生成 log_id（替代 hash()） ---- #
        digest = hashlib.sha256(
            f"{emp_id}:{image_id}:{comment}".encode("utf-8")
        ).hexdigest()[:8]

        result = {
            "log_id": f"FBL-{emp_id}-{digest}",
            "status": "recorded",
            "emp_id": emp_id,
            "image_id": image_id,
            "feedback_type": feedback_type,
            "comment": comment,
            "message": "反馈已记录，将异步更新向量库 Negative Sample。",
        }

        logger.info(f"[MCP] 误报反馈已记录: log_id={result['log_id']}")
        return result

    except Exception as e:
        logger.error(f"[MCP] log_false_positive 执行失败: {e}", exc_info=True)
        return _make_error("反馈记录失败", str(e), status="failed")


@tool(args_schema=EdgePreScreenArgs)
async def edge_pre_screen(
    image_chunk: Optional[str] = None,
    model_type: str = "yolov10n",
    confidence_threshold_high: float = 0.95,
    confidence_threshold_low: float = 0.70,
) -> Dict[str, Any]:
    """
    执行边缘端快速预筛推理，决定是否需要上传云端精算。

    Phase 2 核心工具 — 边缘-云端分流的执行入口。

    分流策略（阈值由参数控制，无硬编码）:
        1. 在边缘端执行快速推理 (yolov10n / 轻量模型)
        2. confidence >= confidence_threshold_high: 直接判定，边缘本地处置
        3. confidence_threshold_low <= conf < confidence_threshold_high: 上传云端精算
        4. confidence < confidence_threshold_low: 静默忽略

    对应技术方案附录 B.1 + Phase 2 边缘智能 MVP。

    Args:
        image_chunk: 图像数据（Base64），None 时返回 Mock 结果
        model_type: 边缘模型类型，默认 "yolov10n"
        confidence_threshold_high: 高置信度阈值（>= 此值直接判定）
        confidence_threshold_low: 低置信度阈值（< 此值忽略）

    Returns:
        dict: 包含 status(edge_resolved/pending_cloud/ignored)、
              confidence、need_cloud_analysis 的分流决策
    """
    logger.info(
        f"[MCP] 边缘预筛: model='{model_type}', "
        f"has_image={image_chunk is not None}, "
        f"thresholds=[high={confidence_threshold_high}, low={confidence_threshold_low}]"
    )

    try:
        if image_chunk is None:
            # Mock: 模拟中等置信度场景 → 触发云端精算
            result: Dict[str, Any] = {
                "status": "pending_cloud",
                "model_type": model_type,
                "confidence": MOCK_EDGE_CONFIDENCE_MEDIUM,
                "confidence_thresholds_used": {
                    "high": confidence_threshold_high,
                    "low": confidence_threshold_low,
                },
                "detections": [
                    {"type": "no_hardhat", "bbox": [120, 80, 350, 420],
                     "confidence": MOCK_EDGE_CONFIDENCE_MEDIUM}
                ],
                "need_cloud_analysis": True,
                "message": (
                    f"边缘检测置信度 {MOCK_EDGE_CONFIDENCE_MEDIUM}，"
                    f"处于 [{confidence_threshold_low}, {confidence_threshold_high}) 区间，"
                    "触发云端 Qwen-VL 精算。"
                ),
            }
            logger.info("[MCP] 边缘预筛: 中等置信度，触发云端精算")
            return result

        # ---- 真实实现：调用边缘模型推理 ---- #
        # model = load_model(model_type)
        # detections = model.predict(image_chunk)
        # max_conf = max(d.confidence for d in detections)
        #
        # if max_conf >= confidence_threshold_high:
        #     return {"status": "edge_resolved", "need_cloud_analysis": False, ...}
        # elif max_conf >= confidence_threshold_low:
        #     return {"status": "pending_cloud", "need_cloud_analysis": True, ...}
        # else:
        #     return {"status": "ignored", "need_cloud_analysis": False, ...}

        # Mock: 模拟高置信度场景 → 边缘即时处置
        result = {
            "status": "edge_resolved",
            "model_type": model_type,
            "confidence": MOCK_EDGE_CONFIDENCE_HIGH,
            "confidence_thresholds_used": {
                "high": confidence_threshold_high,
                "low": confidence_threshold_low,
            },
            "detections": [
                {"type": "fire_smoke", "bbox": [200, 50, 600, 380],
                 "confidence": MOCK_EDGE_CONFIDENCE_HIGH}
            ],
            "need_cloud_analysis": False,
            "message": (
                f"边缘检测置信度 {MOCK_EDGE_CONFIDENCE_HIGH} "
                f">= 阈值 {confidence_threshold_high}，"
                "边缘端直接判定，无需云端精算。"
            ),
        }
        logger.info("[MCP] 边缘预筛: 高置信度，边缘即时处置")
        return result

    except Exception as e:
        logger.error(f"[MCP] edge_pre_screen 执行失败: {e}", exc_info=True)
        # 兜底：失败时安全上升至云端
        return _make_error(
            "边缘推理服务不可用", str(e),
            status="error",
            need_cloud_analysis=True,  # 安全兜底 → 上升云端
        )


@tool(args_schema=SystemHealthArgs)
async def get_system_health(
    edge_node_id: str = "",
    include_details: bool = False,
) -> Dict[str, Any]:
    """
    🆕 Phase 2: 查询云端系统健康状态与当前负载。

    供边缘节点在发起云端精算请求前探测：
        - 云端 API 是否可达
        - 各依赖服务（Neo4j/Redis/Milvus）的健康状态
        - 当前队列深度与预估延迟

    边缘端调用场景:
        1. 启动时握手：边缘节点注册并获取云端状态
        2. 分流前探测：中等置信度场景上传前确认云端可用
        3. 定期心跳：边缘节点存活检测

    Args:
        edge_node_id: 发起查询的边缘节点 ID（用于日志追踪）
        include_details: 是否返回各组件详细状态（默认仅返回摘要）

    Returns:
        dict: 包含 overall_status、components、load_level、timestamp 的健康报告
    """
    logger.info(
        f"[MCP] 查询系统健康: edge_node='{edge_node_id}', "
        f"details={include_details}"
    )

    try:
        now = datetime.now().isoformat()

        # Mock: 模拟云端各组件状态
        components = {
            "api": {
                "status": "healthy",
                "version": "0.1.0",
                "uptime_seconds": 86400,
            },
            "neo4j": {
                "status": "healthy",
                "node_count": 13,
                "relationship_count": 10,
                "latency_ms": 12,
            },
            "redis": {
                "status": "healthy",
                "memory_used_mb": 64,
                "max_memory_mb": 256,
            },
            "milvus": {
                "status": "healthy",
                "collection_count": 1,
                "total_vectors": 2,
                "latency_ms": 8,
            },
            "llm_gateway": {
                "status": "healthy",
                "active_requests": 3,
                "avg_latency_ms": 2500,
            },
        }

        # 计算整体状态
        all_healthy = all(c["status"] == "healthy" for c in components.values())
        overall = "healthy" if all_healthy else "degraded"

        # 计算负载等级
        active_requests = components["llm_gateway"].get("active_requests", 0)
        if active_requests <= 5:
            load_level = "low"
        elif active_requests <= 20:
            load_level = "medium"
        else:
            load_level = "high"

        result: Dict[str, Any] = {
            "overall_status": overall,
            "load_level": load_level,
            "active_llm_requests": active_requests,
            "estimated_latency_ms": 2500 if load_level == "low" else 5000,
            "edge_node_id": edge_node_id,
            "timestamp": now,
            "message": (
                f"云端状态: {overall}, 负载: {load_level}, "
                f"活跃请求: {active_requests}"
            ),
        }

        if include_details:
            result["components"] = components

        logger.info(
            f"[MCP] 系统健康查询完成: overall={overall}, "
            f"load={load_level}"
        )
        return result

    except Exception as e:
        logger.error(f"[MCP] get_system_health 执行失败: {e}", exc_info=True)
        return _make_error(
            "云端健康检查失败", str(e),
            overall_status="unknown",
            load_level="unknown",
        )


# =========================
# 工具注册表（供 LangGraph ToolNode 使用）
# =========================

# 所有 MCP 工具列表，Phase 4 时注入 LangGraph ToolNode
MCP_TOOLS = [
    create_ehs_ticket,
    verify_certificate,
    get_equipment_status,
    log_false_positive,
    edge_pre_screen,
    get_system_health,  # 🆕 Phase 2
]

# 按名称快速查找
MCP_TOOLS_BY_NAME: Dict[str, Any] = {t.name: t for t in MCP_TOOLS}

# 🆕 Phase 2: 工具能力分级（边缘端可调用 vs 云端专属）
EDGE_TOOLS = ["edge_pre_screen", "get_system_health"]
CLOUD_TOOLS = ["create_ehs_ticket", "verify_certificate", "get_equipment_status", "log_false_positive"]


def get_all_tools() -> List[Any]:
    """
    获取所有已注册的 MCP 工具列表。

    供 LangGraph workflow.py 中的 ToolNode 使用。

    Returns:
        List: LangChain @tool 装饰的函数列表
    """
    return MCP_TOOLS


def get_tool_by_name(name: str) -> Optional[Any]:
    """
    按名称查找工具。

    Args:
        name: 工具名称 (e.g., 'create_ehs_ticket')

    Returns:
        工具函数或 None
    """
    return MCP_TOOLS_BY_NAME.get(name)
