"""
隐患研判 API 接口 (Phase 5 实现)

提供隐患图片分析、告警查询、工单状态追踪等 RESTful 接口。
串联 LangGraph 工作流与 FastAPI 路由。

接口清单:
    POST /api/v1/hazard/analyze  — 提交图片进行隐患研判
    GET  /api/v1/hazard/alerts    — 查询告警列表
    GET  /api/v1/hazard/alerts/{alert_id} — 查询单条告警详情
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.graph.workflow import run_hazard_workflow
from app.utils import get_mock_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/hazard", tags=["隐患研判"])


# =========================
# Pydantic 请求/响应模型
# =========================


class AnalyzeRequest(BaseModel):
    """
    隐患研判请求体。

    对应 HazardState 的输入字段。
    """

    image_url: str = Field(..., description="待分析图片路径或 Base64 数据")
    alert_id: str = Field("", description="告警 ID（可选，用于日志追踪）")
    edge_node_id: str = Field("", description="边缘节点 ID")
    area_type: str = Field("", description="区域类型: production/rest/hazard/warehouse")


class AnalyzeResponse(BaseModel):
    """
    隐患研判响应体。

    覆盖 HazardState 中 API 消费者关心的全部字段。
    current_image 和 detection_result(原始) 属于输入侧，合理排除。
    """

    model_config = {"extra": "allow"}

    alert_id: str = Field("", description="告警 ID")
    risk_level: str = Field("", description="隐患等级: high/medium/low/none")
    ticket_status: str = Field("", description="工单状态: created/sent/failed")
    ticket_data: Dict[str, Any] = Field(default_factory=dict, description="工单数据")
    graph_context: str = Field("", description="法规/SOP 知识上下文")
    next_action: str = Field("", description="下一步动作")
    messages: list[dict] = Field(default_factory=list, description="流程消息日志")
    retry_count: int = Field(0, description="重试次数")
    need_cloud_analysis: bool = Field(False, description="是否需要云端大模型精算")
    area_type: str = Field("", description="区域类型: production/rest/hazard/warehouse")
    edge_node_id: str = Field("", description="边缘节点 ID")


# =========================
# Mock 告警数据加载
# =========================

_MOCK_ALERTS_CACHE: list | None = None


def _load_mock_alerts() -> list:
    """加载 mock_alerts.json，全局缓存一份。"""
    global _MOCK_ALERTS_CACHE
    if _MOCK_ALERTS_CACHE is not None:
        return _MOCK_ALERTS_CACHE

    alerts_file = get_mock_path("mock_alerts.json")
    if not alerts_file.exists():
        _MOCK_ALERTS_CACHE = []
        return _MOCK_ALERTS_CACHE

    with open(alerts_file, "r", encoding="utf-8") as f:
        _MOCK_ALERTS_CACHE = json.load(f)
    return _MOCK_ALERTS_CACHE


# =========================
# API 路由
# =========================


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_hazard(request: AnalyzeRequest) -> AnalyzeResponse:
    """
    提交图片进行隐患智能研判。

    完整链路:
        图片 → 视觉分析(Mock Qwen-VL) → Supervisor 路由
        → GraphRAG 法规检索 → 工单生成 → MCP 推送

    Args:
        request: 包含 image_url 和可选元数据的请求体

    Returns:
        AnalyzeResponse: 包含风险等级、工单状态、法规依据、流程日志

    Raises:
        HTTPException 500: 工作流执行失败
    """
    logger.info(f"[API] 收到研判请求: image={request.image_url[:80]}...")

    try:
        # 调用 LangGraph 工作流
        result = await run_hazard_workflow(
            current_image=request.image_url,
            alert_id=request.alert_id,
            edge_node_id=request.edge_node_id,
            area_type=request.area_type,
        )

        detection = result.get("detection_result", {})
        response = AnalyzeResponse(
            alert_id=request.alert_id,
            risk_level=detection.get("risk_level", "none"),
            ticket_status=result.get("ticket_status", ""),
            ticket_data=result.get("ticket_data", {}),
            graph_context=result.get("graph_context", ""),
            next_action=result.get("next_action", ""),
            messages=result.get("messages", []),
            retry_count=result.get("retry_count", 0),
            need_cloud_analysis=result.get("need_cloud_analysis", False),
            area_type=result.get("area_type", request.area_type),
            edge_node_id=result.get("edge_node_id", request.edge_node_id),
        )

        logger.info(
            f"[API] 研判完成: risk_level={response.risk_level}, "
            f"ticket_status={response.ticket_status}"
        )
        return response

    except Exception as e:
        logger.error(f"[API] 研判失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"隐患研判工作流执行失败: {str(e)}",
        )


@router.get("/alerts")
async def list_alerts(limit: int = Query(10, ge=1, le=100)) -> Dict[str, Any]:
    """
    查询告警列表。

    Args:
        limit: 返回数量上限（默认 10）

    Returns:
        dict: 包含 total 和 alerts 列表
    """
    alerts = _load_mock_alerts()
    return {
        "total": len(alerts),
        "alerts": alerts[:limit],
    }


@router.get("/alerts/{alert_id}")
async def get_alert(alert_id: str) -> Dict[str, Any]:
    """
    查询单条告警详情。

    Args:
        alert_id: 告警 ID (e.g., 'ALT-20240520-001')

    Returns:
        dict: 告警详情

    Raises:
        HTTPException 404: 告警不存在
    """
    alerts = _load_mock_alerts()
    for alert in alerts:
        if alert.get("alert_id") == alert_id:
            return alert

    raise HTTPException(status_code=404, detail=f"告警 {alert_id} 不存在")
