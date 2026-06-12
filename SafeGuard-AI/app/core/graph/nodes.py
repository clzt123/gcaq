"""
LangGraph 工作流节点函数

实现隐患研判闭环的全部节点。所有节点均为 async 函数，
接收 HazardState，返回 Dict（LangGraph Partial State Update）。

Phase 2 新增边缘-云端分流能力。
功能 6 新增零幻觉校验层（LLM 强制引用 + 置信度拒答）。

节点清单:
    1. detection_node           — Qwen-VL 视觉分析（真实调用 + Mock 降级）
    2. supervisor_node          — 路由决策（🆕 Phase 2: 边缘-云端置信度分流）
    3. edge_handler_node        — 🆕 Phase 2: 边缘端即时处置（高置信度，跳过云端）
    4. graph_rag_node           — GraphRAG 知识检索（法规/SOP）【云端专属】
    5. memory_retrieval_node    — 记忆系统检索（专家经验/反思教训）【云端专属】
    6. hallucination_guard_node — 🆕 功能6: 零幻觉校验门控（检索置信度检查+拒答）
    7. llm_analysis_node        — 🆕 功能6: LLM 合规分析（强制引用链 Prompt）
    8. ticket_generation_node   — 工单数据组装（含 LLM 分析结果）
    9. urgent_handler_node      — 紧急处理编排（云端全链路）
   10. normal_handler_node      — 普通处理编排（云端全链路）
   11. ticket_push_node         — MCP 工具推送工单

设计原则:
    - async/await 优先
    - 所有节点 try-except 包裹，失败时优雅降级
    - 使用 Python logging（禁止 print）
    - 中文 Docstring
    - Phase 2: 阈值参数化，无硬编码业务规则
"""
import logging
from typing import Any, Dict, List, Optional

from app.core.graph.state import HazardState, MAX_RETRIES
from app.core.rag.neo4j_client import Neo4jClient
from app.core.rag.retriever import GraphRAGRetriever
from app.core.memory.manager import MemoryManager
from app.core.guard.hallucination_guard import (
    HallucinationGuard,
    CitationVerifier,
    generate_mock_llm_response,
    REFUSAL_CONFIDENCE_THRESHOLD,
)
from app.tools.mcp_tools import create_ehs_ticket, edge_pre_screen

logger = logging.getLogger(__name__)

# =========================
# 🆕 Phase 2: 边缘-云端分流阈值
# =========================

# 置信度 >= 此值时，边缘端直接处置，无需上传云端做 GraphRAG 精算
EDGE_CONFIDENCE_LOCAL_THRESHOLD = 0.90

# =========================
# 隐患类型 英→中 映射表
# =========================
# Qwen-VL 返回英文 hazard type，但 Neo4j 图谱 / Mock 记忆中全是中文。
# 检索前将英文类型码映射为中文关键词，大幅提升 GraphRAG 与记忆系统的命中率。

HAZARD_TYPE_ZH_MAP: Dict[str, str] = {
    "no_hardhat":          "安全帽 头部防护 个人防护 PPE",
    "no_safety_vest":      "反光衣 安全背心 防护服 PPE",
    "smoking":             "吸烟 明火 禁烟 火源",
    "using_phone":         "玩手机 违规使用 注意力分散",
    "unauthorized_entry":  "违规闯入 越界 危险区域 禁区",
    "oil_leak":            "油渍泄漏 化学品泄漏 液压油 切削液 密封圈 管路老化 防漏托盘",
    "fire_smoke":          "烟雾 火灾 浓烟 明火 初期火灾 灭火 报警",
    "blocked_exit":        "通道堵塞 消防通道 疏散通道 安全出口 纸箱 叉车",
    "unsafe_behavior":     "不安全行为 违规操作 绊倒 碰撞",
    "unclear":             "未知隐患 人工复核",
}


def _build_rag_query(findings: List[Dict[str, Any]]) -> str:
    """
    将 Qwen-VL 的 findings 转为 GraphRAG/记忆系统可用的中文检索查询。

    核心思路：英文 type → 中文关键词映射 + 保留原始 description 中的中文语义。
    兜底查询字符串确保即使 findings 为空也有产出。

    Args:
        findings: detection_result["findings"] 列表

    Returns:
        中英文混合的检索查询字符串
    """
    parts: List[str] = []

    for f in findings:
        hazard_type = f.get("type", "")
        description = f.get("description", "")

        # 注入中文映射关键词（提高 Neo4j 中文图谱命中率）
        zh_keywords = HAZARD_TYPE_ZH_MAP.get(hazard_type, hazard_type)
        parts.append(zh_keywords)

        # 保留 Qwen-VL 的中文描述（通常包含位置、严重程度等细节）
        if description:
            parts.append(description)

    if not parts:
        return "安全隐患处理 泄漏 火灾 安全帽 通道堵塞"

    return " ".join(parts)


# =========================
# 节点 1: 视觉分析
# =========================


async def detection_node(state: HazardState) -> Dict[str, Any]:
    """
    视觉分析节点（Qwen-VL 真实调用 + Mock 降级）。

    调用 Qwen-VL API 进行多模态隐患识别，支持：安全帽、反光衣、
    吸烟、玩手机、违规闯入、油渍泄漏、烟雾火情、通道堵塞等。
    API 未配置或调用失败时自动降级为 Mock 关键词匹配。

    Args:
        state: 当前工作流状态

    Returns:
        包含 detection_result、need_cloud_analysis、messages 的部分状态更新
    """
    image = state.get("current_image", "")
    logger.info(f"[Detection] 分析图片: {image[:80]}")

    try:
        from app.core.vision.analyzer import analyze_image_with_qwen

        detection = await analyze_image_with_qwen(image)

        # 判断是否需要云端精算（低置信度或无结果时标记）
        risk_level = detection.get("risk_level", "none")
        findings = detection.get("findings", [])
        need_cloud = (
            risk_level == "none"
            or any(f.get("confidence", 0) < 0.5 for f in findings)
        )

        logger.info(
            f"[Detection] 完成: risk_level={risk_level}, "
            f"findings={len(findings)}, need_cloud={need_cloud}"
        )
        return {
            "detection_result": detection,
            "need_cloud_analysis": need_cloud,
            "messages": [{
                "role": "system",
                "content": (
                    f"[视觉分析] {detection.get('raw_response', 'Qwen-VL 分析完成')}"
                ),
            }],
        }

    except Exception as e:
        logger.error(f"[Detection] 视觉分析失败: {e}", exc_info=True)
        return {
            "detection_result": {
                "risk_level": "none",
                "findings": [],
                "error": str(e),
            },
            "need_cloud_analysis": True,
            "messages": [{
                "role": "system",
                "content": f"[视觉分析] 失败: {e}",
            }],
        }


# =========================
# 节点 2: 路由决策
# =========================


async def supervisor_node(state: HazardState) -> Dict[str, Any]:
    """
    Supervisor 路由节点（🆕 Phase 2: 边缘-云端置信度分流）。

    分流逻辑:
        1. retry_count >= MAX_RETRIES → 强制终止
        2. max_confidence >= EDGE_CONFIDENCE_LOCAL_THRESHOLD → edge_handler（边缘即时处置）
        3. risk_level "high" → urgent_handler（云端全链路精算）
        4. risk_level "medium" → normal_handler（云端全链路精算）
        5. 其他 → end

    Phase 2 核心决策：高置信度场景无需 GraphRAG/专家记忆增强，
    边缘端直接生成工单，节省云端算力与网络往返延迟。

    Args:
        state: 当前工作流状态

    Returns:
        包含 next_action、messages 的部分状态更新
    """
    detection = state.get("detection_result", {})
    level = detection.get("risk_level", "low")
    findings = detection.get("findings", [])
    retry_count = state.get("retry_count", 0)

    # 计算最高置信度
    max_confidence = max(
        (f.get("confidence", 0) for f in findings), default=0
    )

    logger.info(
        f"[Supervisor] 等级={level}, max_confidence={max_confidence:.2f}, "
        f"retry_count={retry_count}"
    )

    # ---- 1. 防死循环 ----
    if retry_count >= MAX_RETRIES:
        logger.warning(
            f"[Supervisor] retry_count={retry_count} >= {MAX_RETRIES}，强制终止"
        )
        return {
            "next_action": "end",
            "messages": [{
                "role": "system",
                "content": (
                    f"[系统] 重试次数已达上限 ({MAX_RETRIES})，"
                    f"工单自动终止，请人工介入处理。"
                ),
            }],
        }

    # ---- 2. 🆕 Phase 2: 边缘即时处置（高置信度） ----
    if max_confidence >= EDGE_CONFIDENCE_LOCAL_THRESHOLD and findings:
        action = "edge_handler"
        msg = (
            f"[Phase2-Edge] 置信度 {max_confidence:.0%} >= "
            f"阈值 {EDGE_CONFIDENCE_LOCAL_THRESHOLD:.0%}，"
            f"边缘端即时处置，跳过云端 GraphRAG 精算。"
        )
        logger.info(f"[Supervisor] → {action} (edge-local dispatch)")
        return {
            "next_action": action,
            "messages": [{"role": "system", "content": msg}],
        }

    # ---- 3. 云端全链路（紧急/普通） ----
    if level == "high":
        action = "urgent_handler"
        msg = "[系统] 触发紧急流程：高风险隐患 → 云端全链路精算。"
    elif level == "medium":
        action = "normal_handler"
        msg = "[系统] 触发普通流程：中风险/模糊隐患 → 云端 GraphRAG 增强。"
    else:
        action = "end"
        msg = "[系统] 低风险/无法识别，仅记录日志，不生成工单。"

    logger.info(f"[Supervisor] → {action}")
    return {
        "next_action": action,
        "messages": [{"role": "system", "content": msg}],
    }


# =========================
# 🆕 Phase 2: 边缘即时处置节点
# =========================


async def edge_handler_node(state: HazardState) -> Dict[str, Any]:
    """
    🆕 Phase 2: 边缘端即时处置节点。

    在高置信度场景下（max_confidence >= EDGE_CONFIDENCE_LOCAL_THRESHOLD），
    跳过云端 GraphRAG 检索和专家记忆检索，直接在边缘端：
        1. 调用 edge_pre_screen 确认分流决策
        2. 组装工单（不含云端的法规/SOP 知识增强）
        3. 推送工单至 EHS 系统

    设计意图:
        - 减少云端算力消耗：高置信度场景无需 LLM 精算
        - 降低网络延迟：边缘端本地闭环，秒级响应
        - 离线可用：网络中断时边缘仍可独立处置明确违规

    Args:
        state: 当前工作流状态

    Returns:
        包含 ticket_data、ticket_status、messages 的部分状态更新
    """
    detection = state.get("detection_result", {})
    findings = detection.get("findings", [])
    area_type = state.get("area_type", "")
    edge_node_id = state.get("edge_node_id", "")

    logger.info(
        f"[EdgeHandler] 边缘即时处置: findings={len(findings)}, "
        f"area={area_type}"
    )

    try:
        # ---- Step 1: 调用边缘预筛确认 ----
        pre_screen_result = await edge_pre_screen.ainvoke({
            "model_type": "yolov10n",
            "confidence_threshold_high": EDGE_CONFIDENCE_LOCAL_THRESHOLD,
        })

        pre_screen_status = pre_screen_result.get("status", "unknown")
        logger.info(f"[EdgeHandler] 预筛状态: {pre_screen_status}")

        # ---- Step 2: 组装边缘工单（轻量，不含云端知识） ----
        if findings:
            primary = findings[0]
            hazard_type = primary.get("type", "unknown")
            desc = primary.get("description", "未知隐患")
            confidence = primary.get("confidence", 0)
            title = (
                f"[边缘-{hazard_type}] {area_type or '未知区域'} "
                f"(置信度 {confidence:.0%})"
            )
        else:
            hazard_type = "unknown"
            title = f"[边缘] 未知隐患 - {area_type or '未知区域'}"
            desc = "边缘模型检出异常，待人工确认"

        ticket_data: Dict[str, Any] = {
            "title": title,
            "description": (
                f"{desc}。"
                f"[边缘即时处置] 置信度达阈值，无需云端精算。"
                f"预筛状态: {pre_screen_status}。"
            ),
            "priority": 1,  # 高置信度 → P1 紧急
            "assignee": "边缘节点-自动指派",
            "source_node": edge_node_id,
            "hazard_type": hazard_type,
            "dispatch_mode": "edge_local",  # 🆕 标记为边缘本地处置
        }

        # ---- Step 3: 推送工单 ----
        push_result = await create_ehs_ticket.ainvoke({
            "title": ticket_data["title"],
            "description": ticket_data["description"],
            "priority": ticket_data["priority"],
            "assignee": ticket_data["assignee"],
        })

        ticket_status = "sent" if "error" not in push_result else "failed"

        logger.info(
            f"[EdgeHandler] 边缘处置完成: status={ticket_status}, "
            f"dispatch_mode=edge_local"
        )

        return {
            "ticket_data": ticket_data,
            "ticket_status": ticket_status,
            "graph_context": (
                f"[边缘本地处置] 置信度达阈值，未触发云端 GraphRAG。"
                f"预筛结果: {pre_screen_result.get('message', '')}"
            ),
            "memory_context": "",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"[Phase2-Edge] 边缘即时处置: {title} "
                        f"(预筛: {pre_screen_status})"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        f"[边缘推送] 状态={ticket_status}, "
                        f"dispatch_mode=edge_local"
                    ),
                },
            ],
        }

    except Exception as e:
        logger.error(f"[EdgeHandler] 边缘处置失败: {e}", exc_info=True)
        # 安全兜底：失败时上升至云端
        return {
            "ticket_status": "failed",
            "need_cloud_analysis": True,
            "messages": [{
                "role": "system",
                "content": (
                    f"[Phase2-Edge] 边缘处置失败: {e}，"
                    f"建议上升至云端精算。"
                ),
            }],
        }


# =========================
# 节点 3: GraphRAG 检索
# =========================


async def graph_rag_node(state: HazardState) -> Dict[str, Any]:
    """
    GraphRAG 知识检索节点。

    将 detection_result 中的隐患信息作为查询，
    调用 GraphRAGRetriever 获取法规、SOP、专家经验等知识。

    Args:
        state: 当前工作流状态

    Returns:
        包含 graph_context、messages 的部分状态更新
    """
    detection = state.get("detection_result", {})
    findings = detection.get("findings", [])

    # 构建查询文本（英→中映射 + 中文描述）
    query = _build_rag_query(findings)
    logger.info(f"[GraphRAG] 检索: query='{query[:120]}'")

    try:
        async with Neo4jClient() as neo4j:
            retriever = GraphRAGRetriever(neo4j)
            results = await retriever.retrieve(query)
            context = retriever.build_context(results)

        logger.info(f"[GraphRAG] 检索完成: {len(results)} 条结果, {len(context)} 字符")

        return {
            "graph_context": context,
            "messages": [{
                "role": "system",
                "content": f"[GraphRAG] 已检索 {len(results)} 条知识依据",
            }],
        }

    except Exception as e:
        logger.error(f"[GraphRAG] 检索失败: {e}", exc_info=True)
        return {
            "graph_context": "【检索结果】知识检索服务不可用，无法提供法规依据。\n",
            "messages": [{
                "role": "system",
                "content": f"[GraphRAG] 检索失败: {e}",
            }],
        }


# =========================
# 节点 4: 工单生成
# =========================


# =========================
# 节点 3.5: 记忆系统检索
# =========================


async def memory_retrieval_node(state: HazardState) -> Dict[str, Any]:
    """
    记忆系统检索节点。

    从长期专家经验记忆中检索历史相似案例的处置方案与反思教训，
    作为工单生成的 few-shot 参考。

    Args:
        state: 当前工作流状态

    Returns:
        包含 memory_context、messages 的部分状态更新
    """
    detection = state.get("detection_result", {})
    findings = detection.get("findings", [])

    # 构建查询文本（英→中映射 + 中文描述）
    query = _build_rag_query(findings)
    logger.info(f"[Memory] 检索专家经验: query='{query[:120]}'")

    try:
        manager = MemoryManager()
        items = await manager.retrieve_expert_memory(query, top_k=3)
        memory_context = manager.build_memory_context(items)

        logger.info(f"[Memory] 检索完成: {len(items)} 条记忆")

        return {
            "memory_context": memory_context,
            "messages": [{
                "role": "system",
                "content": f"[记忆系统] 已检索 {len(items)} 条历史经验",
            }],
        }

    except Exception as e:
        logger.error(f"[Memory] 检索失败: {e}", exc_info=True)
        return {
            "memory_context": "",
            "messages": [{
                "role": "system",
                "content": f"[记忆系统] 检索失败: {e}",
            }],
        }


# =========================
# 🆕 功能6: 零幻觉校验门控节点
# =========================


def _parse_context_confidence(graph_context: str) -> Dict[str, Any]:
    """
    从 graph_context 文本中解析置信度分布。

    上下文文本按置信度分三段：高(✅)、中(⚠️)、低(💡)。
    此函数统计各段中的条目数，用于 Pre-LLM 门控决策。

    Args:
        graph_context: build_context() 生成的格式化文本

    Returns:
        {"high_count": int, "medium_count": int, "low_count": int,
         "total_count": int, "has_citations": bool}
    """
    high_count = graph_context.count("✅ ")
    medium_count = graph_context.count("⚠️ ")
    low_count = graph_context.count("💡 ")

    # 检测是否包含引用标记
    has_citations = "📎" in graph_context

    # 检测是否为空结果
    if "未找到" in graph_context or "检索结果" in graph_context and high_count == 0 and medium_count == 0 and low_count == 0:
        total_count = 0
    else:
        total_count = high_count + medium_count + low_count

    return {
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        "total_count": total_count,
        "has_citations": has_citations,
    }


async def hallucination_guard_node(state: HazardState) -> Dict[str, Any]:
    """
    🆕 功能6: 零幻觉校验门控节点（Pre-LLM 第一道防线）。

    检查 GraphRAG 检索到的知识依据是否满足最低置信度要求。
    不足时触发拒答，跳过 LLM 分析直接返回拒答响应。

    门控规则:
        1. 无检索结果 → 拒答
        2. 有高置信度(✅)依据 → 通过
        3. 有中置信度(⚠️)依据 → 通过（但标记为需核实）
        4. 仅有低置信度(💡) → 拒答

    设计意图:
        - 在 LLM 调用前拦截低质量检索，避免浪费 Token 和生成不准确建议
        - 遵循"宁可不答，不可乱答"的安全原则

    Args:
        state: 当前工作流状态（需含 graph_context）

    Returns:
        包含 citation_verified、refusal_reason 的部分状态更新
    """
    graph_context = state.get("graph_context", "")
    detection = state.get("detection_result", {})

    logger.info("[HallucinationGuard] Pre-LLM 检索置信度门控检查")

    # 解析上下文中的置信度标记
    confidence_info = _parse_context_confidence(graph_context)
    total = confidence_info["total_count"]
    high = confidence_info["high_count"]
    medium = confidence_info["medium_count"]
    low = confidence_info["low_count"]

    logger.info(
        f"[HallucinationGuard] 检索结果: high={high}, medium={medium}, "
        f"low={low}, has_citations={confidence_info['has_citations']}"
    )

    # 规则 1: 空结果 → 拒答
    if total == 0 and not confidence_info["has_citations"]:
        risk_level = detection.get("risk_level", "unknown")
        # 如果是高风险场景且边缘已检测到隐患，允许继续（边缘结果可信）
        if risk_level in ("high",) and detection.get("findings"):
            logger.info(
                "[HallucinationGuard] 高风险场景 + 有视觉检测结果，"
                "即使知识库无结果也继续（以防漏报）"
            )
            return {
                "citation_verified": False,
                "refusal_reason": "",
                "messages": [{
                    "role": "system",
                    "content": (
                        "[零幻觉校验] 知识库无匹配依据但风险等级高，"
                        "允许继续生成工单（标记为待人工复核）"
                    ),
                }],
            }

        refusal = (
            f"知识库未检索到与当前隐患相关的法规/SOP依据。"
            f"根据零幻觉原则（拒绝率阈值={REFUSAL_CONFIDENCE_THRESHOLD}），"
            f"不生成无依据的分析建议。"
        )
        logger.warning(f"[HallucinationGuard] 拒答: {refusal}")
        return {
            "citation_verified": False,
            "refusal_reason": refusal,
            "llm_response": HallucinationGuard().build_refusal_response(refusal),
            "response_confidence": 0.0,
            "messages": [{
                "role": "system",
                "content": f"[零幻觉校验] 拒答 — {refusal[:120]}",
            }],
        }

    # 规则 2 & 3: 有高中置信度依据 → 通过
    if high > 0:
        logger.info(f"[HallucinationGuard] ✅ 通过 — 高置信度依据 {high} 条")
        return {
            "citation_verified": True,
            "refusal_reason": "",
            "messages": [{
                "role": "system",
                "content": (
                    f"[零幻觉校验] Pre-LLM 门控通过: "
                    f"高={high}, 中={medium}, 低={low}"
                ),
            }],
        }

    if medium > 0:
        logger.info(f"[HallucinationGuard] ⚠️ 通过 — 中置信度依据 {medium} 条（建议核实）")
        return {
            "citation_verified": True,
            "refusal_reason": "",
            "messages": [{
                "role": "system",
                "content": (
                    f"[零幻觉校验] Pre-LLM 门控通过（中置信度）: "
                    f"高={high}, 中={medium}, 低={low}。建议人工核实。"
                ),
            }],
        }

    # 规则 4: 仅有低置信度 → 拒答
    refusal = (
        f"检索结果仅有 {low} 条低置信度线索，"
        f"无高/中置信度法规依据。"
        f"根据零幻觉原则拒绝生成分析，建议人工核实后重试。"
    )
    logger.warning(f"[HallucinationGuard] 拒答: {refusal}")
    return {
        "citation_verified": False,
        "refusal_reason": refusal,
        "llm_response": HallucinationGuard().build_refusal_response(refusal),
        "response_confidence": 0.0,
        "messages": [{
            "role": "system",
            "content": f"[零幻觉校验] 拒答 — {refusal[:120]}",
        }],
    }


# =========================
# 🆕 功能6: LLM 合规分析节点
# =========================


async def llm_analysis_node(state: HazardState) -> Dict[str, Any]:
    """
    🆕 功能6: LLM 合规分析节点（强制引用链 Prompt）。

    调用 LLM 生成带有强制引用链的合规分析。
    Prompt 中嵌入三层引用规则（Pre-LLM Gate 已在 hallucination_guard_node 完成）。

    工作流程:
        1. 从 graph_context + memory_context 拼接知识上下文
        2. 构建带强制引用规则的 Guarded Prompt
        3. 调用 LLM（真实 API 或 Mock 降级）
        4. Post-LLM 校验：验证引用链、计算综合置信度
        5. 若综合置信度 < 拒答阈值 → 追加警告或拒答

    Args:
        state: 当前工作流状态（需含 graph_context、memory_context、detection_result）

    Returns:
        包含 llm_response、response_confidence、citation_verified 的部分状态更新
    """
    graph_context = state.get("graph_context", "")
    memory_context = state.get("memory_context", "")
    detection = state.get("detection_result", {})

    # 拼接知识上下文
    full_context = graph_context
    if memory_context:
        full_context += f"\n\n【历史经验参考】\n{memory_context}"

    # 构建查询
    findings = detection.get("findings", [])
    query_parts = []
    for f in findings:
        f_type = f.get("type", "")
        f_desc = f.get("description", "")
        query_parts.append(f"{f_type}: {f_desc}")
    query = "；".join(query_parts) if query_parts else "安全隐患合规分析"

    logger.info(f"[LLMAnalysis] 开始 LLM 合规分析: query='{query[:100]}'")

    try:
        guard = HallucinationGuard()

        # Step 1: 尝试真实 LLM 调用
        llm_response = await _call_llm_with_guarded_prompt(
            guard=guard,
            context=full_context,
            query=query,
            detection_result=detection,
        )

        # Step 2: Post-LLM 校验
        is_valid, issues = guard.verify_response(llm_response, full_context)

        # Step 3: 计算综合置信度
        confidence_info = _parse_context_confidence(graph_context)
        # 构建简化的检索结果用于置信度计算
        mock_retrieval: List[Dict[str, Any]] = []
        for _ in range(confidence_info["high_count"]):
            mock_retrieval.append({"score": 0.85, "confidence": "high"})
        for _ in range(confidence_info["medium_count"]):
            mock_retrieval.append({"score": 0.65, "confidence": "medium"})
        for _ in range(confidence_info["low_count"]):
            mock_retrieval.append({"score": 0.40, "confidence": "low"})

        confidence = guard.compute_confidence(llm_response, mock_retrieval or [{"score": 0.5, "confidence": "low"}])

        # Step 4: 校验未通过 → 追加警告
        if not is_valid:
            logger.warning(
                f"[LLMAnalysis] Post-LLM 校验未通过: {len(issues)} 个问题"
            )
            llm_response = guard.augment_with_warning(llm_response, issues)

        # Step 5: 综合置信度低于拒答阈值 → 追加高风险警告
        if confidence < REFUSAL_CONFIDENCE_THRESHOLD and not CitationVerifier.contains_refusal_markers(llm_response):
            logger.warning(
                f"[LLMAnalysis] 综合置信度 {confidence:.4f} < "
                f"阈值 {REFUSAL_CONFIDENCE_THRESHOLD}"
            )
            llm_response += (
                f"\n\n---\n"
                f"## ⚠️ 置信度警告\n\n"
                f"综合置信度 {confidence:.2%} 低于拒答阈值 {REFUSAL_CONFIDENCE_THRESHOLD:.0%}，"
                f"强烈建议人工安全员复核后采纳。\n"
            )

        logger.info(
            f"[LLMAnalysis] 完成: confidence={confidence:.4f}, "
            f"citations={CitationVerifier.count_citations(llm_response)}, "
            f"verified={is_valid}"
        )

        return {
            "llm_response": llm_response,
            "response_confidence": confidence,
            "citation_verified": is_valid,
            "messages": [{
                "role": "system",
                "content": (
                    f"[LLM分析] 合规分析完成: "
                    f"置信度={confidence:.2%}, "
                    f"引用数={CitationVerifier.count_citations(llm_response)}, "
                    f"校验={'通过' if is_valid else '未通过'}"
                ),
            }],
        }

    except Exception as e:
        logger.error(f"[LLMAnalysis] LLM 分析失败: {e}", exc_info=True)
        # 优雅降级：用 Mock 响应兜底
        mock_response = generate_mock_llm_response(
            context=full_context,
            query=query,
            detection_result=detection,
        )
        return {
            "llm_response": mock_response,
            "response_confidence": 0.5,
            "citation_verified": False,
            "messages": [{
                "role": "system",
                "content": f"[LLM分析] LLM 调用失败，降级为 Mock 响应: {e}",
            }],
        }


async def _call_llm_with_guarded_prompt(
    guard: HallucinationGuard,
    context: str,
    query: str,
    detection_result: Optional[Dict[str, Any]] = None,
) -> str:
    """
    调用 LLM 生成带强制引用链的分析响应。

    优先使用真实 LLM API（DeepSeek/OpenAI 兼容接口），
    未配置时降级为 Mock 响应。

    Args:
        guard: HallucinationGuard 实例
        context: 知识上下文
        query: 查询文本
        detection_result: 检测结果

    Returns:
        LLM 生成的响应文本
    """
    # 构建 Guarded Prompt
    prompt = guard.build_guarded_prompt(context, query, detection_result)

    # 尝试真实 LLM 调用
    try:
        from app.config import get_settings

        settings = get_settings()
        api_key = settings.llm.api_key
        base_url = settings.llm.base_url
        model_name = settings.llm.model_name
        timeout = settings.llm.timeout

        # 检查 API Key 是否已配置
        if not api_key or api_key.startswith("your-"):
            logger.info(
                "[LLMAnalysis] LLM API Key 未配置，使用 Mock 降级。"
                "请在 .env 中设置 LLM_API_KEY。"
            )
            return generate_mock_llm_response(context, query, detection_result)

        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model_name,
            temperature=0.1,  # 低温度以减少随机性
            timeout=timeout,
            max_tokens=2000,
        )

        logger.info(
            f"[LLMAnalysis] 调用 LLM: model={model_name}, "
            f"base_url={base_url}"
        )

        response = await llm.ainvoke(prompt)
        return str(response.content)

    except ImportError:
        logger.warning("[LLMAnalysis] langchain_openai 不可用，使用 Mock 降级")
        return generate_mock_llm_response(context, query, detection_result)

    except Exception as e:
        logger.error(f"[LLMAnalysis] LLM 调用失败: {e}", exc_info=True)
        raise  # 让调用方处理降级


# =========================
# 节点 4: 工单生成
# =========================


async def ticket_generation_node(state: HazardState) -> Dict[str, Any]:
    """
    工单数据组装节点。

    基于 detection_result + graph_context + memory_context + llm_response + 区域信息，
    组装结构化工单数据（title, description, priority, assignee）。

    🆕 功能6: 工单 description 中包含 LLM 合规分析的引用链摘要。

    Args:
        state: 当前工作流状态

    Returns:
        包含 ticket_data、ticket_status、messages 的部分状态更新
    """
    detection = state.get("detection_result", {})
    graph_context = state.get("graph_context", "")
    llm_response = state.get("llm_response", "")
    refusal_reason = state.get("refusal_reason", "")
    area_type = state.get("area_type", "")
    edge_node_id = state.get("edge_node_id", "")

    findings = detection.get("findings", [])
    risk_level = detection.get("risk_level", "medium")

    # 确定优先级映射
    priority_map = {"high": 1, "medium": 3, "low": 5, "none": 5}
    priority = priority_map.get(risk_level, 3)

    # 构建工单标题
    if findings:
        primary = findings[0]
        hazard_type = primary.get("type", "unknown")
        description_text = primary.get("description", "未知隐患")
        # 🆕 拒答场景的标题标记
        refusal_prefix = "⚠️[拒答] " if refusal_reason else ""
        title = f"{refusal_prefix}[{risk_level.upper()}] {hazard_type} - {area_type or '未知区域'}"
    else:
        hazard_type = "unknown"
        title = f"[{risk_level.upper()}] 未知隐患 - {area_type or '未知区域'}"
        description_text = "视觉分析未能识别具体隐患类型"

    # 🆕 功能6: 从 LLM 分析中提取引用链摘要
    citation_summary = ""
    if llm_response:
        # 提取 LLM 分析中的置信度声明段落
        citations = CitationVerifier.extract_citations(llm_response)
        if citations:
            unique_citations = list(dict.fromkeys(citations))  # 保序去重
            citation_summary = " | 引用链: " + "; ".join(unique_citations[:5])

    # 从 graph_context 提取法规摘要（前 200 字符）
    regulation_summary = ""
    if graph_context and "未找到" not in graph_context:
        lines = [ln for ln in graph_context.split("\n") if "法规" in ln or "SOP" in ln]
        if lines:
            regulation_summary = "; ".join(lines[:2])[:200]

    # 🆕 构建描述：包含 LLM 分析摘要 + 引用链
    description_parts = [description_text + "。"]

    if refusal_reason:
        description_parts.append(f"【零幻觉校验拒答】{refusal_reason}")

    if regulation_summary:
        description_parts.append(f"依据: {regulation_summary}")

    if citation_summary:
        description_parts.append(citation_summary)

    # 🆕 附上 LLM 分析摘要（前 500 字符）
    if llm_response and not refusal_reason:
        # 提取第一段分析内容
        analysis_short = llm_response[:500].replace("\n", " ").strip()
        description_parts.append(f"AI分析: {analysis_short}...")

    ticket_data: Dict[str, Any] = {
        "title": title,
        "description": "。".join(description_parts),
        "priority": priority,
        "assignee": "",  # 由后续 MCP 工具调用时指定
        "source_node": edge_node_id,
        "hazard_type": hazard_type,
        # 🆕 功能6: 附加零幻觉校验元数据
        "citation_verified": state.get("citation_verified", False),
        "response_confidence": state.get("response_confidence", 0.0),
    }

    logger.info(
        f"[TicketGen] 工单已组装: title='{title}', priority={priority}, "
        f"citation_verified={ticket_data.get('citation_verified')}, "
        f"confidence={ticket_data.get('response_confidence', 0):.2f}"
    )

    return {
        "ticket_data": ticket_data,
        "ticket_status": "created",
        "messages": [{
            "role": "system",
            "content": f"[工单生成] {title} (优先级: {priority}, 校验: {'通过' if ticket_data.get('citation_verified') else '未通过'})",
        }],
    }


# =========================
# 内部: 通用处理编排（消除 urgent/normal handler 重复）
# =========================


async def _handle_hazard(
    state: HazardState, is_urgent: bool
) -> Dict[str, Any]:
    """
    通用隐患处理编排：GraphRAG → 记忆检索 → 幻觉校验门控 → LLM分析 → 工单生成 → 工单推送。

    🆕 功能6: 新增零幻觉校验节点链:
        - hallucination_guard_node (Pre-LLM Gate): 检索置信度检查
        - llm_analysis_node (LLM + Post-LLM Gate): 强制引用链分析 + 引用校验

    urgent_handler_node 和 normal_handler_node 共享此实现。
    若 Pre-LLM Gate 拒答，跳过 LLM 分析，工单标记为拒答状态。

    Args:
        state: 当前工作流状态
        is_urgent: True=紧急处理, False=普通处理

    Returns:
        聚合全部节点的部分状态更新
    """
    label = "Urgent" if is_urgent else "Normal"
    logger.info(f"[{label}Handler] 启动{'紧急' if is_urgent else '普通'}处理流程")

    try:
        # ---- Step 1: GraphRAG 检索（法规/SOP） ----
        rag_result = await graph_rag_node(state)

        # ---- Step 2: 记忆检索（专家经验/反思教训） ----
        merged_state = {**state, **rag_result}
        memory_result = await memory_retrieval_node(merged_state)

        # ---- 🆕 Step 3: 零幻觉校验门控（Pre-LLM Gate） ----
        merged_state = {**merged_state, **memory_result}
        guard_result = await hallucination_guard_node(merged_state)

        # 若 Pre-LLM Gate 拒答，跳过 LLM 分析
        if guard_result.get("refusal_reason"):
            logger.warning(
                f"[{label}Handler] 零幻觉校验拒答，跳过 LLM 分析: "
                f"{guard_result['refusal_reason'][:100]}"
            )
            merged_state = {**merged_state, **guard_result}
            ticket_result = await ticket_generation_node(merged_state)
            merged_state = {**merged_state, **ticket_result}
            push_result = await ticket_push_node(merged_state)
            return {
                **rag_result, **memory_result, **guard_result,
                **ticket_result, **push_result,
            }

        # ---- 🆕 Step 4: LLM 合规分析（强制引用链 Prompt + Post-LLM Gate） ----
        merged_state = {**merged_state, **guard_result}
        llm_result = await llm_analysis_node(merged_state)

        # ---- Step 5: 工单生成（含 LLM 分析结果） ----
        merged_state = {**merged_state, **llm_result}
        ticket_result = await ticket_generation_node(merged_state)

        # ---- Step 6: 工单推送 ----
        merged_state = {**merged_state, **ticket_result}
        push_result = await ticket_push_node(merged_state)

        logger.info(
            f"[{label}Handler] 处理完成: "
            f"confidence={llm_result.get('response_confidence', 0):.2f}, "
            f"citation_verified={llm_result.get('citation_verified')}, "
            f"ticket_status={push_result.get('ticket_status')}"
        )
        return {
            **rag_result, **memory_result, **guard_result,
            **llm_result, **ticket_result, **push_result,
        }

    except Exception as e:
        logger.error(f"[{label}Handler] 处理失败: {e}", exc_info=True)
        return {
            "ticket_status": "failed",
            "messages": [{
                "role": "system",
                "content": f"[{'紧急' if is_urgent else '普通'}处理] 失败: {e}，已转人工。",
            }],
        }


# =========================
# 节点 5: 紧急处理编排
# =========================


async def urgent_handler_node(state: HazardState) -> Dict[str, Any]:
    """
    紧急隐患处理节点（high risk_level 专用）。

    委托 _handle_hazard(state, is_urgent=True)。
    """
    return await _handle_hazard(state, is_urgent=True)


# =========================
# 节点 6: 普通处理编排
# =========================


async def normal_handler_node(state: HazardState) -> Dict[str, Any]:
    """
    普通隐患处理节点（medium risk_level 专用）。

    委托 _handle_hazard(state, is_urgent=False)。
    """
    return await _handle_hazard(state, is_urgent=False)


# =========================
# 节点 7: 工单推送
# =========================


async def ticket_push_node(state: HazardState) -> Dict[str, Any]:
    """
    工单推送节点。

    调用 MCP 工具 create_ehs_ticket 将工单推送至企业微信/EHS 系统。
    推送失败时递增 retry_count，支持最大 3 次重试。

    Args:
        state: 当前工作流状态

    Returns:
        包含 ticket_status、retry_count、messages 的部分状态更新
    """
    ticket_data = state.get("ticket_data", {})
    retry_count = state.get("retry_count", 0)

    title = ticket_data.get("title", "未知工单")
    description = ticket_data.get("description", "")
    priority = ticket_data.get("priority", 3)
    assignee = ticket_data.get("assignee", "待分配")

    logger.info(f"[TicketPush] 推送工单: '{title}', retry={retry_count}")

    try:
        result = await create_ehs_ticket.ainvoke({
            "title": title,
            "description": description,
            "priority": priority,
            "assignee": assignee,
        })

        if "error" in result:
            new_retry = retry_count + 1
            logger.warning(
                f"[TicketPush] 推送失败 (retry {new_retry}/{MAX_RETRIES}): "
                f"{result.get('error')}"
            )
            return {
                "ticket_status": "failed",
                "retry_count": new_retry,
                "messages": [{
                    "role": "system",
                    "content": (
                        f"[工单推送] 失败 (重试 {new_retry}/{MAX_RETRIES}): "
                        f"{result.get('error')}"
                    ),
                }],
            }

        logger.info(f"[TicketPush] 推送成功: ticket_id={result.get('ticket_id')}")
        return {
            "ticket_status": "sent",
            "messages": [{
                "role": "system",
                "content": (
                    f"[工单推送] 成功! "
                    f"工单号: {result.get('ticket_id')}, "
                    f"状态: {result.get('status')}"
                ),
            }],
        }

    except Exception as e:
        new_retry = retry_count + 1
        logger.error(f"[TicketPush] 推送异常: {e}", exc_info=True)
        return {
            "ticket_status": "failed",
            "retry_count": new_retry,
            "messages": [{
                "role": "system",
                "content": f"[工单推送] 异常 (重试 {new_retry}/{MAX_RETRIES}): {e}",
            }],
        }
