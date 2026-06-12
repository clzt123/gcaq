"""
LangGraph 工作流编排

使用 StateGraph 编排隐患研判闭环的完整流程。
支持条件路由（Supervisor 四路分支：边缘/紧急/普通/终止）、节点串联和重试熔断。

🆕 Phase 2: 新增 edge_handler 分支，实现边缘-云端分流。

设计模式参考:
    - WorkFlow/base/baseWorkFlow.py 的 StateGraph 构建 + compile + invoke 模式
    - 本项目异步重写：使用原生 StateGraph API + async 节点
    - 显式边注册（非 WorkFlow 的 DSL 自动化）

图结构 (Phase 2):
    START
      → detection_node
      → supervisor_node
          ├─ next_action="edge_handler"    → edge_handler_node    → END  🆕
          ├─ next_action="urgent_handler"  → urgent_handler_node  → END
          ├─ next_action="normal_handler"  → normal_handler_node  → END
          └─ next_action="end" → END
"""
import logging
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from app.core.graph.nodes import (
    detection_node,
    supervisor_node,
    edge_handler_node,     # 🆕 Phase 2
    urgent_handler_node,
    normal_handler_node,
)
from app.core.graph.state import HazardState

logger = logging.getLogger(__name__)


# =========================
# 路由函数
# =========================


def _route_by_action(state: HazardState) -> str:
    """
    条件边路由函数：读取 next_action 决定下一节点。

    🆕 Phase 2: 新增 "edge_handler" 路由。

    Args:
        state: 当前状态

    Returns:
        下一节点名称
        ("edge_handler" / "urgent_handler" / "normal_handler" / "end")
    """
    action = state.get("next_action", "end")
    if action in ("edge_handler", "urgent_handler", "normal_handler"):
        return action
    return "end"


# =========================
# StateGraph 构建
# =========================


def create_hazard_workflow() -> StateGraph:
    """
    创建并配置隐患研判工作流图。

    🆕 Phase 2 图结构:
        1. detection → supervisor（四路分流）
        2. edge_handler:    高置信度 → 边缘即时处置 → END
        3. urgent_handler:  高风险 → 云端全链路（GraphRAG+记忆+工单）→ END
        4. normal_handler:  中风险 → 云端全链路 → END
        5. end:             低风险 → 仅记录

    构建顺序:
        1. 创建 StateGraph(HazardState)
        2. 添加 6 个业务节点（含 edge_handler）
        3. 添加普通边 (START → detection → supervisor)
        4. 添加条件边 (supervisor → edge/urgent/normal/end)
        5. 添加结束边 (all handlers → END)
        6. compile()

    Returns:
        已编译的 StateGraph 实例（可调用 .ainvoke() 执行）
    """
    # ---- 1. 创建图 ----
    workflow = StateGraph(HazardState)

    # ---- 2. 添加节点（🆕 Phase 2: +edge_handler） ----
    workflow.add_node("detection", detection_node)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("edge_handler", edge_handler_node)      # 🆕
    workflow.add_node("urgent_handler", urgent_handler_node)
    workflow.add_node("normal_handler", normal_handler_node)

    # ---- 3. 设置入口 ----
    workflow.set_entry_point("detection")

    # ---- 4. 普通边 ----
    workflow.add_edge("detection", "supervisor")

    # ---- 5. 条件边（🆕 Phase 2: +edge_handler 路由） ----
    workflow.add_conditional_edges(
        "supervisor",
        _route_by_action,
        {
            "edge_handler": "edge_handler",       # 🆕
            "urgent_handler": "urgent_handler",
            "normal_handler": "normal_handler",
            "end": END,
        },
    )

    # ---- 6. 结束边 ----
    workflow.add_edge("edge_handler", END)          # 🆕
    workflow.add_edge("urgent_handler", END)
    workflow.add_edge("normal_handler", END)

    # ---- 7. 编译 ----
    compiled = workflow.compile()
    logger.info("HazardWorkflow (Phase 2) 已编译: 6 节点 + 4 路分流")
    return compiled


# =========================
# 便捷执行函数
# =========================


async def run_hazard_workflow(
    current_image: str,
    alert_id: str = "",
    edge_node_id: str = "",
    area_type: str = "",
) -> Dict[str, Any]:
    """
    执行隐患研判工作流。

    便捷的一站式入口：初始化 HazardState → 执行工作流 → 返回最终状态。

    Args:
        current_image: 待分析图片路径
        alert_id: 告警 ID（用于日志追踪）
        edge_node_id: 边缘节点 ID
        area_type: 区域类型

    Returns:
        最终 HazardState 字典（含 messages, ticket_data, ticket_status 等）
    """
    logger.info(
        f"[Workflow] 启动: alert_id={alert_id}, image={current_image[:60]}..."
    )

    # 初始状态
    initial_state: HazardState = {
        "messages": [],
        "current_image": current_image,
        "detection_result": {},
        "ticket_data": {},
        "graph_context": "",
        "memory_context": "",
        "next_action": "",
        "ticket_status": "",
        "retry_count": 0,
        "edge_node_id": edge_node_id,
        "area_type": area_type,
        "need_cloud_analysis": False,
        # 零幻觉校验 (功能6)
        "llm_response": "",
        "refusal_reason": "",
        "citation_verified": False,
        "response_confidence": 0.0,
    }

    # 创建工作流并执行
    workflow = create_hazard_workflow()
    final_state = await workflow.ainvoke(initial_state)

    logger.info(
        f"[Workflow] 完成: next_action={final_state.get('next_action')}, "
        f"ticket_status={final_state.get('ticket_status')}, "
        f"retry_count={final_state.get('retry_count')}"
    )

    return final_state
