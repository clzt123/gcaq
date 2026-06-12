"""
LangGraph 状态机与节点模块

定义隐患研判工作流的状态契约、路由逻辑和节点执行函数。

核心文件:
    - state.py: HazardState TypedDict 类型定义
    - workflow.py: StateGraph 编排与条件路由
    - nodes.py: 7 个核心节点执行函数

快速使用:
    from app.core.graph.state import HazardState
    from app.core.graph.workflow import create_hazard_workflow, run_hazard_workflow

    result = await run_hazard_workflow(
        current_image="/mock_data/images/inj_mold_leak.jpg",
        alert_id="ALT-001",
    )
"""
from app.core.graph.state import HazardState, MAX_RETRIES
from app.core.graph.workflow import create_hazard_workflow, run_hazard_workflow
from app.core.graph.nodes import (
    detection_node,
    supervisor_node,
    graph_rag_node,
    ticket_generation_node,
    urgent_handler_node,
    normal_handler_node,
    ticket_push_node,
)

__all__ = [
    "HazardState",
    "MAX_RETRIES",
    "create_hazard_workflow",
    "run_hazard_workflow",
    "detection_node",
    "supervisor_node",
    "graph_rag_node",
    "ticket_generation_node",
    "urgent_handler_node",
    "normal_handler_node",
    "ticket_push_node",
]
