"""
LangGraph 状态契约定义

定义隐患研判工作流的核心状态类型 HazardState。
采用 TypedDict + operator.add 归约器，确保 LangGraph 节点间
类型安全的消息传递与自动合并。

设计依据:
    - 技术方案附录 D.1 (11 字段完整版)
    - 与 LangGraph StateGraph 的 add_messages 机制兼容
    - WorkFlow 参考: Base/ Pydantic State → 本项目改用 TypedDict（更轻量）
"""
import operator
from typing import Annotated, Dict, List, TypedDict


class HazardState(TypedDict):
    """
    隐患研判工作流状态。

    各节点通过返回 Dict 进行部分状态更新（Partial Update），
    LangGraph 自动将返回值合并到当前 State 中。
    messages 字段使用 operator.add 归约器：多节点追加的消息自动拼接。

    字段分组:
        对话历史 — messages
        隐患数据 — current_image, detection_result
        工单数据 — ticket_data
        知识上下文 — graph_context, memory_context
        流程控制 — next_action, ticket_status, retry_count
        环境信息 — edge_node_id, area_type, need_cloud_analysis
    """

    # ---- 对话历史 ----
    messages: Annotated[List[Dict], operator.add]
    """对话消息历史。每项为 {"role": "system"/"ai"/"human", "content": str}。
    operator.add 归约器确保多节点的消息自动拼接而非覆盖。"""

    # ---- 隐患数据 ----
    current_image: str
    """当前待分析的图片路径或 Base64 数据。Mock 模式下为路径字符串。"""

    detection_result: Dict
    """视觉检测结果。
    格式: {"risk_level": "high"/"medium"/"low"/"none",
           "findings": [{"type": str, "description": str, "confidence": float}],
           "raw_response": str}"""

    # ---- 工单数据 ----
    ticket_data: Dict
    """生成的工单。
    格式: {"title": str, "description": str, "priority": int, "assignee": str}"""

    # ---- 知识上下文 ----
    graph_context: str
    """GraphRAG 检索到的法规/SOP/经验上下文文本。由 graph_rag_node 填充。"""

    memory_context: str
    """记忆系统召回的专家经验/反思教训。由 memory_retrieval_node 填充。
    包含历史相似案例的处置方案与人工修正记录，作为工单生成的 few-shot 参考。"""

    # ---- 流程控制 ----
    next_action: str
    """路由指令。取值: "urgent_handler" / "normal_handler" / "end"。
    supervisor_node 设置，StateGraph 条件边据此路由。"""

    ticket_status: str
    """工单生命周期状态。
    取值: "created" / "sent" / "acknowledged" / "closed" / "timeout" / "failed" """

    retry_count: int
    """推送重试计数。每次推送失败 +1，达到 MAX_RETRIES(3) 时强制终止。
    防止状态机死循环。"""

    # ---- 环境信息 ----
    edge_node_id: str
    """边缘节点 ID。格式: EDGE_{厂区}_{序号}，如 'EDGE_DG_01'。"""

    area_type: str
    """区域类型。取值: 'production' / 'rest' / 'hazard' / 'warehouse' """

    need_cloud_analysis: bool
    """是否需要云端大模型精算。边缘预筛中等置信度时为 True。"""

    # ---- 零幻觉校验 (功能6) ----
    llm_response: str
    """LLM 生成的合规分析响应。
    由 llm_analysis_node 填充，经 hallucination_guard_node 校验。
    包含强制引用链的完整分析文本（含法规依据、风险分析、处置建议、置信度声明）。"""

    refusal_reason: str
    """拒答原因。当检索置信度不足或 LLM 校验失败时由 hallucination_guard_node 填充。
    非空时表示当前请求被零幻觉校验模块拒绝生成分析。"""

    citation_verified: bool
    """引用链校验是否通过。由 hallucination_guard_node 在 Post-LLM 阶段设置。
    True 表示 LLM 响应中包含至少 1 条可验证的引用标记。"""

    response_confidence: float
    """LLM 响应的综合置信度评分 (0.0-1.0)。
    由 hallucination_guard_node 在 Post-LLM 阶段计算，综合检索质量、引用密度和拒答检测。"""


# =========================
# 常量
# =========================

MAX_RETRIES = 3  # 最大重试次数（与 t_sync_event.retry_count 定义一致）
