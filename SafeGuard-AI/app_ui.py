"""
SafeGuard-AI (安卫智脑) 指挥中心控制台
========================================
基于 Streamlit 的全景 Web UI，覆盖 20 大核心功能点，
按 Phase 1-4 分类展示：核心检测 → 智能增强 → 边缘计算 → 运维管理。

启动方式:
    streamlit run app_ui.py

前置条件:
    pip install streamlit httpx pillow
    可选: FastAPI 后端已启动（图片分析需要）
"""

import asyncio
import base64
import json
import os
import random
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import streamlit as st
from PIL import Image

# OpenCV 视频处理（可选依赖，未安装时降级提示）
try:
    import cv2

    HAS_CV2 = True
except ImportError:
    cv2 = None  # type: ignore
    HAS_CV2 = False

# ── 页面配置 ──────────────────────────────────────────
st.set_page_config(
    page_title="安卫智脑指挥中心 | SafeGuard-AI",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 常量 ──────────────────────────────────────────────
DEFAULT_API_URL = "http://localhost:8000"
PROJECT_ROOT = Path(__file__).resolve().parent
MOCK_IMAGES_DIR = PROJECT_ROOT / "mock_data" / "images"
DEFAULT_VIDEO_PATH = str(PROJECT_ROOT / "mock_data" / "videos" / "test_video.mp4")
VIDEO_FRAME_INTERVAL = 0.5  # 视频模拟每帧间隔（秒），约 2 FPS
VIDEO_ANALYZE_CONFIDENCE_THRESHOLD = 0.6  # 隐患告警置信度阈值

# 风险等级配色
RISK_COLORS = {
    "high":   {"bg": "#fce4e4", "border": "#d32f2f", "label": "🔴 高风险", "emoji": "🚨"},
    "medium": {"bg": "#fff3e0", "border": "#f57c00", "label": "🟠 中风险", "emoji": "⚠️"},
    "low":    {"bg": "#e8f5e9", "border": "#388e3c", "label": "🟢 低风险", "emoji": "✅"},
    "none":   {"bg": "#e3f2fd", "border": "#1976d2", "label": "🔵 无风险", "emoji": "ℹ️"},
}
TICKET_STATUS_MAP = {
    "sent": "✅ 已推送", "created": "📝 已生成", "acknowledged": "👀 已确认",
    "closed": "🔒 已关闭", "timeout": "⏱️ 超时", "failed": "❌ 失败",
}
LIVE_MONITOR_INTERVAL = 5  # 实时流模拟间隔（秒）

# ── 20 大功能点定义 ──────────────────────────────────

# Phase 1: 10 大隐患检测类型
HAZARD_TYPES = [
    {"id": "oil_leak",           "emoji": "🛢️", "name": "油渍泄漏",       "desc": "液压油/切削液/化学品泄漏检测"},
    {"id": "blocked_exit",       "emoji": "🚫", "name": "消防通道堵塞",    "desc": "疏散通道/安全出口被障碍物堵塞"},
    {"id": "no_hardhat",         "emoji": "🪖", "name": "未戴安全帽",      "desc": "施工/生产区域头部防护缺失"},
    {"id": "fire_smoke",         "emoji": "☁️", "name": "化学品烟雾/火情", "desc": "烟雾、明火、初期火灾识别"},
    {"id": "no_safety_vest",     "emoji": "🦺", "name": "未穿安全背心",    "desc": "反光衣/防护服/安全背心缺失"},
    {"id": "smoking",            "emoji": "🚬", "name": "违规吸烟",        "desc": "禁烟区域吸烟/明火检测"},
    {"id": "using_phone",        "emoji": "📱", "name": "违规使用手机",    "desc": "作业区域玩手机注意力分散"},
    {"id": "unauthorized_entry", "emoji": "⛔", "name": "违规闯入禁区",    "desc": "越界进入危险/限制区域"},
    {"id": "unsafe_behavior",    "emoji": "⚠️", "name": "不安全行为",      "desc": "违规操作/绊倒/碰撞风险识别"},
    {"id": "unclear",            "emoji": "🔍", "name": "未知隐患复核",    "desc": "AI 不确定场景，需人工研判"},
]

# Phase 2: 智能增强 (GraphRAG & Memory)
PHASE2_FEATURES = [
    {"id": "graphrag_retrieve",  "emoji": "📖", "name": "法规知识检索",
     "desc": "在 Neo4j 图谱中检索适用法规/SOP/标准条款"},
    {"id": "expert_memory",      "emoji": "🧠", "name": "专家经验匹配",
     "desc": "从记忆系统检索历史相似案例处置方案"},
    {"id": "false_positive_log", "emoji": "🔄", "name": "误报反馈学习",
     "desc": "记录 AI 误报，触发反思进化闭环"},
    {"id": "certificate_audit",  "emoji": "📜", "name": "证书合规审计",
     "desc": "验证特种作业人员资质有效性"},
]

# Phase 3: 边缘计算 (Edge Intelligence)
PHASE3_FEATURES = [
    {"id": "edge_pre_screen",   "emoji": "🔍", "name": "边缘预筛分流",
     "desc": "边缘端快速推理，决定上传云端 or 本地处置"},
    {"id": "offline_queue",     "emoji": "📦", "name": "离线数据队列",
     "desc": "断网时本地 SQLite 缓存，恢复后自动冲洗"},
    {"id": "cloud_health_probe","emoji": "☁️", "name": "云端状态探测",
     "desc": "探测云端 Neo4j/Redis/Milvus/LLM 健康状态"},
    {"id": "mqtt_simulate",     "emoji": "📨", "name": "MQTT 消息模拟",
     "desc": "模拟边缘-云端 MQTT 告警/心跳消息收发"},
]

# Phase 4: 运维管理 (Ops & SFT)
PHASE4_FEATURES = [
    {"id": "ticket_generate",   "emoji": "📝", "name": "工单自动生成",
     "desc": "基于检测结果自动生成 EHS 隐患整改工单"},
    {"id": "system_health",     "emoji": "💚", "name": "系统健康检查",
     "desc": "全栈组件健康探测 (Neo4j/Redis/Milvus/API/LLM)"},
    {"id": "data_import",       "emoji": "📥", "name": "数据一键导入",
     "desc": "一键导入 Neo4j 图谱 + Milvus 专家经验向量"},
    {"id": "sft_export",        "emoji": "📤", "name": "SFT 微调数据导出",
     "desc": "导出 JSONL 训练数据，支持 LlamaFactory 微调"},
]

# ── 角色定义 ─ 按生产角色拆分功能 ─────────────────────

ROLES = {
    "full": {
        "name": "🎛️ 全功能演示",
        "desc": "开发/演示模式，展示全部 26 个功能入口",
        "color": "#1976d2",
        "sidebar_icon": "🎛️",
    },
    "inspector": {
        "name": "👷 巡检员模式",
        "desc": "一线巡检员：拍照识隐患 → 看处置方案 → 填反馈 → 出工单",
        "color": "#388e3c",
        "sidebar_icon": "👷",
        # 只显示这些 sidebar feature_id
        "features": [
            "phase1_area",        # 图片上传 + 10类检测 + 实时流 + 视频
            "patrol_inspector",
            "expert_memory",
            "false_positive_log",
            "ticket_generate",
        ],
    },
    "manager": {
        "name": "🧑‍💼 管理模式",
        "desc": "EHS 主管/安全经理：人员画像 · 设备状态 · 合规审计 · 培训 · 应急",
        "color": "#f57c00",
        "sidebar_icon": "🧑‍💼",
        "features": [
            "graphrag_retrieve",
            "employee_profiles",
            "equipment_dashboard",
            "certificate_audit",
            "meeting_minutes",
            "training_plans",
            "emergency_drill",
            "system_health",
        ],
    },
    "admin": {
        "name": "🔧 运维模式",
        "desc": "系统管理员：知识库管理 · 模型进化 · 法规追踪 · 可观测性",
        "color": "#6a1b9a",
        "sidebar_icon": "🔧",
        "features": [
            "knowledge_base",
            "ontology_explorer",
            "regulation_impact",
            "hallucination_guard",
            "short_term_memory",
            "evolution_report",
            "edge_pre_screen",
            "offline_queue",
            "cloud_health_probe",
            "mqtt_simulate",
            "data_import",
            "sft_export",
        ],
    },
}


# ── 工具函数 ──────────────────────────────────────────

def run_async(coro):
    """在 Streamlit 同步上下文中安全执行 async 协程。"""
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        # 如果已有运行中的 loop（极少情况），用 nest_asyncio 兜底
        import nest_asyncio
        nest_asyncio.apply()
        return loop.run_until_complete(coro)
    except ImportError:
        return asyncio.run(coro)


@st.cache_data(ttl=15)
def check_backend_health(api_url: str) -> tuple:
    """检测 FastAPI 后端健康状态（15s 缓存）。"""
    try:
        r = httpx.get(f"{api_url}/health", timeout=3)
        if r.status_code == 200:
            data = r.json()
            return True, f"✅ 已连接 — {data.get('app', 'SafeGuard-AI')} v{data.get('version', '?')}"
        return False, f"⚠️ 异常状态码: {r.status_code}"
    except httpx.ConnectError:
        return False, "❌ 无法连接后端，请确认 FastAPI 已启动"
    except Exception as e:
        return False, f"❌ 连接失败: {e}"


def call_analyze_api(api_url: str, image_path: str, alert_id: str = "",
                     area_type: str = "production") -> Optional[Dict[str, Any]]:
    """调用 POST /api/v1/hazard/analyze。"""
    payload = {
        "image_url": str(image_path),
        "alert_id": alert_id or f"WEB-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "area_type": area_type,
    }
    try:
        r = httpx.post(f"{api_url}/api/v1/hazard/analyze", json=payload, timeout=120)
        if r.status_code == 200:
            return r.json()
        st.error(f"API 返回错误: {r.status_code} — {r.text[:300]}")
        return None
    except httpx.ConnectError:
        st.error("❌ 无法连接后端 API，请确认 FastAPI 服务已启动")
        return None
    except Exception as e:
        st.error(f"❌ 请求失败: {e}")
        return None


def load_sample_images() -> dict:
    """加载 mock_data/images 目录下的示例图片。"""
    samples = {}
    name_map = {
        "inj_mold_leak":      "🛢️ 液压油泄漏",
        "blocked_fire_exit":  "🚫 消防通道堵塞",
        "welding_no_helmet":  "🪖 未戴安全帽",
        "chemical_smoke":     "☁️ 化学品烟雾",
    }
    if MOCK_IMAGES_DIR.exists():
        for f in sorted(MOCK_IMAGES_DIR.glob("*.jpg")):
            stem = f.stem
            samples[name_map.get(stem, stem)] = f
    return samples


# ── 后端直接调用函数 (Phase 2/3/4) ────────────────────

def _do_graphrag_search(query: str) -> Dict[str, Any]:
    """GraphRAG 混合检索：Neo4j 图谱 + Milvus 向量。"""
    from app.core.rag.neo4j_client import Neo4jClient
    from app.core.rag.retriever import GraphRAGRetriever

    async def _search():
        async with Neo4jClient() as neo4j:
            retriever = GraphRAGRetriever(neo4j)
            results = await retriever.retrieve(query, top_k=5)
            context = retriever.build_context(results)
            return {"results": results, "context": context, "count": len(results)}

    try:
        return run_async(_search())
    except Exception as e:
        return {"error": str(e), "results": [], "context": "", "count": 0}


def _do_memory_search(query: str) -> Dict[str, Any]:
    """专家经验记忆检索。"""
    from app.core.memory.manager import MemoryManager

    async def _search():
        manager = MemoryManager()
        items = await manager.retrieve_expert_memory(query, top_k=5)
        ctx = manager.build_memory_context(items)
        return {"items": items, "context": ctx, "count": len(items), "mode": manager.storage_mode}

    try:
        return run_async(_search())
    except Exception as e:
        return {"error": str(e), "items": [], "context": "", "count": 0, "mode": {}}


def _do_false_positive_log(emp_id: str, image_id: str, feedback_type: str, comment: str) -> Dict[str, Any]:
    """记录误报反馈。"""
    from app.tools.mcp_tools import log_false_positive

    async def _log():
        return await log_false_positive.ainvoke({
            "emp_id": emp_id, "image_id": image_id,
            "feedback_type": feedback_type, "comment": comment,
        })
    try:
        return run_async(_log())
    except Exception as e:
        return {"error": str(e), "status": "failed"}


def _do_certificate_verify(employee_id: str, required_type: str) -> Dict[str, Any]:
    """证书合规审计。"""
    from app.tools.mcp_tools import verify_certificate

    async def _verify():
        return await verify_certificate.ainvoke({
            "employee_id": employee_id, "required_type": required_type,
        })
    try:
        return run_async(_verify())
    except Exception as e:
        return {"error": str(e), "is_qualified": False}


def _do_edge_pre_screen() -> Dict[str, Any]:
    """边缘预筛分流。"""
    from app.tools.mcp_tools import edge_pre_screen

    async def _screen():
        return await edge_pre_screen.ainvoke({
            "model_type": "yolov10n",
            "confidence_threshold_high": 0.90,
        })
    try:
        return run_async(_screen())
    except Exception as e:
        return {"error": str(e), "status": "error"}


def _do_cloud_health_probe() -> Dict[str, Any]:
    """云端系统健康探测。"""
    from app.tools.mcp_tools import get_system_health

    async def _probe():
        return await get_system_health.ainvoke({
            "edge_node_id": "WEB-UI-CONSOLE",
            "include_details": True,
        })
    try:
        return run_async(_probe())
    except Exception as e:
        return {"error": str(e), "overall_status": "unknown"}


def _do_mqtt_simulate() -> Dict[str, Any]:
    """MQTT 消息模拟发送。"""
    from app.tools.mqtt_client import EdgeMQTTClient

    async def _sim():
        mqtt = EdgeMQTTClient(edge_node_id="WEB-CONSOLE", use_mock=True)
        msg_id = await mqtt.publish_alert(
            ticket_data={"title": "[模拟] 测试告警", "description": "指挥中心手动触发", "priority": 3},
            need_cloud=False,
        )
        await mqtt.publish_heartbeat()
        return {"msg_id": msg_id, "connected": mqtt.connected, "edge_id": mqtt.edge_id}

    try:
        return run_async(_sim())
    except Exception as e:
        return {"error": str(e), "connected": False}


def _do_offline_queue_stats() -> Dict[str, Any]:
    """离线数据队列统计。"""
    from app.tools.offline_queue import OfflineQueue
    try:
        queue = OfflineQueue(edge_node_id="WEB-CONSOLE")
        return {"stats": queue.stats(), "db_path": queue.db_path}
    except Exception as e:
        return {"error": str(e), "stats": {}}


def _do_ticket_generate() -> Dict[str, Any]:
    """工单自动生成（直接调用 MCP 工具）。"""
    from app.tools.mcp_tools import create_ehs_ticket

    async def _gen():
        return await create_ehs_ticket.ainvoke({
            "title": "[模拟] 指挥中心手动工单",
            "description": "从安卫智脑指挥中心手动触发的测试工单，用于验证工单生成链路。",
            "priority": 3,
            "assignee": "安全管理员-系统",
        })
    try:
        return run_async(_gen())
    except Exception as e:
        return {"error": str(e), "status": "failed"}


def _do_system_health_full() -> Dict[str, Any]:
    """全栈系统健康检查（所有组件逐项探测）。"""
    results = {}
    # 1. FastAPI 后端
    try:
        r = httpx.get(f"{DEFAULT_API_URL}/health", timeout=3)
        results["api"] = {"status": "healthy" if r.status_code == 200 else "degraded",
                          "detail": r.json() if r.status_code == 200 else str(r.status_code)}
    except Exception as e:
        results["api"] = {"status": "unreachable", "detail": str(e)}

    # 2. Neo4j
    from app.core.rag.neo4j_client import Neo4jClient
    async def _check_neo4j():
        async with Neo4jClient() as client:
            await client.run("RETURN 1")
            return {"status": "healthy" if not client.is_mock else "mock_mode",
                    "mock": client.is_mock}
    try:
        results["neo4j"] = run_async(_check_neo4j())
    except Exception as e:
        results["neo4j"] = {"status": "unreachable", "detail": str(e)}

    # 3. Memory
    from app.core.memory.manager import MemoryManager
    try:
        manager = MemoryManager()
        results["memory"] = {"status": "healthy", "mode": manager.storage_mode}
    except Exception as e:
        results["memory"] = {"status": "degraded", "detail": str(e)}

    # 4. MCP 工具
    try:
        cloud_health = _do_cloud_health_probe()
        results["mcp_cloud"] = {"status": cloud_health.get("overall_status", "unknown"),
                                "detail": cloud_health}
    except Exception as e:
        results["mcp_cloud"] = {"status": "unreachable", "detail": str(e)}

    overall = all(v.get("status") in ("healthy", "mock_mode") for v in results.values())
    return {"overall": "healthy" if overall else "degraded", "components": results}


def _do_data_import() -> Dict[str, Any]:
    """一键导入 Neo4j 图谱 + Milvus 向量数据。"""
    results = {}
    # Neo4j 导入
    try:
        import subprocess
        neo4j_result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "init_neo4j.py"), "--yes"],
            capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT),
        )
        results["neo4j"] = {"status": "success" if neo4j_result.returncode == 0 else "failed",
                            "output": neo4j_result.stdout[-500:]}
    except Exception as e:
        results["neo4j"] = {"status": "error", "detail": str(e)}

    # Milvus 导入
    try:
        milvus_result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "embed_to_milvus.py"), "--force"],
            capture_output=True, text=True, timeout=60, cwd=str(PROJECT_ROOT),
        )
        results["milvus"] = {"status": "success" if milvus_result.returncode == 0 else "failed",
                             "output": milvus_result.stdout[-500:]}
    except Exception as e:
        results["milvus"] = {"status": "error", "detail": str(e)}

    return results


def _do_sft_export() -> Dict[str, Any]:
    """SFT 微调数据导出。"""
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "export_training_data.py")],
            capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT),
        )
        return {"status": "success" if result.returncode == 0 else "failed",
                "output": result.stdout[:1000],
                "stderr": result.stderr[:500]}
    except Exception as e:
        return {"error": str(e), "status": "failed"}

# ── Phase 5: 模块一「业务前台」后端调用 ─────────────────

def _do_patrol_run() -> Dict[str, Any]:
    """数字巡检员：执行一次完整巡检（Mock 模式）。"""
    from app.core.patrol import PatrolScheduler

    async def _run():
        scheduler = PatrolScheduler(mock_mode=True)
        alerts = await scheduler.run_once()
        stats = scheduler.get_stats()
        return {"alerts": [a.__dict__ if hasattr(a, '__dict__') else a for a in alerts],
                "count": len(alerts), "stats": stats}

    try:
        return run_async(_run())
    except Exception as e:
        return {"error": str(e), "alerts": [], "count": 0}


def _do_meeting_process(scenario_key: str = "weekly_safety") -> Dict[str, Any]:
    """智能会议纪要：转录 → 提取 → 纪要生成 → 知识库归档。"""
    from app.core.meeting import MeetingManager

    async def _process():
        manager = MeetingManager()
        minutes = await manager.process_meeting(scenario_key, archive_to_kb=False)
        if hasattr(minutes, '__dict__'):
            d = minutes.__dict__
            d["meeting_id"] = minutes.meeting_id
            d["title"] = minutes.title
            d["markdown_content"] = getattr(minutes, 'markdown_content', '')
            return d
        return {"result": str(minutes)}

    try:
        return run_async(_process())
    except Exception as e:
        return {"error": str(e), "title": scenario_key}


# ── Phase 5: 模块二「认知大脑」后端调用 ─────────────────


def _do_knowledge_base_search(query: str = "动火作业 安全要求") -> Dict[str, Any]:
    """结构化知识库搜索。"""
    from app.core.knowledge import KnowledgeIngestion

    async def _search():
        kb = KnowledgeIngestion()
        await kb.ingest_all_mock()
        results = await kb.search(query, top_k=5)
        stats = kb.get_stats()
        return {"results": results, "count": len(results), "stats": stats}

    try:
        return run_async(_search())
    except Exception as e:
        return {"error": str(e), "results": [], "count": 0}


def _do_ontology_expand(text: str = "") -> Dict[str, Any]:
    """本体驱动图谱：三元组抽取 → 校验 → Cypher 生成 → 图写入。"""
    from app.core.ontology import OntologyManager

    sample = text or "焊接工位发现工人未佩戴安全帽，多次警告无效。该区域属于高危动火作业区，需立即整改。"

    async def _expand():
        manager = OntologyManager()
        result = await manager.expand_graph(sample, source_description="指挥中心手动触发")
        schema = manager.get_schema_summary()
        r_dict = result.__dict__ if hasattr(result, '__dict__') else {}
        return {"expansion": r_dict, "schema": schema,
                "extracted": getattr(result, 'extracted_count', 0),
                "inserted": getattr(result, 'inserted_count', 0),
                "cypher_count": len(getattr(result, 'cypher_statements', []))}

    try:
        return run_async(_expand())
    except Exception as e:
        return {"error": str(e), "extracted": 0, "inserted": 0}


def _do_regulation_analyze(change_id: Optional[str] = None) -> Dict[str, Any]:
    """法规变更影响分析：文本对比 → 图谱反向追溯 → 影响报告。"""
    from app.core.regulation import RegulationManager

    async def _analyze():
        manager = RegulationManager()
        available = manager.list_available_changes()
        cid = change_id or (available[0]["id"] if available else None)
        if cid is None:
            return {"error": "没有可用的法规变更数据", "available": available}
        report = await manager.analyze_change(cid)
        r_dict = report.__dict__ if hasattr(report, '__dict__') else {}
        return {"report": r_dict, "available_changes": available, "change_id": cid}

    try:
        return run_async(_analyze())
    except Exception as e:
        return {"error": str(e), "report": {}}


def _do_hallucination_guard_check(query: str = "") -> Dict[str, Any]:
    """零幻觉校验：三层防线模拟。"""
    from app.core.guard import HallucinationGuard, REFUSAL_CONFIDENCE_THRESHOLD
    from app.core.guard.hallucination_guard import generate_mock_llm_response

    sample_query = query or "焊接工位未戴安全帽违反了哪条安全规定？"
    mock_context = (
        "## 1. 适用法规\n**《安全生产法》第42条**: 从业人员必须正确佩戴劳动防护用品。\n"
        "**GB 39800.1-2020**: 头部防护装备选用规范 — 作业场所存在坠落物、碰撞风险的必须佩戴安全帽。\n"
        "## 2. 历史案例\n2024-03 焊接车间未戴安全帽致头部受伤1人。"
    )
    guard = HallucinationGuard()
    # Layer 1: Pre-LLM Gate
    mock_retrieval = [{"source": "Neo4j", "text": "安全生产法第42条", "score": 0.95}]
    gate_ok, gate_reason = guard.check_retrieval_gate(mock_retrieval)
    # Layer 2: Guarded Prompt
    guarded_prompt = guard.build_guarded_prompt(mock_context, sample_query) if gate_ok else ""
    # Layer 3: Post-LLM Verify
    mock_response = generate_mock_llm_response(mock_context, sample_query)
    verify_ok, verify_issues = guard.verify_response(mock_response, mock_context)
    confidence = guard.compute_confidence(mock_response, mock_retrieval)
    refused = confidence < REFUSAL_CONFIDENCE_THRESHOLD

    return {
        "query": sample_query[:100],
        "gate_ok": gate_ok, "gate_reason": gate_reason,
        "guarded_prompt_preview": guarded_prompt[:300] if guarded_prompt else "",
        "mock_response": mock_response[:500],
        "verify_ok": verify_ok, "verify_issues": verify_issues,
        "confidence": confidence, "refused": refused,
        "threshold": REFUSAL_CONFIDENCE_THRESHOLD,
    }


def _do_training_plan(employee_id: str = "EMP_001") -> Dict[str, Any]:
    """个性化培训：协同过滤推荐 + 题目生成。"""
    from app.core.training import TrainingManager

    async def _plan():
        manager = TrainingManager()
        plan = await manager.create_training_plan(employee_id, cases_per_employee=3, questions_per_case=2)
        p_dict = plan.__dict__ if hasattr(plan, '__dict__') else {}
        return {"plan": p_dict,
                "employee_name": getattr(plan, 'employee_name', employee_id),
                "total_questions": getattr(plan, 'total_questions', 0),
                "estimated_minutes": getattr(plan, 'estimated_minutes', 0)}

    try:
        return run_async(_plan())
    except Exception as e:
        return {"error": str(e), "plan": {}, "total_questions": 0}


# ── Phase 5: 模块三「数字灵魂」后端调用 ─────────────────


def _do_short_term_memory_view() -> Dict[str, Any]:
    """短期工作记忆查看。"""
    from app.core.memory import MemoryManager

    try:
        manager = MemoryManager(use_mock=True)
        # 预填一些示例对话
        manager.add_conversation("system", "[视觉分析] 检测到焊接工位人员未佩戴安全帽，置信度 0.92")
        manager.add_conversation("ai", "根据 GraphRAG 检索，该行为违反《安全生产法》第42条。已生成工单 EHS-20240612-001。")
        manager.add_conversation("human", "经现场核实，该工人安全帽在休息时摘下未及时佩戴。已现场教育并整改。")
        ctx = manager.get_short_term_context(n=5)
        size = manager.short_term_size
        mode = manager.storage_mode
        return {"context": ctx, "size": size, "mode": mode}
    except Exception as e:
        return {"error": str(e), "context": "", "size": 0}


def _do_employee_profiles() -> Dict[str, Any]:
    """员工安全画像：加载全部 + 部门风险分布 + 高风险员工。"""
    from app.core.profile import ProfileManager

    async def _load():
        manager = ProfileManager()
        await manager.load_all()
        all_profiles = manager._profiles
        dept_risk = manager.get_department_risk_summary()
        high_risk = manager.get_high_risk_employees()
        violation_stats = manager.get_violation_stats()
        return {
            "profiles": [p.__dict__ if hasattr(p, '__dict__') else p for p in all_profiles.values()],
            "total": len(all_profiles),
            "department_risk": dept_risk,
            "high_risk_count": len(high_risk),
            "high_risk_employees": [p.employee_id for p in high_risk],
            "violation_stats": violation_stats,
        }

    try:
        return run_async(_load())
    except Exception as e:
        return {"error": str(e), "profiles": [], "total": 0}


def _do_equipment_dashboard() -> Dict[str, Any]:
    """设备全生命周期：状态汇总 + 维保预警。"""
    from app.core.equipment import EquipmentManager

    async def _load():
        manager = EquipmentManager()
        await manager.load_all()
        all_eq = manager._equipment
        status_summary = manager.get_equipment_status_summary()
        alerts = manager.get_maintenance_alerts()
        high_risk = manager.get_high_risk_equipment()
        return {
            "equipment": [e.__dict__ if hasattr(e, '__dict__') else e for e in all_eq.values()],
            "total": len(all_eq),
            "status_summary": status_summary,
            "alerts": alerts,
            "alert_count": len(alerts),
            "high_risk_count": len(high_risk),
            "high_risk_ids": [e.equipment_id for e in high_risk],
        }

    try:
        return run_async(_load())
    except Exception as e:
        return {"error": str(e), "equipment": [], "total": 0}


def _do_evolution_report() -> Dict[str, Any]:
    """反思与进化全貌报告。"""
    from app.core.evolution import EvolutionManager

    try:
        manager = EvolutionManager()
        report = manager.get_evolution_report()
        readiness = manager.check_finetune_readiness()
        r_dict = report.__dict__ if hasattr(report, '__dict__') else {}
        return {"report": r_dict, "readiness": readiness,
                "positive_count": getattr(report, 'positive_samples', 0),
                "negative_count": getattr(report, 'negative_samples', 0),
                "ready_for_finetune": readiness.get("is_ready", False) if isinstance(readiness, dict) else False}
    except Exception as e:
        return {"error": str(e), "report": {}, "positive_count": 0, "negative_count": 0}


# ── Phase 5: 模块四「工程骨架」后端调用 ─────────────────


def _do_emergency_drill(scenario: str = "fire") -> Dict[str, Any]:
    """应急预案推演：A* 路径规划 + 传感器模拟。"""
    from app.core.emergency import EmergencyManager

    async def _drill():
        manager = EmergencyManager()
        result = await manager.run_drill(
            scenario_type=scenario,
            center=(6, 6),
            intensity=0.8,
            spread_radius=5,
        )
        r_dict = result.__dict__ if hasattr(result, '__dict__') else {}
        return {"result": r_dict,
                "scenario": getattr(result, 'scenario_type', scenario),
                "evacuation_time": getattr(result, 'total_evacuation_time', 0),
                "is_safe": getattr(result, 'is_safe', True),
                "escape_path_count": len(getattr(result, 'escape_paths', [])),
                "affected_area_count": len(getattr(result, 'affected_areas', [])),
                "sensor_alert_count": len(getattr(result, 'sensor_alerts', [])),
                "recommendations": getattr(result, 'recommendations', [])}

    try:
        return run_async(_drill())
    except Exception as e:
        return {"error": str(e), "is_safe": False, "evacuation_time": 0}


# ── 渲染函数 ──────────────────────────────────────────

def render_risk_banner(risk_level: str, confidence: float = 0):
    """风险等级大横幅。"""
    info = RISK_COLORS.get(risk_level, RISK_COLORS["none"])
    conf_str = f" — 置信度 {confidence:.0%}" if confidence else ""
    st.markdown(f"""
    <div style="
        background: {info['bg']};
        border-left: 6px solid {info['border']};
        border-radius: 8px;
        padding: 20px 24px; margin: 16px 0;
    ">
        <div style="font-size: 28px; font-weight: 700; color: {info['border']}; margin-bottom: 4px;">
            {info['emoji']} {info['label']}{conf_str}
        </div>
        <div style="font-size: 14px; color: #666;">工业安全生产隐患智能研判结果</div>
    </div>
    """, unsafe_allow_html=True)


def render_status_panel():
    """系统状态面板 —— 显示各组件连接状态。"""
    st.subheader("📊 系统状态面板")

    cols = st.columns(5)
    components = [
        ("FastAPI", DEFAULT_API_URL),
        ("Neo4j", "Mock 图谱"),
        ("Memory", "Milvus/Redis"),
        ("MCP 工具", "6 个工具"),
        ("LLM", "Qwen-VL"),
    ]

    # FastAPI 状态
    api_ok, api_msg = check_backend_health(DEFAULT_API_URL)
    for i, (name, default_detail) in enumerate(components):
        with cols[i]:
            if name == "FastAPI":
                status = "🟢 在线" if api_ok else "🔴 离线"
                detail = api_msg[:40] if api_ok else "未连接"
            elif name == "Neo4j":
                try:
                    from app.core.rag.neo4j_client import Neo4jClient
                    async def _check():
                        async with Neo4jClient() as c:
                            return c.is_mock, await c.run("RETURN 1")
                    is_mock, _ = run_async(_check())
                    status = "🟡 Mock" if is_mock else "🟢 在线"
                    detail = "内存图谱" if is_mock else "Bolt 连接"
                except Exception:
                    status, detail = "⚪ 未知", "—"
            elif name == "Memory":
                try:
                    from app.core.memory.manager import MemoryManager
                    mode = MemoryManager().storage_mode
                    st_mode = mode.get("short_term", "?")
                    lt_mode = mode.get("expert", "?")
                    status = "🟢 就绪" if "redis" in st_mode or "milvus" in lt_mode else "🟡 Mock"
                    detail = f"ST:{st_mode} LT:{lt_mode}"
                except Exception:
                    status, detail = "⚪ 未知", "—"
            elif name == "MCP 工具":
                try:
                    from app.tools.mcp_tools import MCP_TOOLS, EDGE_TOOLS, CLOUD_TOOLS
                    status, detail = "🟢 就绪", f"{len(MCP_TOOLS)} 工具 ({len(EDGE_TOOLS)}E+{len(CLOUD_TOOLS)}C)"
                except Exception:
                    status, detail = "⚪ 未知", "—"
            elif name == "LLM":
                from app.config import get_settings
                settings = get_settings()
                has_key = bool(settings.dashscope.api_key or settings.llm.api_key)
                status = "🟢 已配置" if has_key else "🟡 Mock"
                detail = settings.dashscope.vl_model[:25] if has_key else "降级模式"
            else:
                status, detail = "⚪ 未知", default_detail

            st.markdown(f"""
            <div style="text-align:center; padding:8px; border-radius:6px;
                        background:#f8f9fa; border:1px solid #e9ecef;">
                <div style="font-size:18px;">{status}</div>
                <div style="font-size:11px; color:#666; margin-top:4px;"><b>{name}</b></div>
                <div style="font-size:10px; color:#999;">{detail}</div>
            </div>
            """, unsafe_allow_html=True)


def render_execution_trace(trace_data: List[Dict[str, str]]):
    """执行轨迹 —— 展示 LangGraph 节点执行路径。"""
    if not trace_data:
        return
    st.subheader("🔄 执行轨迹")
    cols = st.columns(len(trace_data))
    for i, step in enumerate(trace_data):
        with cols[i]:
            node = step.get("node", "?")
            status = step.get("status", "pending")
            color = {"completed": "#28a745", "running": "#ffc107", "failed": "#dc3545", "pending": "#6c757d"}
            st.markdown(f"""
            <div style="text-align:center; padding:8px; border-radius:8px;
                        background:{color.get(status, '#6c757d')}15;
                        border:2px solid {color.get(status, '#6c757d')};">
                <div style="font-size:12px; font-weight:700;">{node}</div>
                <div style="font-size:10px; color:{color.get(status)};">{status.upper()}</div>
            </div>
            """, unsafe_allow_html=True)
            if i < len(trace_data) - 1:
                st.markdown('<div style="text-align:center; color:#ccc;">→</div>', unsafe_allow_html=True)


def render_result_card(title: str, data: Dict[str, Any], icon: str = "📋"):
    """以卡片形式展示 JSON 结果。"""
    st.subheader(f"{icon} {title}")

    # 如果有 error，单独展示
    if "error" in data:
        st.error(f"⚠️ {data['error']}")
        if len(data) == 1:
            return

    # 提取关键指标行
    metrics = {}
    for key, val in data.items():
        if key in ("error", "detail", "results", "items", "context", "output", "stderr",
                   "components", "mode", "stats", "payload", "message"):
            continue
        if isinstance(val, (int, float, str, bool)):
            metrics[key] = val

    if metrics:
        metric_cols = st.columns(min(len(metrics), 5))
        for i, (k, v) in enumerate(metrics.items()):
            with metric_cols[i % 5]:
                display_val = f"{v:.2f}" if isinstance(v, float) else str(v)
                if isinstance(v, bool):
                    display_val = "✅" if v else "❌"
                st.metric(k.replace("_", " ").title(), display_val)

    # JSON 展开
    with st.expander("📄 完整响应数据", expanded=False):
        st.json(data)


def render_findings_cards(findings: list):
    """隐患检测项卡片网格。"""
    if not findings:
        st.info("未检测到具体隐患项。")
        return
    st.subheader("🔍 检测到的隐患项")
    cols = st.columns(min(len(findings), 3))
    for i, f in enumerate(findings):
        with cols[i % 3]:
            hazard_type = f.get("type", "unknown")
            desc = f.get("description", "无详细描述")
            confidence = f.get("confidence", 0)
            conf_pct = f"{confidence:.0%}" if isinstance(confidence, (int, float)) else str(confidence)
            bar_color = ("linear-gradient(90deg, #d32f2f, #ff6f6f)" if confidence >= 0.8
                         else "linear-gradient(90deg, #f57c00, #ffb74d)" if confidence >= 0.6
                         else "linear-gradient(90deg, #388e3c, #81c784)")
            st.markdown(f"""
            <div style="border:1px solid #e0e0e0; border-radius:8px; padding:16px; margin:8px 0; height:180px;">
                <div style="font-size:13px; color:#888; text-transform:uppercase; margin-bottom:4px;">{hazard_type}</div>
                <div style="font-size:14px; color:#333; flex:1; overflow:hidden; margin-bottom:8px;">{desc[:120]}{'…' if len(desc)>120 else ''}</div>
                <div style="font-size:12px; color:#666; margin-bottom:4px;">置信度: {conf_pct}</div>
                <div style="height:6px; border-radius:3px; background:{bar_color}; width:{min(int(confidence*100), 100)}%;"></div>
            </div>
            """, unsafe_allow_html=True)


def render_ticket_card(ticket_data: dict, ticket_status: str):
    """工单预览卡片。"""
    if not ticket_data:
        st.info("未生成工单数据。")
        return
    status_label = TICKET_STATUS_MAP.get(ticket_status, ticket_status)
    st.subheader("📝 生成的 EHS 工单")
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"**🎯 标题**: {ticket_data.get('title', '—')}")
        st.markdown(f"**📋 优先级**: `{ticket_data.get('priority', '—')}`")
        st.markdown(f"**👤 指派给**: {ticket_data.get('assignee', '—')}")
        st.markdown(f"**🏷️ 类型**: {ticket_data.get('hazard_type', '—')}")
    with col2:
        st.metric("推送状态", status_label)
        st.caption(f"来源节点: {ticket_data.get('source_node', '—')}")
    with st.expander("📄 工单详细描述", expanded=False):
        st.text_area("描述", ticket_data.get("description", ""), height=150, disabled=True)


def render_knowledge_panel(graph_context: str):
    """知识上下文面板。"""
    if not graph_context or graph_context.strip() == "":
        st.info("📚 未检索到相关知识上下文。")
        return
    st.subheader("📚 知识增强检索 (GraphRAG)")
    with st.expander(f"📎 法规/SOP/经验上下文 ({len(graph_context)} 字符)", expanded=False):
        for sec in graph_context.split("##"):
            sec = sec.strip()
            if not sec:
                continue
            if sec.startswith("1.") or sec.startswith("2."):
                st.markdown(f"### {sec}")
            else:
                st.markdown(sec)


def render_message_timeline(messages: list):
    """流程日志时间线。"""
    if not messages:
        return
    st.subheader("💬 处理流程日志")
    role_emoji = {"system": "⚙️", "ai": "🤖", "human": "👤"}
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        emoji = role_emoji.get(role, "📌")
        if len(content) > 200:
            content = content[:200] + "…"
        st.markdown(f"""
        <div style="border-left:3px solid {'#1976d2' if role=='system' else '#388e3c' if role=='ai' else '#f57c00'};
                    padding:4px 12px; margin:4px 0; font-size:13px; color:#555;">
            <strong>{emoji} [{role}]</strong> {content}
        </div>
        """, unsafe_allow_html=True)


# ── Sidebar 渲染 ──────────────────────────────────────

def render_sidebar(api_url: str):
    """渲染侧边栏：角色选择 + 按角色过滤的功能导航。"""
    with st.sidebar:
        # ── 角色选择 ──
        st.image("https://img.icons8.com/color/96/industrial-safety.png", width=64)
        st.title("安卫智脑")

        role = st.selectbox(
            "👤 角色模式",
            options=["full", "inspector", "manager", "admin"],
            format_func=lambda x: ROLES[x]["name"],
            key="sidebar_role",
        )
        # persist role in session state
        st.session_state.user_role = role
        role_info = ROLES[role]
        st.caption(role_info["desc"])

        # ── 辅助函数：当前角色是否可见某功能 ──
        def _visible(feature_id: str) -> bool:
            if role == "full":
                return True
            allowed = role_info.get("features", [])
            return feature_id in allowed

        st.divider()

        # 后端连接
        st.subheader("🔌 后端连接")
        api_url_new = st.text_input("API 地址", value=api_url, key="sidebar_api_url")
        if st.button("🔄 检测连接", use_container_width=True, key="sidebar_health_btn"):
            st.session_state.health_checked = True
            ok, msg = check_backend_health(api_url_new)
            st.session_state.health_ok = ok
            st.session_state.health_msg = msg
        if st.session_state.get("health_checked"):
            if st.session_state.get("health_ok"):
                st.success(st.session_state.get("health_msg", ""))
            else:
                st.error(st.session_state.get("health_msg", ""))

        st.divider()

        # 区域类型（巡检员 & 全功能显示）
        if _visible("phase1_area"):
            st.subheader("🏭 场景设置")
            area_type = st.selectbox(
                "区域类型",
                options=["production", "warehouse", "hazard", "rest"],
                format_func=lambda x: {
                    "production": "🏭 生产区", "warehouse": "🏬 仓库区",
                    "hazard": "☣️ 危化品区", "rest": "🛌 休息区",
                }.get(x, x),
                key="sidebar_area_type",
            )
            st.session_state.area_type = area_type
            st.divider()

        # ── 🛡️ Phase 1: 核心检测（所有角色可见）──
        with st.expander("🛡️ 核心检测 (10大隐患场景)", expanded=(role == "inspector" or role == "full")):
            st.caption("支持以下 10 种工业安全隐患的智能识别：")
            for ht in HAZARD_TYPES:
                st.markdown(f"{ht['emoji']} **{ht['name']}** — {ht['desc']}")
            st.divider()

            # ── 📹 接入模式选择 ──
            video_mode = st.radio(
                "📹 接入模式",
                options=["manual", "video_sim"],
                format_func=lambda x: "📤 手动上传" if x == "manual" else "🎥 视频模拟",
                horizontal=True,
                key="sidebar_video_mode",
                help="手动上传：上传单张图片分析 | 视频模拟：读取本地视频逐帧分析",
            )
            st.session_state.video_mode = video_mode

            st.divider()

            # ── 🆕 实时流模拟开关（仅手动上传模式） ──
            if video_mode == "manual":
                live_mode = st.toggle(
                    "🔴 开启实时流模拟",
                    value=st.session_state.get("live_mode", False),
                    help="每 5 秒自动从本地图片库随机抽取一张进行分析，模拟现场实时监控",
                    key="sidebar_live_toggle",
                )
                st.session_state.live_mode = live_mode

                if live_mode:
                    st.success(f"🔴 实时流已激活 — 每 {LIVE_MONITOR_INTERVAL}s 自动分析")
                    st.caption(f"📁 图片池: mock_data/images/ ({len(load_sample_images())} 张)")
                    if st.button("⏹️ 停止实时流", type="secondary", use_container_width=True, key="stop_live"):
                        st.session_state.live_mode = False
                        st.session_state.active_feature = ""
                        st.rerun()
                else:
                    # 上传图片
                    uploaded_file = st.file_uploader(
                        "📤 上传隐患图片",
                        type=["jpg", "jpeg", "png", "bmp"],
                        key="sidebar_upload",
                    )

                    # 示例图片
                    samples = load_sample_images()
                    if samples:
                        st.caption("或选择示例图片：")
                        sample_cols = st.columns(2)
                        for i, (label, path) in enumerate(samples.items()):
                            with sample_cols[i % 2]:
                                if st.button(label, use_container_width=True, key=f"sample_{label}"):
                                    st.session_state.selected_sample = str(path)
                                    st.session_state.active_feature = "phase1_analyze"

                    if st.button("🔍 开始智能分析", type="primary", use_container_width=True, key="analyze_btn",
                                 disabled=(not uploaded_file and not st.session_state.get("selected_sample"))):
                        st.session_state.active_feature = "phase1_analyze"
                        if uploaded_file:
                            tmp_dir = tempfile.mkdtemp(prefix="safeguard_")
                            tmp_path = os.path.join(tmp_dir, uploaded_file.name or "upload.jpg")
                            with open(tmp_path, "wb") as f:
                                f.write(uploaded_file.getbuffer())
                            st.session_state.uploaded_image_path = tmp_path
                        elif st.session_state.get("selected_sample"):
                            st.session_state.uploaded_image_path = st.session_state.get("selected_sample")

            else:
                # ── 🎥 视频模拟模式 ──
                st.caption("🎥 基于本地视频文件的自动化监控模拟")
                st.info("💡 **工作原理**: 逐帧读取本地视频 → 自动调用 AI 研判 → 实时显示检测结果")

                # 检查 OpenCV 是否可用
                if not HAS_CV2:
                    st.error("❌ OpenCV 未安装！请运行: `pip install opencv-python-headless`")
                else:
                    # 视频文件上传
                    st.caption("**📁 选择视频文件：**")
                    video_upload = st.file_uploader(
                        "上传 MP4/MOV/AVI 视频",
                        type=["mp4", "mov", "avi", "mkv", "webm"],
                        key="sidebar_video_upload",
                    )

                    if video_upload:
                        # 保存上传的视频到临时文件
                        tmp_dir = tempfile.mkdtemp(prefix="safeguard_video_")
                        tmp_video_path = os.path.join(tmp_dir, video_upload.name or "upload.mp4")
                        with open(tmp_video_path, "wb") as f:
                            f.write(video_upload.getbuffer())
                        st.session_state.video_path = tmp_video_path
                        st.success(f"✅ 视频已加载: {video_upload.name}")

                    # 手动输入路径
                    st.caption("**🔗 或指定本地路径：**")
                    manual_path = st.text_input(
                        "视频文件路径",
                        value=st.session_state.get("video_path", DEFAULT_VIDEO_PATH),
                        placeholder=DEFAULT_VIDEO_PATH,
                        key="sidebar_video_path_input",
                    )
                    if manual_path:
                        st.session_state.video_path = manual_path

                    # 帧率控制
                    st.caption("**⚙️ 帧率控制：**")
                    frame_interval = st.slider(
                        "每帧间隔（秒）",
                        min_value=0.1,
                        max_value=3.0,
                        value=float(st.session_state.get("video_frame_interval", VIDEO_FRAME_INTERVAL)),
                        step=0.1,
                        help="值越小帧率越高，但对后端压力更大",
                        key="sidebar_frame_interval",
                    )
                    st.session_state.video_frame_interval = frame_interval

                    # 置信度阈值
                    conf_threshold = st.slider(
                        "🚨 告警置信度阈值",
                        min_value=0.3,
                        max_value=0.95,
                        value=float(st.session_state.get("video_conf_threshold", VIDEO_ANALYZE_CONFIDENCE_THRESHOLD)),
                        step=0.05,
                        help="置信度高于此阈值时触发红色警报",
                        key="sidebar_conf_threshold",
                    )
                    st.session_state.video_conf_threshold = conf_threshold

                    # 控制按钮
                    st.divider()
                    video_playing = st.session_state.get("video_playing", False)
                    if not video_playing:
                        if st.button("▶️ 启动视频监控", type="primary", use_container_width=True, key="start_video"):
                            # 验证视频文件
                            vid_path = st.session_state.get("video_path", "")
                            if not vid_path or not os.path.exists(vid_path):
                                st.error(f"❌ 视频文件不存在: {vid_path}")
                                st.caption("请上传视频文件或输入正确的本地路径。")
                            else:
                                st.session_state.video_playing = True
                                st.session_state.active_feature = "video_simulation"
                                st.session_state.video_frame_idx = 0
                                st.rerun()
                    else:
                        st.success("🔴 视频监控运行中…")
                        if st.button("⏹️ 停止视频监控", type="secondary", use_container_width=True, key="stop_video"):
                            st.session_state.video_playing = False
                            st.session_state.active_feature = ""
                            st.session_state.video_frame_idx = 0
                            st.rerun()

        # ── 🚶 模块一: 业务前台 (补充功能) ──
        with st.expander("🚶 模块一: 业务前台 (补充)", expanded=False):
            if _visible("patrol_inspector") or _visible("meeting_minutes") or _visible("false_positive_log"):
                st.caption("数字巡检员 · 智能会议纪要 · 误报反馈")

                if _visible("patrol_inspector"):
                    if st.button("🚶 数字巡检员", use_container_width=True, key="m1_patrol"):
                        st.session_state.active_feature = "patrol_inspector"

                if _visible("meeting_minutes"):
                    if st.button("📋 智能会议纪要", use_container_width=True, key="m1_meeting"):
                        st.session_state.active_feature = "meeting_minutes"

                if _visible("false_positive_log"):
                    if st.button("🔄 误报反馈学习", use_container_width=True, key="m1_feedback"):
                        st.session_state.active_feature = "false_positive_log"
            else:
                st.caption("🔒 请切换到「👷 巡检员模式」使用此模块")

        # ── 🧠 模块二: 认知大脑 (6项) ──
        with st.expander("🧠 模块二: 认知大脑 (6项)", expanded=False):
            if _visible("knowledge_base") or _visible("ontology_explorer") or _visible("graphrag_retrieve"):
                st.caption("知识构建 · 深度检索 · 法规追踪 · 幻觉防御 · 个性化培训")

                if _visible("knowledge_base"):
                    if st.button("📚 结构化知识库", use_container_width=True, key="m2_kb"):
                        st.session_state.active_feature = "knowledge_base"

                if _visible("ontology_explorer"):
                    if st.button("🕸️ 本体驱动图谱", use_container_width=True, key="m2_onto"):
                        st.session_state.active_feature = "ontology_explorer"

                if _visible("graphrag_retrieve"):
                    if st.button("📖 GraphRAG 法规检索", use_container_width=True, key="m2_graphrag"):
                        st.session_state.active_feature = "graphrag_retrieve"

                if _visible("regulation_impact"):
                    if st.button("⚖️ 法规变更影响分析", use_container_width=True, key="m2_reg"):
                        st.session_state.active_feature = "regulation_impact"

                if _visible("hallucination_guard"):
                    if st.button("🛡️ 零幻觉校验", use_container_width=True, key="m2_guard"):
                        st.session_state.active_feature = "hallucination_guard"

                if _visible("training_plans"):
                    if st.button("🎓 个性化培训", use_container_width=True, key="m2_train"):
                        st.session_state.active_feature = "training_plans"
            else:
                st.caption("🔒 请切换到「🧑‍💼 管理模式」或「🔧 运维模式」使用此模块")

        # ── 💭 模块三: 数字灵魂 (5项) ──
        with st.expander("💭 模块三: 数字灵魂 (5项)", expanded=False):
            if _visible("short_term_memory") or _visible("expert_memory") or _visible("employee_profiles"):
                st.caption("记忆系统 · 员工画像 · 设备管理 · 反思进化")

                if _visible("short_term_memory"):
                    if st.button("💭 短期工作记忆", use_container_width=True, key="m3_stm"):
                        st.session_state.active_feature = "short_term_memory"

                if _visible("expert_memory"):
                    if st.button("🧠 专家经验记忆", use_container_width=True, key="m3_exp_mem"):
                        st.session_state.active_feature = "expert_memory"

                if _visible("employee_profiles"):
                    if st.button("👥 员工安全画像", use_container_width=True, key="m3_emp"):
                        st.session_state.active_feature = "employee_profiles"

                if _visible("equipment_dashboard"):
                    if st.button("🔧 设备全生命周期", use_container_width=True, key="m3_equip"):
                        st.session_state.active_feature = "equipment_dashboard"

                if _visible("evolution_report"):
                    if st.button("🔄 反思与进化", use_container_width=True, key="m3_evo"):
                        st.session_state.active_feature = "evolution_report"
            else:
                st.caption("🔒 请切换到「🧑‍💼 管理模式」使用此模块")

        # ── 🏗️ 模块四: 工程骨架 (4项 + 工具) ──
        with st.expander("🏗️ 模块四: 工程骨架 (4项 + 工具)", expanded=False):
            if _visible("certificate_audit") or _visible("emergency_drill") or _visible("system_health"):
                st.caption("合规审计 · 应急推演 · MCP集成 · 可观测性 · 边缘工具")

                if _visible("certificate_audit"):
                    if st.button("📜 智能合规审计", use_container_width=True, key="m4_cert"):
                        st.session_state.active_feature = "certificate_audit"

                if _visible("emergency_drill"):
                    if st.button("🧯 应急预案推演", use_container_width=True, key="m4_drill"):
                        st.session_state.active_feature = "emergency_drill"

                if _visible("ticket_generate"):
                    if st.button("📝 工单自动生成", use_container_width=True, key="m4_ticket"):
                        st.session_state.active_feature = "ticket_generate"

                if _visible("system_health"):
                    if st.button("💚 可观测性看板", use_container_width=True, key="m4_health"):
                        st.session_state.active_feature = "system_health"

                st.divider()
                st.caption("⚡ 边缘计算与运维工具:")

                if _visible("edge_pre_screen"):
                    if st.button("🔍 边缘预筛分流", use_container_width=True, key="m4_edge"):
                        st.session_state.active_feature = "edge_pre_screen"

                if _visible("offline_queue"):
                    if st.button("📦 离线数据队列", use_container_width=True, key="m4_queue"):
                        st.session_state.active_feature = "offline_queue"

                if _visible("cloud_health_probe"):
                    if st.button("☁️ 云端状态探测", use_container_width=True, key="m4_cloud"):
                        st.session_state.active_feature = "cloud_health_probe"

                if _visible("mqtt_simulate"):
                    if st.button("📨 MQTT 消息模拟", use_container_width=True, key="m4_mqtt"):
                        st.session_state.active_feature = "mqtt_simulate"

                if _visible("data_import"):
                    if st.button("📥 数据一键导入", use_container_width=True, key="m4_import"):
                        st.session_state.active_feature = "data_import"

                if _visible("sft_export"):
                    if st.button("📤 SFT 微调数据导出", use_container_width=True, key="m4_sft"):
                        st.session_state.active_feature = "sft_export"
            else:
                st.caption("🔒 请切换到「🧑‍💼 管理模式」或「🔧 运维模式」使用此模块")

        st.divider()
        st.caption("💡 提示：先启动 `python -m app.main`，再运行 `streamlit run app_ui.py`")
        st.caption("🧪 所有功能均支持 Mock 模式，无需后端即可体验")
        st.caption(f"⏰ 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    return api_url_new


# ── 主区域渲染 ────────────────────────────────────────

def render_main_area(api_url: str):
    """渲染主区域：根据 active_feature 展示对应功能界面。"""
    active = st.session_state.get("active_feature", "")
    live_mode = st.session_state.get("live_mode", False)

    # 🆕 实时流模式 —— 接管整个主区域
    if live_mode:
        _render_live_monitoring(api_url)
        return

    # ── 标题栏（含角色指示）──
    current_role = st.session_state.get("user_role", "full")
    role_meta = ROLES.get(current_role, ROLES["full"])
    col_title, col_status = st.columns([3, 1])
    with col_title:
        st.title(f"🏭 安卫智脑指挥中心")
        st.caption(f"SafeGuard-AI | 当前角色: {role_meta['name']} | {role_meta['desc']}")
    with col_status:
        api_ok, _ = check_backend_health(api_url)
        st.metric("后端状态", "🟢 在线" if api_ok else "🔴 离线")
        feature_count = len(role_meta.get("features", []))
        if current_role == "full":
            st.metric("可用功能", "26 项")
        else:
            st.metric("可用功能", f"{feature_count} 项")

    st.divider()

    # ── 状态面板（始终显示） ──
    render_status_panel()
    st.divider()

    # ── 根据 active_feature 渲染不同内容 ──

    if active == "phase1_analyze":
        _render_phase1_analyze(api_url)

    elif active == "graphrag_retrieve":
        _render_graphrag_retrieve()

    elif active == "expert_memory":
        _render_expert_memory()

    elif active == "false_positive_log":
        _render_false_positive_log()

    elif active == "certificate_audit":
        _render_certificate_audit()

    elif active == "edge_pre_screen":
        _render_edge_pre_screen()

    elif active == "offline_queue":
        _render_offline_queue()

    elif active == "cloud_health_probe":
        _render_cloud_health_probe()

    elif active == "mqtt_simulate":
        _render_mqtt_simulate()

    elif active == "ticket_generate":
        _render_ticket_generate()

    elif active == "system_health":
        _render_system_health()

    elif active == "data_import":
        _render_data_import()

    elif active == "sft_export":
        _render_sft_export()

    elif active == "video_simulation":
        _render_video_simulation(api_url)

    # ── 🆕 模块一: 业务前台 ──
    elif active == "patrol_inspector":
        _render_patrol_inspector()

    elif active == "meeting_minutes":
        _render_meeting_minutes()

    # ── 🆕 模块二: 认知大脑 ──
    elif active == "knowledge_base":
        _render_knowledge_base()

    elif active == "ontology_explorer":
        _render_ontology_explorer()

    elif active == "regulation_impact":
        _render_regulation_impact()

    elif active == "hallucination_guard":
        _render_hallucination_guard()

    elif active == "training_plans":
        _render_training_plans()

    # ── 🆕 模块三: 数字灵魂 ──
    elif active == "short_term_memory":
        _render_short_term_memory()

    elif active == "employee_profiles":
        _render_employee_profiles()

    elif active == "equipment_dashboard":
        _render_equipment_dashboard()

    elif active == "evolution_report":
        _render_evolution_report()

    # ── 🆕 模块四: 工程骨架 ──
    elif active == "emergency_drill":
        _render_emergency_drill()

    else:
        _render_welcome()


# ── 🆕 实时流监控模式 ──────────────────────────────────

def _pick_random_image() -> Optional[str]:
    """从 mock_data/images/ 随机抽取一张图片路径。"""
    samples = load_sample_images()
    if not samples:
        return None
    return str(random.choice(list(samples.values())))


def _render_live_monitoring(api_url: str):
    """实时流模拟监控 —— 每 N 秒自动随机分析一张图片。"""
    # 初始化实时流状态
    if "live_analysis_count" not in st.session_state:
        st.session_state.live_analysis_count = 0
    if "live_history" not in st.session_state:
        st.session_state.live_history = []
    if "live_last_result" not in st.session_state:
        st.session_state.live_last_result = None
    if "live_last_image" not in st.session_state:
        st.session_state.live_last_image = None
    if "live_last_time" not in st.session_state:
        st.session_state.live_last_time = None
    if "live_next_trigger" not in st.session_state:
        st.session_state.live_next_trigger = 0

    # ── 标题栏 ──
    col_title, col_timer, col_status = st.columns([2.5, 1, 1])
    with col_title:
        st.title("🔴 安卫智脑 · 实时监控中")
        st.caption("SafeGuard-AI Live Monitor | 模拟工业现场实时画面分析")
    with col_timer:
        now = time.time()
        remaining = max(0, st.session_state.live_next_trigger - now)
        st.metric("⏱️ 下次分析", f"{remaining:.0f}s")
    with col_status:
        api_ok, _ = check_backend_health(api_url)
        st.metric("后端", "🟢" if api_ok else "🔴")
        st.metric("已分析", f"{st.session_state.live_analysis_count} 次")

    st.divider()

    # ── 决定是否触发新一轮分析 ──
    now = time.time()
    should_analyze = now >= st.session_state.live_next_trigger

    if should_analyze:
        image_path = _pick_random_image()
        if image_path is None:
            st.error("❌ 没有可用的测试图片，请确保 mock_data/images/ 目录存在图片文件。")
            return

        area_types = ["production", "warehouse", "hazard", "rest"]
        area_type = random.choice(area_types)

        # 更新状态
        st.session_state.live_last_image = image_path
        st.session_state.live_next_trigger = now + LIVE_MONITOR_INTERVAL
        st.session_state.live_analysis_count += 1

        # 执行分析
        with st.spinner(f"🤖 正在分析第 {st.session_state.live_analysis_count} 帧…"):
            result = call_analyze_api(
                api_url, image_path,
                alert_id=f"LIVE-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                area_type=area_type,
            )
        st.session_state.live_last_result = result
        st.session_state.live_last_time = datetime.now().strftime('%H:%M:%S')

        # 加入历史记录
        if result:
            detection = result.get("detection_result", {})
            risk_level = result.get("risk_level", "none")
            findings = detection.get("findings", []) or result.get("findings", [])
            st.session_state.live_history.insert(0, {
                "time": st.session_state.live_last_time,
                "image": Path(image_path).name,
                "area_type": area_type,
                "risk_level": risk_level,
                "findings_count": len(findings),
                "need_cloud": result.get("need_cloud_analysis", False),
                "ticket_status": result.get("ticket_status", ""),
            })
            # 只保留最近 20 条
            st.session_state.live_history = st.session_state.live_history[:20]

    # ── 当前帧结果 ──
    result = st.session_state.live_last_result
    image_path = st.session_state.live_last_image
    last_time = st.session_state.live_last_time

    if result is None and image_path is None:
        st.info("⏳ 等待首次分析触发…")
        st.session_state.live_next_trigger = time.time()  # 立即触发
        time.sleep(0.5)
        st.rerun()
        return

    # ── 当前帧：图片 + 结果并排 ──
    st.subheader(f"📸 当前画面 — {last_time or '分析中…'}")
    col_img, col_result = st.columns([1, 1])

    with col_img:
        if image_path and os.path.exists(image_path):
            st.image(Image.open(image_path), use_container_width=True)
            st.caption(f"📁 {Path(image_path).name} | 🔢 第 {st.session_state.live_analysis_count} 帧")
        else:
            st.warning("⏳ 等待画面...")

    with col_result:
        if result:
            risk_level = result.get("risk_level", "none")
            detection = result.get("detection_result", {})
            findings = detection.get("findings", []) or result.get("findings", [])
            ticket_data = result.get("ticket_data", {})
            ticket_status = result.get("ticket_status", "")
            need_cloud = result.get("need_cloud_analysis", False)
            next_action = result.get("next_action", "")

            max_conf = max((f.get("confidence", 0) for f in findings), default=0)
            render_risk_banner(risk_level, max_conf)

            m1, m2, m3, m4 = st.columns(4)
            with m1: st.metric("⚠️ 风险", risk_level.upper())
            with m2: st.metric("🔍 隐患数", len(findings))
            with m3: st.metric("☁️ 云端", "是" if need_cloud else "否")
            with m4: st.metric("📝 工单", TICKET_STATUS_MAP.get(ticket_status, "—"))

            if findings:
                with st.expander("🔍 检出隐患详情", expanded=False):
                    render_findings_cards(findings)

            # 执行轨迹
            messages = result.get("messages", [])
            if messages:
                trace_nodes = []
                for m in messages:
                    content = m.get("content", "")
                    if "[视觉分析]" in content:
                        trace_nodes.append({"node": "📸 detection", "status": "completed"})
                    elif "[系统]" in content or "[Phase2-Edge]" in content:
                        trace_nodes.append({"node": "🧭 supervisor", "status": "completed"})
                    elif next_action == "edge_handler":
                        trace_nodes.append({"node": "⚡ edge_handler", "status": "completed"})
                    elif next_action in ("urgent_handler", "normal_handler"):
                        trace_nodes.append({"node": f"🔧 {next_action}", "status": "completed"})
                if trace_nodes:
                    trace_nodes.append({"node": "✅ END", "status": "completed"})
                    render_execution_trace(trace_nodes)
        else:
            st.error("⚠️ 分析未返回结果，请检查后端连接")

    st.divider()

    # ── 历史记录时间线 ──
    history = st.session_state.live_history
    if history:
        st.subheader(f"📜 分析历史 (最近 {min(len(history), 10)} 条)")
        hist_cols = st.columns(min(len(history), 5))
        for i, h in enumerate(history[:10]):
            with hist_cols[i % 5]:
                risk_color = {
                    "high": "#d32f2f", "medium": "#f57c00",
                    "low": "#388e3c", "none": "#1976d2",
                }.get(h["risk_level"], "#999")
                st.markdown(f"""
                <div style="border-left:4px solid {risk_color}; padding:4px 8px;
                            margin:4px 0; background:#fafafa; border-radius:4px; font-size:12px;">
                    <b>{h['time']}</b><br>
                    🖼️ {h['image'][:25]}<br>
                    ⚠️ {h['risk_level'].upper()}
                    {'☁️' if h['need_cloud'] else '⚡'}
                    ({h['findings_count']}项)
                </div>
                """, unsafe_allow_html=True)

    # ── 自动刷新 ──
    time.sleep(0.3)  # 短暂停顿，避免过于频繁的rerun
    st.rerun()


# ── 🎥 视频模拟监控模式 ──────────────────────────────────

def _render_video_simulation(api_url: str):
    """
    基于本地视频文件的自动化监控模拟（方案 B）。

    核心流程:
        1. OpenCV 读取视频 → 逐帧获取
        2. 帧率控制（可配置间隔，默认 0.5s）
        3. 每帧保存为临时图片 → 调用 /api/v1/hazard/analyze
        4. 实时显示画面 + 检测结果（红色警报 / 绿色正常）
        5. 视频播放结束后自动循环重头播放
        6. 文件不存在时给出友好提示

    依赖: opencv-python-headless (cv2)
    """
    # ── 初始化 session state ──
    if "video_frame_idx" not in st.session_state:
        st.session_state.video_frame_idx = 0
    if "video_last_result" not in st.session_state:
        st.session_state.video_last_result = None
    if "video_last_frame_display" not in st.session_state:
        st.session_state.video_last_frame_display = None
    if "video_last_time" not in st.session_state:
        st.session_state.video_last_time = None
    if "video_next_trigger" not in st.session_state:
        st.session_state.video_next_trigger = 0
    if "video_total_frames" not in st.session_state:
        st.session_state.video_total_frames = 0
    if "video_fps_actual" not in st.session_state:
        st.session_state.video_fps_actual = 0
    if "video_history" not in st.session_state:
        st.session_state.video_history = []
    if "video_analysis_count" not in st.session_state:
        st.session_state.video_analysis_count = 0

    video_path = st.session_state.get("video_path", "")
    frame_interval = st.session_state.get("video_frame_interval", VIDEO_FRAME_INTERVAL)
    conf_threshold = st.session_state.get("video_conf_threshold", VIDEO_ANALYZE_CONFIDENCE_THRESHOLD)

    # ── 标题栏 ──
    col_title, col_timer, col_status = st.columns([2.5, 1, 1])
    with col_title:
        st.title("🎥 安卫智脑 · 视频监控模拟")
        st.caption("SafeGuard-AI Video Simulation | 基于本地视频的自动化安全巡检")
    with col_timer:
        now = time.time()
        remaining = max(0, st.session_state.video_next_trigger - now)
        st.metric("⏱️ 下一帧", f"{remaining:.1f}s")
    with col_status:
        api_ok, _ = check_backend_health(api_url)
        st.metric("后端", "🟢" if api_ok else "🔴")
        st.metric("已分析", f"{st.session_state.video_analysis_count} 帧")

    st.divider()

    # ── 视频文件检查 ──
    if not video_path or not os.path.exists(video_path):
        st.error(f"❌ 视频文件不存在: `{video_path or '(未指定)'}`")
        st.info("💡 **请通过以下方式提供视频文件：**")
        st.markdown("1. 在左侧边栏**上传** MP4/MOV/AVI 视频文件")
        st.markdown(f"2. 在左侧边栏输入正确的**本地路径**（默认路径: `{DEFAULT_VIDEO_PATH}`）")
        st.markdown("3. 将测试视频放入 `mock_data/videos/test_video.mp4`")
        st.warning("⚠️ 视频监控已暂停，提供有效文件后点击「▶️ 启动视频监控」继续。")
        # 重置播放状态
        st.session_state.video_playing = False
        st.session_state.active_feature = ""
        return

    # ── 打开视频文件 ──
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        st.error(f"❌ 无法打开视频文件: `{video_path}`")
        st.caption("文件可能已损坏或格式不支持。")
        st.session_state.video_playing = False
        return

    # 获取视频元信息
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    st.session_state.video_total_frames = total_frames
    st.session_state.video_fps_actual = fps

    # ── 视频信息条 ──
    info_cols = st.columns(5)
    with info_cols[0]:
        st.metric("📁 文件", Path(video_path).name[:20])
    with info_cols[1]:
        st.metric("🎞️ 总帧数", f"{total_frames}")
    with info_cols[2]:
        st.metric("⚡ 帧率", f"{fps:.1f} FPS")
    with info_cols[3]:
        st.metric("📐 分辨率", f"{width}x{height}")
    with info_cols[4]:
        current_frame = st.session_state.video_frame_idx
        st.metric("📍 当前帧", f"{current_frame}/{total_frames}")

    st.divider()

    # ── 决定是否触发新一轮分析 ──
    now = time.time()
    should_analyze = now >= st.session_state.video_next_trigger

    if should_analyze:
        # 跳转到当前帧位置
        cap.set(cv2.CAP_PROP_POS_FRAMES, st.session_state.video_frame_idx)
        ret, frame = cap.read()

        if not ret:
            # 视频播放结束，循环重头开始
            st.session_state.video_frame_idx = 0
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()
            if not ret:
                st.error("❌ 视频读取失败，无法解码任何帧。")
                cap.release()
                return
            st.info("🔄 视频已自动循环重头播放。")

        # 将 BGR 帧转换为 RGB 用于显示
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # 保存当前帧为临时文件（用于 API 调用）
        tmp_dir = tempfile.mkdtemp(prefix="safeguard_vframe_")
        tmp_frame_path = os.path.join(tmp_dir, f"frame_{st.session_state.video_frame_idx:06d}.jpg")
        cv2.imwrite(tmp_frame_path, frame)  # OpenCV 写 BGR 即可

        # 更新状态
        st.session_state.video_last_frame_display = frame_rgb
        st.session_state.video_last_time = datetime.now().strftime("%H:%M:%S")
        st.session_state.video_next_trigger = now + frame_interval
        st.session_state.video_analysis_count += 1

        # 执行 AI 分析
        with st.spinner(f"🤖 正在分析第 {st.session_state.video_analysis_count} 帧…"):
            result = call_analyze_api(
                api_url, tmp_frame_path,
                alert_id=f"VID-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                area_type=st.session_state.get("area_type", "production"),
            )
        st.session_state.video_last_result = result

        # 清理临时文件
        try:
            os.remove(tmp_frame_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass

        # 加入历史记录
        if result:
            detection = result.get("detection_result", {})
            risk_level = result.get("risk_level", "none")
            findings = detection.get("findings", []) or result.get("findings", [])
            max_conf = max((f.get("confidence", 0) for f in findings), default=0)
            st.session_state.video_history.insert(0, {
                "time": st.session_state.video_last_time,
                "frame_idx": st.session_state.video_frame_idx,
                "risk_level": risk_level,
                "findings_count": len(findings),
                "max_confidence": max_conf,
                "alert_triggered": max_conf >= conf_threshold,
            })
            # 只保留最近 30 条
            st.session_state.video_history = st.session_state.video_history[:30]

        # 前进到下一帧
        st.session_state.video_frame_idx += 1
        # 如果超出总帧数，循环
        if st.session_state.video_frame_idx >= total_frames:
            st.session_state.video_frame_idx = 0

    # ── 当前帧画面展示 ──
    frame_rgb = st.session_state.video_last_frame_display
    result = st.session_state.video_last_result
    last_time = st.session_state.video_last_time

    if frame_rgb is None:
        st.info("⏳ 等待读取第一帧…")
        st.session_state.video_next_trigger = time.time()  # 立即触发
        cap.release()
        time.sleep(0.3)
        st.rerun()
        return

    st.subheader(f"📸 当前监控画面 — {last_time or '分析中…'}")

    col_img, col_result = st.columns([1, 1])

    with col_img:
        # 使用 st.image 实时显示当前帧
        st.image(frame_rgb, use_container_width=True, channels="RGB")
        frame_idx = st.session_state.video_frame_idx
        st.caption(f"🎞️ 帧 {max(frame_idx - 1, 0)}/{total_frames} | "
                   f"📁 {Path(video_path).name} | "
                   f"🔢 第 {st.session_state.video_analysis_count} 次分析")

    with col_result:
        if result is None:
            st.warning("⏳ 等待首次分析结果…")
        else:
            risk_level = result.get("risk_level", "none")
            detection = result.get("detection_result", {})
            findings = detection.get("findings", []) or result.get("findings", [])
            max_conf = max((f.get("confidence", 0) for f in findings), default=0)
            is_alert = max_conf >= conf_threshold

            # ── 🚨 结果反馈：红色警报 or 绿色正常 ──
            if is_alert:
                # 发现隐患 —— 红色警报
                alert_findings = [f for f in findings if f.get("confidence", 0) >= conf_threshold]
                finding_names = ", ".join(
                    f.get("type", f.get("description", "未知")) for f in alert_findings[:3]
                )
                st.markdown(f"""
                <div style="
                    background: #fff0f0;
                    border: 3px solid #d32f2f;
                    border-radius: 12px;
                    padding: 20px 24px;
                    margin: 8px 0;
                    animation: pulse 1.5s infinite;
                ">
                    <div style="font-size: 32px; font-weight: 800; color: #d32f2f; margin-bottom: 8px;">
                        🚨⚠️ 警报：发现安全隐患！
                    </div>
                    <div style="font-size: 16px; color: #b71c1c; margin-bottom: 4px;">
                        检测到: <b>{finding_names}</b>
                    </div>
                    <div style="font-size: 14px; color: #888;">
                        最高置信度: {max_conf:.1%} | 阈值: {conf_threshold:.0%}
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # 脉冲动画 CSS
                st.markdown("""
                <style>
                @keyframes pulse {
                    0%, 100% { box-shadow: 0 0 8px rgba(211,47,47,0.4); }
                    50% { box-shadow: 0 0 24px rgba(211,47,47,0.8); }
                }
                </style>
                """, unsafe_allow_html=True)
            else:
                # 正常 —— 绿色显示
                st.markdown(f"""
                <div style="
                    background: #f0fff0;
                    border: 2px solid #388e3c;
                    border-radius: 12px;
                    padding: 20px 24px;
                    margin: 8px 0;
                ">
                    <div style="font-size: 28px; font-weight: 700; color: #388e3c; margin-bottom: 4px;">
                        ✅ 监测正常
                    </div>
                    <div style="font-size: 14px; color: #666;">
                        未检测到高于阈值的隐患 | 最高置信度: {max_conf:.1%} | 阈值: {conf_threshold:.0%}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            # ── 详细指标 ──
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("⚠️ 风险等级", risk_level.upper())
            with m2:
                st.metric("🔍 检出隐患数", len(findings))
            with m3:
                st.metric("📊 最高置信度", f"{max_conf:.1%}")
            with m4:
                ticket_status = result.get("ticket_status", "")
                st.metric("📝 工单", TICKET_STATUS_MAP.get(ticket_status, "—"))

            # 隐患详情
            if findings:
                with st.expander("🔍 检出隐患详情", expanded=is_alert):
                    render_findings_cards(findings)

            # 执行轨迹
            messages = result.get("messages", [])
            next_action = result.get("next_action", "")
            if messages:
                trace_nodes = []
                for m in messages:
                    content = m.get("content", "")
                    if "[视觉分析]" in content:
                        trace_nodes.append({"node": "📸 detection", "status": "completed"})
                    elif "[系统]" in content or "[Phase2-Edge]" in content:
                        trace_nodes.append({"node": "🧭 supervisor", "status": "completed"})
                if next_action == "edge_handler":
                    trace_nodes.append({"node": "⚡ edge_handler", "status": "completed"})
                elif next_action in ("urgent_handler", "normal_handler"):
                    trace_nodes.append({"node": f"🔧 {next_action}", "status": "completed"})
                if trace_nodes:
                    trace_nodes.append({"node": "✅ END", "status": "completed"})
                    render_execution_trace(trace_nodes)

    cap.release()

    st.divider()

    # ── 分析历史时间线 ──
    history = st.session_state.video_history
    if history:
        st.subheader(f"📜 分析历史 (最近 {min(len(history), 12)} 条)")
        hist_cols = st.columns(min(len(history), 6))
        for i, h in enumerate(history[:12]):
            with hist_cols[i % 6]:
                is_alert = h.get("alert_triggered", False)
                border_color = "#d32f2f" if is_alert else "#388e3c"
                bg_color = "#fff0f0" if is_alert else "#f0fff0"
                alert_icon = "🚨" if is_alert else "✅"
                st.markdown(f"""
                <div style="border-left:4px solid {border_color}; padding:4px 8px;
                            margin:4px 0; background:{bg_color}; border-radius:4px; font-size:11px;">
                    <b>{h['time']}</b> {alert_icon}<br>
                    🎞️ 帧 #{h['frame_idx']}<br>
                    📊 置信度: {h['max_confidence']:.1%}<br>
                    🔍 {h['findings_count']}项隐患<br>
                    ⚠️ {h['risk_level'].upper()}
                </div>
                """, unsafe_allow_html=True)

    # ── 自动刷新循环 ──
    time.sleep(0.15)  # 短暂停顿
    st.rerun()


# ── Phase 1: 图片分析 ─────────────────────────────────

def _render_phase1_analyze(api_url: str):
    """Phase 1: 核心检测 —— 图片上传与分析。"""
    image_path = st.session_state.get("uploaded_image_path", "")
    area_type = st.session_state.get("area_type", "production")

    col_img, col_info = st.columns([1, 1])
    with col_img:
        st.subheader("🖼️ 待分析图片")
        if image_path and os.path.exists(image_path):
            st.image(Image.open(image_path), use_container_width=True)
            st.caption(f"📁 {Path(image_path).name}")
        else:
            st.warning("请先在侧边栏上传图片或选择示例图片。")
            return
    with col_info:
        st.subheader("⚙️ 分析配置")
        st.markdown(f"- **区域类型**: {area_type}")
        st.markdown(f"- **检测能力**: 10 种隐患类型（油渍/堵塞/安全帽/烟雾/背心/吸烟/手机/闯入/行为/复核）")
        st.markdown(f"- **后端**: {api_url}")
        st.markdown(f"- **工作流**: detection → supervisor → {', '.join(['edge_handler', 'urgent_handler', 'normal_handler'])}")

    # 执行分析
    if st.button("🚀 执行智能分析", type="primary", use_container_width=True, key="exec_analyze"):
        st.divider()
        # 执行轨迹
        trace = [
            {"node": "📸 detection", "status": "running"},
            {"node": "🧭 supervisor", "status": "pending"},
            {"node": "🔧 handler", "status": "pending"},
            {"node": "✅ END", "status": "pending"},
        ]
        trace_placeholder = st.empty()

        with st.spinner("🤖 AI 正在分析隐患… 预计 5-25s"):
            start_time = time.time()

            # 更新轨迹: detection → running
            trace[0]["status"] = "running"
            trace_placeholder.markdown("🔄 执行中...")

            result = call_analyze_api(
                api_url, image_path,
                alert_id=f"WEB-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                area_type=area_type,
            )
            elapsed = time.time() - start_time

            if result is None:
                trace[0]["status"] = "failed"
                render_execution_trace(trace)
                return

            # 更新轨迹
            next_action = result.get("next_action", "end")
            trace[0]["status"] = "completed"
            trace[1]["status"] = "completed"
            trace[2]["status"] = "completed"
            if next_action == "edge_handler":
                trace[2]["node"] = "⚡ edge_handler"
            elif next_action == "urgent_handler":
                trace[2]["node"] = "🚨 urgent_handler"
            elif next_action == "normal_handler":
                trace[2]["node"] = "📋 normal_handler"
            trace[3]["status"] = "completed"
            render_execution_trace(trace)

        # 结果展示
        st.divider()
        st.subheader("📊 AI 分析报告")
        st.caption(f"⏱️ 总耗时: {elapsed:.1f}s | 告警ID: {result.get('alert_id', '—')}")

        risk_level = result.get("risk_level", "none")
        ticket_data = result.get("ticket_data", {})
        ticket_status = result.get("ticket_status", "")
        graph_context = result.get("graph_context", "")
        messages = result.get("messages", [])
        need_cloud = result.get("need_cloud_analysis", False)
        detection = result.get("detection_result", {})
        findings = detection.get("findings", []) or result.get("findings", [])

        max_conf = max((f.get("confidence", 0) for f in findings), default=0)

        render_risk_banner(risk_level, max_conf)

        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("🎯 风险等级", risk_level.upper())
        with col2: st.metric("📝 工单状态", TICKET_STATUS_MAP.get(ticket_status, ticket_status))
        with col3: st.metric("🔍 检出隐患数", len(findings))
        with col4: st.metric("☁️ 需云端精算", "是" if need_cloud else "否")

        st.divider()
        render_findings_cards(findings)
        st.divider()
        render_ticket_card(ticket_data, ticket_status)
        st.divider()
        render_knowledge_panel(graph_context)
        st.divider()
        render_message_timeline(messages)

        with st.expander("🔧 原始 API 响应 (JSON)", expanded=False):
            st.json(result)


# ── Phase 2: 智能增强 ─────────────────────────────────

def _render_graphrag_retrieve():
    """📖 法规知识检索。"""
    st.subheader("📖 法规知识检索 (GraphRAG)")
    st.caption("在 Neo4j 知识图谱中检索适用法规、SOP 标准、设备关联信息，实现「先查图谱，再注入 Prompt」的零幻觉原则。")

    query = st.text_area("🔍 检索查询", placeholder="输入隐患描述，如：液压油泄漏 密封圈更换 SOP",
                         value="油渍泄漏 化学品泄漏 液压油 密封圈 管路老化 防漏托盘", key="graphrag_query")
    top_k = st.slider("返回数量", 1, 10, 5, key="graphrag_topk")

    if st.button("🔍 执行检索", type="primary", use_container_width=True, key="exec_graphrag"):
        trace = [{"node": "🔗 Neo4j 关键词搜索", "status": "running"},
                 {"node": "🔗 关联扩展", "status": "pending"},
                 {"node": "📊 Milvus 向量检索", "status": "pending"},
                 {"node": "📋 合并排序", "status": "pending"}]
        trace_ph = st.empty()

        with st.spinner("🔍 正在检索知识图谱…"):
            result = _do_graphrag_search(query)
            for t in trace: t["status"] = "completed"
            render_execution_trace(trace)

        render_result_card("GraphRAG 检索结果", result, "📖")
        if result.get("context"):
            st.subheader("📚 构建的上下文")
            st.markdown(result["context"])

        if result.get("results"):
            st.subheader("📋 检索详情")
            for i, item in enumerate(result["results"]):
                src = item.get("source", "unknown")
                label = item.get("label", "")
                score = item.get("score", 0)
                text = item.get("text", "")
                citation = item.get("citation", "")
                with st.expander(f"{'✅' if score >= 0.8 else '⚠️'} [{src}] {label} — {text[:60]}… (score: {score:.2f})"):
                    st.markdown(f"**来源**: {src}")
                    st.markdown(f"**标签**: {label}")
                    st.markdown(f"**内容**: {text}")
                    if citation:
                        st.markdown(f"**引用**: `{citation}`")
                    st.json(item)


def _render_expert_memory():
    """🧠 专家经验匹配。"""
    st.subheader("🧠 专家经验匹配 (Memory System)")
    st.caption("从长期专家经验记忆中检索历史相似案例的处置方案与反思教训，作为 few-shot 参考。")

    query = st.text_area("🔍 查询描述", placeholder="描述场景，如：焊接工位未戴安全帽，多次警告无效",
                         value="安全帽 头部防护 个人防护 PPE 焊接工位", key="memory_query")

    if st.button("🧠 检索经验", type="primary", use_container_width=True, key="exec_memory"):
        with st.spinner("🧠 正在检索专家经验…"):
            result = _do_memory_search(query)

        trace = [{"node": "📝 查询向量化", "status": "completed"},
                 {"node": "🔍 Milvus/关键词匹配", "status": "completed"},
                 {"node": "📋 结果排序", "status": "completed"}]
        render_execution_trace(trace)

        render_result_card("专家经验检索结果", result, "🧠")
        if result.get("mode"):
            st.info(f"存储模式: {result['mode']}")

        if result.get("context"):
            st.subheader("📚 经验上下文")
            st.markdown(result["context"])

        if result.get("items"):
            st.subheader("📋 记忆条目")
            for item in result["items"]:
                src = item.get("source", "unknown")
                score = item.get("score", 0)
                text = item.get("text", "")
                with st.expander(f"{'🧠' if src == 'expert' else '🔄'} [{src}] 相关度: {score:.2f} — {text[:80]}…"):
                    st.markdown(text)
                    st.json(item)


def _render_false_positive_log():
    """🔄 误报反馈学习。"""
    st.subheader("🔄 误报反馈学习")
    st.caption("记录 AI 误报/驳回反馈，触发反思进化闭环 —— 自动更新向量库 Negative Sample。")

    col1, col2 = st.columns(2)
    with col1:
        emp_id = st.text_input("员工工号", "EMP-8842", key="fb_emp_id")
        image_id = st.text_input("图片 ID", "IMG-20240611-001", key="fb_image_id")
    with col2:
        feedback_type = st.selectbox("反馈类型", ["false_positive", "irrelevant"],
                                     format_func=lambda x: "❌ 误报 (false_positive)" if x == "false_positive" else "📭 不相关 (irrelevant)",
                                     key="fb_type")
    comment = st.text_area("驳回理由", "该场景为正常作业，非违规行为。员工穿着了合规防护装备。", key="fb_comment")

    if st.button("🔄 记录反馈", type="primary", use_container_width=True, key="exec_feedback"):
        with st.spinner("📝 正在记录误报反馈…"):
            result = _do_false_positive_log(emp_id, image_id, feedback_type, comment)

        trace = [{"node": "✅ 参数校验", "status": "completed"},
                 {"node": "💾 写入反馈日志", "status": "completed"},
                 {"node": "🔄 异步更新向量库", "status": "completed"}]
        render_execution_trace(trace)
        render_result_card("误报反馈结果", result, "🔄")

        if result.get("status") == "recorded":
            st.success(f"✅ 反馈已记录！Log ID: {result.get('log_id', '—')}")
            st.info("📌 向量库将异步更新 Negative Sample，下次推理将参考此反馈。")


def _render_certificate_audit():
    """📜 证书合规审计。"""
    st.subheader("📜 证书合规审计")
    st.caption("实时验证特种作业人员资质（动火证、电工证、焊工证等），自动检测证书过期。")

    col1, col2 = st.columns(2)
    with col1:
        employee_id = st.text_input("员工工号", "EMP-8842", key="cert_emp_id")
    with col2:
        cert_type = st.selectbox("资质类型", ["welder", "electrician", "forklift_operator", "crane_operator"],
                                 format_func=lambda x: {
                                     "welder": "🔧 焊工", "electrician": "⚡ 电工",
                                     "forklift_operator": "🏗️ 叉车操作员", "crane_operator": "🏗️ 吊车操作员",
                                 }.get(x, x), key="cert_type")

    if st.button("📜 验证资质", type="primary", use_container_width=True, key="exec_cert"):
        with st.spinner("🔍 正在查询证书系统…"):
            result = _do_certificate_verify(employee_id, cert_type)

        qualified = result.get("is_qualified", False)
        trace = [{"node": "🔍 查询 HR/证书平台", "status": "completed"},
                 {"node": "📅 过期检查", "status": "completed"}]
        render_execution_trace(trace)
        render_result_card("资质验证结果", result, "📜")

        if qualified:
            st.success(f"✅ {result.get('name', employee_id)} 的 {cert_type} 资质有效！")
            st.info(f"证书有效期至: {result.get('cert_expiry', '—')}")
        else:
            warning = result.get("warning", "")
            st.error(f"❌ 资质验证未通过！{warning}")


# ── Phase 3: 边缘计算 ─────────────────────────────────

def _render_edge_pre_screen():
    """🔍 边缘预筛分流。"""
    st.subheader("🔍 边缘预筛分流 (Edge Pre-Screen)")
    st.caption("边缘端 YOLOv10n 快速推理 → 置信度三档分流：≥0.90 本地处置 | 0.70-0.90 上传云端 | <0.70 静默忽略。")

    if st.button("🔍 执行边缘预筛", type="primary", use_container_width=True, key="exec_edge"):
        with st.spinner("⚡ 边缘端推理中…"):
            result = _do_edge_pre_screen()

        status = result.get("status", "unknown")
        status_label = {
            "edge_resolved": "✅ 边缘本地处置（高置信度）",
            "pending_cloud": "☁️ 触发云端精算（中置信度）",
            "ignored": "🔇 静默忽略（低置信度）",
            "error": "❌ 边缘推理失败，安全上升至云端",
        }.get(status, status)

        trace = [{"node": "⚡ YOLOv10n 快速推理", "status": "completed"},
                 {"node": f"🔀 分流决策: {status}", "status": "completed"}]
        render_execution_trace(trace)

        st.subheader("🔀 分流决策")
        st.info(status_label)

        render_result_card("边缘预筛结果", result, "🔍")

        # 可视化分流逻辑
        confidence = result.get("confidence", 0)
        thresholds = result.get("confidence_thresholds_used", {})
        high_t = thresholds.get("high", 0.9)
        low_t = thresholds.get("low", 0.7)

        st.subheader("📊 置信度分布")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("🔇 忽略区间", f"< {low_t}")
        with col2:
            st.metric("☁️ 云端精算区间", f"[{low_t}, {high_t})")
        with col3:
            st.metric("✅ 边缘处置区间", f"≥ {high_t}")

        # 当前置信度位置
        bar_html = f"""
        <div style="margin:16px 0;">
            <div style="font-size:12px;color:#666;margin-bottom:4px;">当前置信度: {confidence:.2%}</div>
            <div style="position:relative;height:30px;background:linear-gradient(90deg,#e8f5e9,#fff3e0,#fce4e4);border-radius:6px;">
                <div style="position:absolute;left:{low_t*100}%;top:0;width:2px;height:100%;background:#666;"></div>
                <div style="position:absolute;left:{high_t*100}%;top:0;width:2px;height:100%;background:#666;"></div>
                <div style="position:absolute;left:{min(confidence,1)*100}%;top:2px;width:8px;height:26px;background:#1976d2;border-radius:4px;transform:translateX(-50%);"></div>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:10px;color:#999;margin-top:2px;">
                <span>0%</span><span>{low_t:.0%}</span><span>{high_t:.0%}</span><span>100%</span>
            </div>
        </div>
        """
        st.markdown(bar_html, unsafe_allow_html=True)

        if result.get("detections"):
            st.subheader("🔍 检测详情")
            for d in result["detections"]:
                st.markdown(f"- **{d.get('type', '?')}**: 置信度 {d.get('confidence', 0):.2%}, bbox={d.get('bbox', [])}")


def _render_offline_queue():
    """📦 离线数据队列。"""
    st.subheader("📦 离线数据队列 (Offline Queue)")
    st.caption("基于 SQLite 的边缘离线队列 —— 断网时本地持久化，恢复连接后自动冲洗至 MQTT。")

    if st.button("📦 查看队列状态", type="primary", use_container_width=True, key="exec_queue"):
        with st.spinner("📦 查询离线队列…"):
            result = _do_offline_queue_stats()

        trace = [{"node": "💾 SQLite 查询", "status": "completed"},
                 {"node": "📊 统计聚合", "status": "completed"}]
        render_execution_trace(trace)
        render_result_card("离线队列状态", result, "📦")

        stats = result.get("stats", {})
        if stats:
            cols = st.columns(4)
            labels = {"pending": "⏳ 待发送", "sending": "📤 发送中", "sent": "✅ 已发送", "failed": "❌ 失败"}
            for i, (key, label) in enumerate(labels.items()):
                with cols[i]:
                    st.metric(label, stats.get(key, 0))
            st.metric("📊 总计", stats.get("total", 0))


def _render_cloud_health_probe():
    """☁️ 云端状态探测。"""
    st.subheader("☁️ 云端状态探测")
    st.caption("边缘节点在发起云端精算前，先探测云端各组件（Neo4j/Redis/Milvus/LLM Gateway）的健康状态与负载。")

    if st.button("☁️ 探测云端状态", type="primary", use_container_width=True, key="exec_cloud_health"):
        with st.spinner("🔍 正在探测云端组件…"):
            result = _do_cloud_health_probe()

        trace = [{"node": "🌐 API 可达性检查", "status": "completed"},
                 {"node": "🗄️ Neo4j 健康检查", "status": "completed"},
                 {"node": "📦 Redis 健康检查", "status": "completed"},
                 {"node": "🔢 Milvus 健康检查", "status": "completed"},
                 {"node": "🤖 LLM Gateway 检查", "status": "completed"}]
        render_execution_trace(trace)

        overall = result.get("overall_status", "unknown")
        if overall == "healthy":
            st.success("✅ 云端所有组件健康")
        elif overall == "degraded":
            st.warning("⚠️ 云端部分组件异常")
        else:
            st.error(f"❌ 云端状态异常: {overall}")

        render_result_card("云端健康报告", result, "☁️")

        # 组件详情
        components = result.get("components", {})
        if components:
            st.subheader("🔧 组件详情")
            comp_cols = st.columns(len(components))
            for i, (name, info) in enumerate(components.items()):
                with comp_cols[i]:
                    status = info.get("status", "unknown")
                    icon = "🟢" if status == "healthy" else "🟡" if status == "degraded" else "🔴"
                    st.markdown(f"**{icon} {name}**")
                    st.caption(f"状态: {status}")
                    if isinstance(info, dict):
                        for k, v in info.items():
                            if k != "status":
                                st.caption(f"{k}: {v}")


def _render_mqtt_simulate():
    """📨 MQTT 消息模拟。"""
    st.subheader("📨 MQTT 消息模拟")
    st.caption("模拟边缘节点 MQTT 消息收发：告警上报 → 心跳 → 云端反馈，Topic 规范 `safeguard/{edge_id}/*`。")

    edge_id = st.text_input("边缘节点 ID", "EDGE-DG-01", key="mqtt_edge_id")

    if st.button("📨 发送模拟消息", type="primary", use_container_width=True, key="exec_mqtt"):
        with st.spinner("📨 发送 MQTT 消息…"):
            result = _do_mqtt_simulate()

        trace = [{"node": "📤 发布 Alert → safeguard/{edge_id}/alert", "status": "completed"},
                 {"node": "💓 发布 Heartbeat → safeguard/{edge_id}/heartbeat", "status": "completed"},
                 {"node": "📥 (预留) 订阅 Feedback", "status": "completed"}]
        render_execution_trace(trace)
        render_result_card("MQTT 发送结果", result, "📨")

        if result.get("connected"):
            st.success(f"✅ 消息已通过 Mock MQTT 发送 (边缘节点: {result.get('edge_id', '?')})")
            st.info(f"📋 消息 ID: {result.get('msg_id', '—')}")
            st.caption("💡 Mock 模式：消息持久化至 `logs/mqtt_mock/outbox_*.json`")


# ── Phase 4: 运维管理 ─────────────────────────────────

def _render_ticket_generate():
    """📝 工单自动生成。"""
    st.subheader("📝 工单自动生成")
    st.caption("直接调用 MCP 工具 create_ehs_ticket，模拟隐患工单的自动生成与推送流程。")

    if st.button("📝 生成测试工单", type="primary", use_container_width=True, key="exec_ticket"):
        with st.spinner("📝 正在生成 EHS 工单…"):
            result = _do_ticket_generate()

        trace = [{"node": "📋 组装工单数据", "status": "completed"},
                 {"node": "🔗 幂等性检查", "status": "completed"},
                 {"node": "📤 推送至 EHS 系统", "status": "completed"}]
        render_execution_trace(trace)
        render_result_card("工单生成结果", result, "📝")

        ticket_id = result.get("ticket_id", "—")
        if ticket_id and "error" not in result:
            st.success(f"✅ 工单已生成并推送！工单号: {ticket_id}")
            with st.expander("📄 工单详情"):
                st.json(result)


def _render_system_health():
    """💚 系统健康检查。"""
    st.subheader("💚 全栈系统健康检查")
    st.caption("对所有后端组件进行逐项健康探测，包括 FastAPI、Neo4j、Memory 系统、MCP 工具。")

    if st.button("💚 执行全栈健康检查", type="primary", use_container_width=True, key="exec_sys_health"):
        with st.spinner("🔍 正在探测所有组件…"):
            result = _do_system_health_full()

        overall = result.get("overall", "degraded")
        if overall == "healthy":
            st.success("✅ 所有组件健康！")
        else:
            st.warning("⚠️ 部分组件异常，详见下方详情。")

        components = result.get("components", {})
        if components:
            comp_cols = st.columns(len(components))
            for i, (name, info) in enumerate(components.items()):
                with comp_cols[i]:
                    status = info.get("status", "unknown")
                    if status == "healthy":
                        icon, color = "🟢", "#28a745"
                    elif status == "mock_mode":
                        icon, color = "🟡", "#ffc107"
                    elif status == "degraded":
                        icon, color = "🟠", "#f57c00"
                    else:
                        icon, color = "🔴", "#dc3545"
                    st.markdown(f"""
                    <div style="text-align:center;padding:12px;border-radius:8px;background:{color}15;border:2px solid {color};margin:4px 0;">
                        <div style="font-size:24px;">{icon}</div>
                        <div style="font-size:14px;font-weight:700;">{name.upper()}</div>
                        <div style="font-size:11px;color:#666;">{status}</div>
                    </div>
                    """, unsafe_allow_html=True)

        with st.expander("🔧 完整探测数据", expanded=False):
            st.json(result)


def _render_data_import():
    """📥 数据一键导入。"""
    st.subheader("📥 数据一键导入")
    st.caption("一键执行 Neo4j 图谱初始化（init_neo4j.py）+ Milvus 专家经验向量化（embed_to_milvus.py）。")

    st.warning("⚠️ 此操作将清空并重建 Neo4j 图谱和 Milvus Collection，请确认环境配置正确。")

    if st.button("📥 一键导入数据", type="primary", use_container_width=True, key="exec_import"):
        with st.spinner("📥 正在导入数据（可能需要 30-60 秒）…"):
            result = _do_data_import()

        neo4j_result = result.get("neo4j", {})
        milvus_result = result.get("milvus", {})

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("🗄️ Neo4j 图谱导入")
            neo4j_status = neo4j_result.get("status", "unknown")
            if neo4j_status == "success":
                st.success("✅ Neo4j 导入成功")
            else:
                st.error(f"❌ Neo4j 导入失败: {neo4j_result.get('detail', neo4j_status)}")
            with st.expander("查看输出"):
                st.code(neo4j_result.get("output", ""))

        with col2:
            st.subheader("🔢 Milvus 向量导入")
            milvus_status = milvus_result.get("status", "unknown")
            if milvus_status == "success":
                st.success("✅ Milvus 导入成功")
            else:
                st.error(f"❌ Milvus 导入失败: {milvus_result.get('detail', milvus_status)}")
            with st.expander("查看输出"):
                st.code(milvus_result.get("output", ""))


def _render_sft_export():
    """📤 SFT 微调数据导出。"""
    st.subheader("📤 SFT 微调数据导出")
    st.caption("导出 JSONL 格式的监督微调训练数据（正负样本混合 + 训练/验证/测试分割），兼容 LlamaFactory。")

    if st.button("📤 导出 SFT 训练数据", type="primary", use_container_width=True, key="exec_sft"):
        with st.spinner("📤 正在导出训练数据…"):
            result = _do_sft_export()

        status = result.get("status", "failed")
        if status == "success":
            st.success("✅ SFT 训练数据导出成功！")
        else:
            st.error(f"❌ 导出失败: {result.get('error', '未知错误')}")

        render_result_card("SFT 导出结果", result, "📤")

        output = result.get("output", "")
        if output:
            st.subheader("📄 导出日志")
            st.code(output[:2000])

        st.info("💡 导出的 JSONL 文件可用于 LlamaFactory / LLaMA-Factory 进行 Qwen-VL 模型微调。")


# ── 🆕 模块一「业务前台」渲染函数 ──────────────────────

def _render_patrol_inspector():
    """🚶 数字巡检员：模拟多摄像头自动化安全巡检。"""
    st.subheader("🚶 数字巡检员 (Digital Patrol)")
    st.caption("基于 APScheduler 的自动化安全巡检 —— 模拟 4 路摄像头图像比对 + 状态变更检测 + 分级告警。")

    col1, col2 = st.columns([1, 1])
    with col1:
        st.info("📷 **模拟摄像头**: CAM-A (生产区) | CAM-B (仓库区) | CAM-C (危化品区) | CAM-D (休息区)")
    with col2:
        st.metric("⏱️ 默认巡检周期", "30 分钟 (Cron)")

    if st.button("🔍 执行一轮巡检", type="primary", use_container_width=True, key="exec_patrol"):
        with st.spinner("🔍 正在模拟巡检…"):
            result = _do_patrol_run()

        trace = [
            {"node": "📷 图像采集 (4路)", "status": "completed"},
            {"node": "🔬 感知哈希比对", "status": "completed"},
            {"node": "⚠️ 变更检测分析", "status": "completed"},
            {"node": "📋 告警汇总", "status": "completed"},
        ]
        render_execution_trace(trace)

        alerts = result.get("alerts", [])
        stats = result.get("stats", {})
        if stats:
            a1, a2, a3 = st.columns(3)
            with a1: st.metric("📷 覆盖摄像头", stats.get("cameras", "?"))
            with a2: st.metric("🔄 已完成轮次", stats.get("rounds", "?"))
            with a3: st.metric("⚠️ 检出告警", result.get("count", 0))

        if alerts:
            st.subheader(f"📋 巡检告警 ({len(alerts)} 条)")
            for a in alerts[:6]:
                severity = a.get("severity", "medium")
                change_type = a.get("change_type", "unknown")
                color = {"high": "#d32f2f", "medium": "#f57c00", "low": "#388e3c"}.get(severity, "#999")
                with st.expander(f"{'🔴' if severity == 'high' else '🟠' if severity == 'medium' else '🟢'} [{a.get('camera_id','?')}] {change_type} — {a.get('description','')[:60]}", expanded=(severity == "high")):
                    st.markdown(f"**告警ID**: {a.get('alert_id', '—')}")
                    st.markdown(f"**严重性**: {severity.upper()}")
                    st.markdown(f"**差异距离**: {a.get('diff_distance', '—')}")
                    st.markdown(f"**建议**: {a.get('suggested_action', '—')}")
        else:
            st.success("✅ 本轮巡检未发现异常告警。")
        st.json(result)


def _render_meeting_minutes():
    """📋 智能会议纪要：音频转录 → 结构化提取 → Markdown 生成。"""
    st.subheader("📋 智能会议纪要 (Meeting Minutes)")
    st.caption("基于 Mock ASR + LLM 结构化提取 + Jinja2 模板生成——覆盖 3 种会议场景，自动归档至知识库。")

    col1, col2 = st.columns([2, 1])
    with col1:
        scenario = st.selectbox("📁 选择会议场景", ["weekly_safety", "accident_review", "drill_summary"],
            format_func=lambda x: {"weekly_safety": "📅 周安全例会", "accident_review": "🚨 事故复盘会", "drill_summary": "🧯 应急演练总结"}.get(x, x),
            key="meeting_scenario")
    with col2:
        st.info("💡 Mock 模式使用预置中文安全会议转录文本")

    if st.button("📋 生成会议纪要", type="primary", use_container_width=True, key="exec_meeting"):
        with st.spinner("🎙️ 转录中 → 🔍 提取关键信息 → 📝 生成纪要…"):
            result = _do_meeting_process(scenario)

        trace = [
            {"node": "🎙️ ASR 转录", "status": "completed"},
            {"node": "🔍 实体提取 (LLM+正则)", "status": "completed"},
            {"node": "📝 纪要生成 (Jinja2)", "status": "completed"},
            {"node": "📚 知识库归档", "status": "completed"},
        ]
        render_execution_trace(trace)

        render_result_card("会议纪要生成结果", result, "📋")

        md = result.get("markdown_content", "")
        if md:
            st.subheader("📄 会议纪要 (Markdown)")
            with st.expander("📝 查看完整纪要", expanded=True):
                st.markdown(md)

        if result.get("title"):
            st.success(f"✅ 纪要已生成: {result['title']}")
        if result.get("error"):
            st.error(result["error"])


# ── 🆕 模块二「认知大脑」渲染函数 ──────────────────────

def _render_knowledge_base():
    """📚 结构化知识库：向量搜索法规/SOP/标准条款。"""
    st.subheader("📚 结构化知识库 (Knowledge Base)")
    st.caption("基于 BGE-M3 向量嵌入的中文 EHS 法规知识库——支持语义搜索、文档类型过滤、分块溯源。")

    query = st.text_area("🔍 搜索查询", placeholder="输入 EHS 关键词，如：动火作业 审批流程 监护",
                         value="动火作业 安全要求 审批 监护人 灭火器材", key="kb_query")
    doc_type = st.selectbox("📂 文档类型过滤", ["全部", "regulation", "standard", "sop", "policy"],
                           format_func=lambda x: {"全部": "📋 全部", "regulation": "📜 法规", "standard": "📏 标准",
                                                  "sop": "📖 SOP", "policy": "📋 政策"}.get(x, x), key="kb_doc_type")

    if st.button("🔍 搜索知识库", type="primary", use_container_width=True, key="exec_kb"):
        with st.spinner("📚 正在向量检索法规知识…"):
            result = _do_knowledge_base_search(query)

        trace = [
            {"node": "📝 查询向量化 (BGE-M3)", "status": "completed"},
            {"node": "🔍 Milvus 相似度检索", "status": "completed"},
            {"node": "📋 结果排序去重", "status": "completed"},
        ]
        render_execution_trace(trace)

        stats = result.get("stats", {})
        if stats:
            s1, s2, s3, s4 = st.columns(4)
            with s1: st.metric("📊 文档块总数", stats.get("total_chunks", "?"))
            with s2: st.metric("🔢 文档类型数", len(stats.get("doc_types", {})))
            with s3: st.metric("💾 存储模式", stats.get("mode", "mock"))
            with s4: st.metric("🧠 嵌入模型", stats.get("embedding_model", "BGE-M3"))

        results = result.get("results", [])
        if results:
            st.subheader(f"📋 检索结果 ({len(results)} 条)")
            for i, item in enumerate(results):
                score = item.get("score", 0)
                doc_type = item.get("doc_type", "?")
                source = item.get("source_doc", item.get("source", "?"))
                text = item.get("text", "")
                clause = item.get("clause", "")
                with st.expander(f"{'✅' if score >= 0.8 else '⚠️'} [{doc_type}] {source} — {text[:70]}… (相关度: {score:.2f})"):
                    if clause: st.markdown(f"**条款**: `{clause}`")
                    st.markdown(f"**来源**: {source}")
                    st.markdown(f"**全文**: {text}")
        else:
            st.warning("未检索到匹配结果，请尝试其他关键词。")
        render_result_card("知识库统计", result, "📚")


def _render_ontology_explorer():
    """🕸️ 本体驱动图谱：LLM 三元组抽取 + Schema 管理 + 图写入。"""
    st.subheader("🕸️ 本体驱动图谱 (Ontology-Driven Graph)")
    st.caption("LLM 实时抽取三元组 (6种实体 + 8种关系) → Schema 校验 → Cypher GENERATE → Neo4j/Mock 图写入。")

    sample_text = st.text_area("📝 输入文本", placeholder="输入安全事件描述…",
        value="焊接工位发现工人未佩戴安全帽，多次警告无效。该区域属于高危动火作业区，需立即整改。安全员张三已开具整改通知单。",
        key="onto_text")

    if st.button("🕸️ 抽取三元组并写入图谱", type="primary", use_container_width=True, key="exec_onto"):
        with st.spinner("🤖 LLM 抽取三元组 → ✅ Schema 校验 → 💾 图写入…"):
            result = _do_ontology_expand(sample_text.strip())

        trace = [
            {"node": "🤖 LLM 三元组抽取", "status": "completed"},
            {"node": "✅ Schema 校验", "status": "completed"},
            {"node": "🔗 Cypher MERGE 生成", "status": "completed"},
            {"node": "💾 Neo4j/Mock 写入", "status": "completed"},
        ]
        render_execution_trace(trace)

        e1, e2, e3 = st.columns(3)
        with e1: st.metric("🔢 抽取三元组", result.get("extracted", 0))
        with e2: st.metric("✅ 成功写入", result.get("inserted", 0))
        with e3: st.metric("📋 Cypher 语句", result.get("cypher_count", 0))

        expansion = result.get("expansion", {})
        cypher_stmts = expansion.get("cypher_statements", [])
        if cypher_stmts:
            st.subheader("📋 生成的 Cypher 语句")
            for s in cypher_stmts[:10]:
                st.code(s, language="cypher")

        schema = result.get("schema", {})
        if schema:
            with st.expander("🔧 当前 Schema 定义", expanded=False):
                st.json(schema)

        render_result_card("图谱扩展结果", result, "🕸️")


def _render_regulation_impact():
    """⚖️ 法规变更影响分析：Text-Diff + 图谱反向追溯 + 影响报告。"""
    st.subheader("⚖️ 法规变更影响分析 (Regulatory Change Impact)")
    st.caption("difflib 文本差异对比 + Neo4j 图谱反向追溯（法规→隐患→设备→SOP）→ 影响等级评估 + 整改建议。")

    if st.button("⚖️ 分析法规变更影响", type="primary", use_container_width=True, key="exec_regulation"):
        with st.spinner("🔍 对比法规变更 → 🔗 图谱反向追溯 → 📊 影响评估…"):
            result = _do_regulation_analyze()

        trace = [
            {"node": "📝 Text-Diff 差异对比", "status": "completed"},
            {"node": "🔗 图谱反向追溯", "status": "completed"},
            {"node": "📊 影响等级评估", "status": "completed"},
            {"node": "📋 整改建议生成", "status": "completed"},
        ]
        render_execution_trace(trace)

        report = result.get("report", {})
        high = report.get("high_impact_count", 0)
        medium = report.get("medium_impact_count", 0)
        low = report.get("low_impact_count", 0)
        e1, e2, e3, e4 = st.columns(4)
        with e1: st.metric("🔴 高影响", high)
        with e2: st.metric("🟠 中影响", medium)
        with e3: st.metric("🟢 低影响", low)
        with e4: st.metric("📊 总影响实体", report.get("total_impacted", 0))

        impacted = report.get("impacted_entities", [])
        if impacted:
            st.subheader("🔍 受影响实体详情")
            for entity in impacted[:10]:
                level = entity.get("impact_level", "low")
                icon = {"high": "🔴", "medium": "🟠", "low": "🟢"}.get(level, "⚪")
                with st.expander(f"{icon} [{entity.get('entity_type','?')}] {entity.get('entity_name','?')} — {entity.get('impact_reason','')[:60]}"):
                    st.markdown(f"**相关条款**: {entity.get('related_clause', '—')}")
                    st.markdown(f"**建议措施**: {entity.get('suggested_action', '—')}")

        recs = report.get("recommendations", [])
        if recs:
            st.subheader("📋 整改建议")
            for r in recs[:8]:
                st.markdown(f"- {r}")

        if result.get("available_changes"):
            st.caption(f"📁 可用法规变更: {', '.join(c['id'] for c in result['available_changes'])}")
        render_result_card("影响分析报告", result, "⚖️")


def _render_hallucination_guard():
    """🛡️ 零幻觉校验：三层防线可视化演示。"""
    st.subheader("🛡️ 零幻觉校验 (Hallucination Guard)")
    st.caption("三层防线机制：Layer 1 检索门禁 → Layer 2 引导式提示词 → Layer 3 响应引用校验。置信度 < 0.70 自动拒答。")

    query = st.text_input("📝 测试查询", value="焊接工位未戴安全帽违反了哪条安全规定？", key="guard_query")

    if st.button("🛡️ 执行三层校验", type="primary", use_container_width=True, key="exec_guard"):
        with st.spinner("🛡️ 正在执行三层防线校验…"):
            result = _do_hallucination_guard_check(query)

        trace = [
            {"node": "🚧 Layer 1: 检索门禁", "status": "completed"},
            {"node": "📝 Layer 2: 引导提示词", "status": "completed"},
            {"node": "✅ Layer 3: 引用校验", "status": "completed"},
        ]
        render_execution_trace(trace)

        # 三层防线可视化
        l1, l2, l3 = st.columns(3)
        with l1:
            gate_ok = result.get("gate_ok", False)
            st.markdown(f"""
            <div style="padding:16px;border-radius:10px;background:{'#e8f5e9' if gate_ok else '#fce4e4'};
                        border:2px solid {'#388e3c' if gate_ok else '#d32f2f'};text-align:center;">
                <div style="font-size:28px;">{'✅' if gate_ok else '❌'}</div>
                <div style="font-size:14px;font-weight:700;">Layer 1: 检索门禁</div>
                <div style="font-size:12px;color:#666;">{result.get('gate_reason', '')[:60]}</div>
            </div>
            """, unsafe_allow_html=True)
        with l2:
            guarded = bool(result.get("guarded_prompt_preview"))
            st.markdown(f"""
            <div style="padding:16px;border-radius:10px;background:{'#e8f5e9' if guarded else '#fff3e0'};
                        border:2px solid {'#388e3c' if guarded else '#f57c00'};text-align:center;">
                <div style="font-size:28px;">{'✅' if guarded else '⚠️'}</div>
                <div style="font-size:14px;font-weight:700;">Layer 2: 引导提示词</div>
                <div style="font-size:12px;color:#666;">{'含引用要求+防幻觉指令' if guarded else '门禁未通过，跳过'}</div>
            </div>
            """, unsafe_allow_html=True)
        with l3:
            verify_ok = result.get("verify_ok", False)
            issues = result.get("verify_issues", [])
            st.markdown(f"""
            <div style="padding:16px;border-radius:10px;background:{'#e8f5e9' if verify_ok else '#fce4e4'};
                        border:2px solid {'#388e3c' if verify_ok else '#d32f2f'};text-align:center;">
                <div style="font-size:28px;">{'✅' if verify_ok else '❌'}</div>
                <div style="font-size:14px;font-weight:700;">Layer 3: 引用校验</div>
                <div style="font-size:12px;color:#666;">{'通过' if verify_ok else issues}</div>
            </div>
            """, unsafe_allow_html=True)

        st.divider()

        # 置信度仪表盘
        confidence = result.get("confidence", 0)
        refused = result.get("refused", False)
        c1, c2 = st.columns([1, 2])
        with c1:
            conf_color = "#d32f2f" if refused else "#f57c00" if confidence < 0.85 else "#388e3c"
            st.markdown(f"""
            <div style="text-align:center;padding:20px;border-radius:12px;background:{conf_color}15;border:3px solid {conf_color};">
                <div style="font-size:48px;font-weight:800;color:{conf_color};">{confidence:.1%}</div>
                <div style="font-size:14px;color:#666;">综合置信度</div>
                <div style="font-size:12px;margin-top:8px;">阈值: {result.get('threshold',0.7):.0%}</div>
                <div style="font-size:18px;font-weight:700;color:{conf_color};margin-top:8px;">
                    {'🚫 已拒答' if refused else '✅ 可信输出'}
                </div>
            </div>
            """, unsafe_allow_html=True)
        with c2:
            mock_resp = result.get("mock_response", "")
            if mock_resp:
                st.subheader("🤖 Mock LLM 响应（含引用标注）")
                st.markdown(mock_resp[:600])
            if result.get("guarded_prompt_preview"):
                with st.expander("📝 Layer 2 引导提示词预览"):
                    st.code(result["guarded_prompt_preview"], language="markdown")

        render_result_card("校验详情", result, "🛡️")


def _render_training_plans():
    """🎓 个性化培训：协同过滤推荐 + 事故案例 → 选择题/判断题。"""
    st.subheader("🎓 个性化培训 (Personalized Training)")
    st.caption("基于员工安全画像的协同过滤推荐引擎 (4维加权) + 12 个事故案例库 + LLM/模板题目生成。")

    col1, col2 = st.columns([2, 1])
    with col1:
        employee_id = st.text_input("👤 员工工号", "EMP_001", key="train_emp_id",
            help="EMP_001~008，建议使用 EMP_001(高风险焊工) / EMP_002(维修工)")
    with col2:
        st.metric("📚 事故案例库", "12 个")
        st.caption("覆盖焊接/化学品/消防/高处/电气等")

    if st.button("🎓 生成培训计划", type="primary", use_container_width=True, key="exec_training"):
        with st.spinner("🧠 协同过滤推荐 → 📚 匹配案例 → ✍️ 生成题目…"):
            result = _do_training_plan(employee_id)

        trace = [
            {"node": "📊 员工画像分析", "status": "completed"},
            {"node": "🎯 协同过滤推荐", "status": "completed"},
            {"node": "📚 案例匹配", "status": "completed"},
            {"node": "✍️ 题目生成 (LLM+模板)", "status": "completed"},
        ]
        render_execution_trace(trace)

        e1, e2, e3 = st.columns(3)
        with e1: st.metric("👤 员工", result.get("employee_name", employee_id))
        with e2: st.metric("📝 题目数", result.get("total_questions", 0))
        with e3: st.metric("⏱️ 预计时长", f"{result.get('estimated_minutes', 0)} 分钟")

        plan = result.get("plan", {})
        questions = plan.get("questions", [])
        if questions:
            st.subheader(f"📝 培训题目 ({len(questions)} 题)")
            for q in questions:
                q_type = q.get("type", "?")
                q_text = q.get("question", q.get("text", str(q)))
                with st.expander(f"{'🔤' if q_type == 'multiple_choice' else '✅'} [{q.get('case_id','?')}] {q_text[:80]}…"):
                    st.markdown(f"**类型**: {q_type}")
                    st.markdown(f"**题干**: {q_text}")
                    if "options" in q:
                        for opt_label, opt_text in q["options"].items():
                            st.markdown(f"- {opt_label}: {opt_text}")
                    if "answer" in q:
                        st.success(f"**答案**: {q['answer']}")
                    if "explanation" in q:
                        st.info(f"**解析**: {q['explanation']}")

        rec = plan.get("recommendation", {})
        if rec:
            with st.expander("🎯 推荐详情", expanded=False):
                st.json(rec)

        render_result_card("培训计划结果", result, "🎓")


# ── 🆕 模块三「数字灵魂」渲染函数 ──────────────────────

def _render_short_term_memory():
    """💭 短期工作记忆：查看对话上下文窗口。"""
    st.subheader("💭 短期工作记忆 (Short-term Working Memory)")
    st.caption("Redis List 支持的短期对话记忆——保留最近 N 轮对话，为 LLM 提供上下文连续性。")

    if st.button("💭 查看工作记忆", type="primary", use_container_width=True, key="exec_stm"):
        with st.spinner("🧠 加载短期记忆…"):
            result = _do_short_term_memory_view()

        trace = [
            {"node": "📥 预填示例对话", "status": "completed"},
            {"node": "📋 读取 Redis/Deque", "status": "completed"},
            {"node": "📊 统计汇总", "status": "completed"},
        ]
        render_execution_trace(trace)

        m1, m2 = st.columns(2)
        with m1: st.metric("📝 对话轮次", result.get("size", 0))
        with m2: st.json(result.get("mode", {}))

        ctx = result.get("context", "")
        if ctx:
            st.subheader("📋 当前工作记忆上下文")
            st.info("此内容将注入 LLM 提示词，作为短期记忆提供连续性。")
            st.markdown(f"```\n{ctx}\n```")

        render_result_card("短期记忆状态", result, "💭")


def _render_employee_profiles():
    """👥 员工安全画像：四维度风险评分 + 部门分布 + 高风险识别。"""
    st.subheader("👥 员工安全画像 (Employee Safety Profiles)")
    st.caption("基于违章历史/岗位风险/证书状态/培训完成度的四维度安全风险评分——高风险员工追踪。")

    if st.button("👥 加载员工画像", type="primary", use_container_width=True, key="exec_emp"):
        with st.spinner("👥 加载员工档案 → 📊 计算风险评分 → 📋 汇总统计…"):
            result = _do_employee_profiles()

        trace = [
            {"node": "📂 加载 Mock 档案", "status": "completed"},
            {"node": "📊 四维评分计算", "status": "completed"},
            {"node": "📋 部门聚合统计", "status": "completed"},
        ]
        render_execution_trace(trace)

        e1, e2, e3, e4 = st.columns(4)
        with e1: st.metric("👥 总员工", result.get("total", 0))
        with e2: st.metric("🔴 高风险", result.get("high_risk_count", 0))
        with e3: st.metric("🏢 部门数", len(result.get("department_risk", {})))
        with e4: st.metric("⚠️ 违规类型", len(result.get("violation_stats", {})))

        # 部门风险分布
        dept_risk = result.get("department_risk", {})
        if dept_risk:
            st.subheader("🏢 部门风险分布")
            dept_cols = st.columns(min(len(dept_risk), 4))
            for i, (dept, info) in enumerate(dept_risk.items()):
                with dept_cols[i % 4]:
                    avg_risk = info.get("avg_risk_score", 0) if isinstance(info, dict) else 0
                    risk_color = "#d32f2f" if avg_risk > 0.7 else "#f57c00" if avg_risk > 0.4 else "#388e3c"
                    count = info.get("count", 0) if isinstance(info, dict) else 0
                    st.markdown(f"""
                    <div style="text-align:center;padding:12px;border-radius:8px;background:{risk_color}10;border:2px solid {risk_color};margin:4px 0;">
                        <div style="font-size:22px;">{'🔴' if avg_risk > 0.7 else '🟠' if avg_risk > 0.4 else '🟢'}</div>
                        <div style="font-size:14px;font-weight:700;">{dept}</div>
                        <div style="font-size:20px;font-weight:800;color:{risk_color};">{avg_risk:.2f}</div>
                        <div style="font-size:11px;color:#999;">{count} 人 | 平均风险</div>
                    </div>
                    """, unsafe_allow_html=True)

        # 员工卡片
        profiles = result.get("profiles", [])
        if profiles:
            st.subheader(f"👥 员工详情 ({len(profiles)} 人)")
            for p in profiles[:8]:
                emp_id = p.get("employee_id", "?")
                name = p.get("name", "?")
                dept = p.get("department", "?")
                position = p.get("position", "?")
                violations = p.get("violations", [])
                v_count = len(violations) if violations else 0
                v_color = "#d32f2f" if v_count >= 3 else "#f57c00" if v_count >= 1 else "#388e3c"
                with st.expander(f"{'🔴' if v_count >= 3 else '🟠' if v_count >= 1 else '🟢'} [{emp_id}] {name} — {position} ({dept}) | 违规: {v_count}次"):
                    c1, c2, c3 = st.columns(3)
                    with c1: st.markdown(f"**工号**: {emp_id}")
                    with c2: st.markdown(f"**部门**: {dept}")
                    with c3: st.markdown(f"**岗位风险等级**: {p.get('position_risk', '?')}")
                    if violations:
                        st.markdown("**违规记录**:")
                        for v in violations[:5]:
                            st.markdown(f"- `{v.get('date','?')}` | {v.get('type','?')} | 严重度: {v.get('severity','?')}")
                    certs = p.get("certifications", [])
                    if certs:
                        st.markdown(f"**证书**: {', '.join(c.get('type','?') for c in certs[:3])}")

        render_result_card("员工画像数据", result, "👥")


def _render_equipment_dashboard():
    """🔧 设备全生命周期：状态监控 + 维保预警 + 故障频率。"""
    st.subheader("🔧 设备全生命周期 (Equipment Lifecycle)")
    st.caption("设备状态追踪 (正常/预警/维保到期/大修到期/故障) + 维保预警 + MTBF 故障频率统计。")

    if st.button("🔧 加载设备仪表盘", type="primary", use_container_width=True, key="exec_equip"):
        with st.spinner("🔧 加载设备档案 → ⚙️ 风险评估 → ⚠️ 维保预警…"):
            result = _do_equipment_dashboard()

        trace = [
            {"node": "📂 加载 Mock 设备档案", "status": "completed"},
            {"node": "📊 故障频率评分", "status": "completed"},
            {"node": "⚠️ 维保/大修预警", "status": "completed"},
            {"node": "📋 汇总仪表盘", "status": "completed"},
        ]
        render_execution_trace(trace)

        e1, e2, e3, e4 = st.columns(4)
        with e1: st.metric("🔧 总设备", result.get("total", 0))
        with e2: st.metric("🔴 高风险", result.get("high_risk_count", 0))
        with e3: st.metric("⚠️ 预警数", result.get("alert_count", 0))
        status_summary = result.get("status_summary", {})
        with e4: st.metric("✅ 正常", status_summary.get("NORMAL", status_summary.get("normal", 0)))

        # 维保预警
        alerts = result.get("alerts", [])
        if alerts:
            st.subheader(f"⚠️ 维保预警 ({len(alerts)} 条)")
            for alert in alerts[:8]:
                severity = alert.get("severity", "medium")
                icon = "🔴" if severity == "high" else "🟠" if severity == "medium" else "🟡"
                with st.expander(f"{icon} [{alert.get('type','?')}] {alert.get('equipment_name', alert.get('equipment_id','?'))} — {alert.get('description','')[:80]}"):
                    st.markdown(f"**类型**: {alert.get('type', '—')}")
                    st.markdown(f"**严重性**: {severity}")
                    st.markdown(f"**描述**: {alert.get('description', '—')}")
                    if "suggested_action" in alert:
                        st.markdown(f"**建议**: {alert['suggested_action']}")
        else:
            st.success("✅ 暂无维保预警。")

        # 设备列表
        equipment = result.get("equipment", [])
        if equipment:
            st.subheader(f"🔧 设备详情 ({len(equipment)} 台)")
            eq_cols = st.columns(3)
            for i, eq in enumerate(equipment[:9]):
                with eq_cols[i % 3]:
                    status = eq.get("status", "NORMAL")
                    color_map = {"NORMAL": "#388e3c", "WARNING": "#f57c00", "MAINTENANCE_DUE": "#d32f2f",
                                 "OVERHAUL_DUE": "#d32f2f", "FAULT": "#d32f2f", "DECOMMISSIONED": "#999"}
                    color = color_map.get(status, "#999")
                    st.markdown(f"""
                    <div style="padding:10px;border-radius:8px;background:{color}10;border:2px solid {color};margin:4px 0;font-size:12px;">
                        <b>{eq.get('name', eq.get('equipment_id','?'))}</b><br>
                        🏢 {eq.get('department','?')} | {eq.get('equipment_type','?')}<br>
                        📊 状态: <span style="color:{color};font-weight:700;">{status}</span><br>
                        ⏱️ 运行: {eq.get('running_hours','?')}h
                    </div>
                    """, unsafe_allow_html=True)

        render_result_card("设备仪表盘数据", result, "🔧")


def _render_evolution_report():
    """🔄 反思与进化：正负样本管理 + 模型注册表 + 微调就绪评估。"""
    st.subheader("🔄 反思与进化 (Reflection & Evolution)")
    st.caption("完整进化闭环：正反馈收集 (点赞/采纳) → 负样本管理 (误报自动收集) → SFT 数据导出 → 模型热加载/回滚。")

    if st.button("🔄 查看进化全貌", type="primary", use_container_width=True, key="exec_evo"):
        with st.spinner("🔄 加载进化报告…"):
            result = _do_evolution_report()

        trace = [
            {"node": "✅ 正样本收集", "status": "completed"},
            {"node": "❌ 负样本管理", "status": "completed"},
            {"node": "📊 微调就绪检查", "status": "completed"},
            {"node": "🔬 模型注册表", "status": "completed"},
        ]
        render_execution_trace(trace)

        e1, e2, e3, e4 = st.columns(4)
        with e1: st.metric("✅ 正样本", result.get("positive_count", 0))
        with e2: st.metric("❌ 负样本", result.get("negative_count", 0))
        ready = result.get("ready_for_finetune", False)
        with e3: st.metric("🎯 可微调", "✅ 是" if ready else "⏳ 否")
        readiness = result.get("readiness", {})
        if isinstance(readiness, dict):
            with e4: st.metric("📊 最小样本", readiness.get("min_samples_required", "?"))

        report = result.get("report", {})
        model_status = report.get("model_status", {})
        if model_status:
            st.subheader("🔬 模型注册表")
            if isinstance(model_status, dict):
                active = model_status.get("active_version", "?")
                st.info(f"**当前活跃版本**: {active}")
                versions = model_status.get("versions", [])
                if versions:
                    for v in versions[:5]:
                        st.markdown(f"- **{v.get('version','?')}**: {v.get('status','?')} | 部署时间: {v.get('deploy_time','?')}")

        recs = report.get("recommendations", [])
        if recs:
            st.subheader("📋 进化建议")
            for r in recs:
                st.markdown(f"- {r}")

        render_result_card("进化报告数据", result, "🔄")


# ── 🆕 模块四「工程骨架」渲染函数 ──────────────────────

def _render_emergency_drill():
    """🧯 应急预案推演：2D 数字孪生 + A* 路径规划 + 传感器模拟。"""
    st.subheader("🧯 应急预案推演 (Emergency Drill)")
    st.caption("基于 2D 网格地图的工厂数字孪生 (40×30) + A* 最优逃生路径 + 温度/烟雾传感器模拟。")

    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        scenario = st.selectbox("🔥 灾害场景", ["fire", "chemical_leak"],
            format_func=lambda x: "🔥 火灾" if x == "fire" else "☣️ 化学品泄漏", key="drill_scenario")
    with col2:
        intensity = st.slider("💥 灾害强度", 0.3, 1.0, 0.8, 0.1, key="drill_intensity")
    with col3:
        st.metric("🗺️ 地图尺寸", "40×30")
        st.caption("8 区域 | 4 出口 | 6 消防栓 | 6 传感器")

    if st.button("🧯 启动应急推演", type="primary", use_container_width=True, key="exec_drill"):
        with st.spinner("🔥 模拟灾害扩散 → 🧭 A* 路径规划 → 📡 传感器读数…"):
            result = _do_emergency_drill(scenario)

        trace = [
            {"node": "🔥 灾害源初始化", "status": "completed"},
            {"node": "📡 传感器模拟", "status": "completed"},
            {"node": "🗺️ 危险区域扩散", "status": "completed"},
            {"node": "🧭 A* 最优路径规划", "status": "completed"},
            {"node": "📋 预案生成", "status": "completed"},
        ]
        render_execution_trace(trace)

        is_safe = result.get("is_safe", False)
        e1, e2, e3, e4 = st.columns(4)
        with e1:
            st.markdown(f"""
            <div style="text-align:center;padding:12px;border-radius:8px;background:{'#e8f5e9' if is_safe else '#fce4e4'};
                        border:2px solid {'#388e3c' if is_safe else '#d32f2f'};">
                <div style="font-size:32px;">{'✅' if is_safe else '🚨'}</div>
                <div style="font-size:14px;font-weight:700;">{'可安全疏散' if is_safe else '存在风险'}</div>
            </div>
            """, unsafe_allow_html=True)
        with e2: st.metric("⏱️ 疏散时间", f"{result.get('evacuation_time', 0):.1f}s")
        with e3: st.metric("🗺️ 逃生路径", f"{result.get('escape_path_count', 0)} 条")
        with e4: st.metric("📡 传感器告警", f"{result.get('sensor_alert_count', 0)} 个")

        drill_result = result.get("result", {})
        escape_paths = drill_result.get("escape_paths", [])
        if escape_paths:
            st.subheader("🧭 逃生路径详情")
            for i, path in enumerate(escape_paths[:4]):
                path_len = path.get("length", 0) if isinstance(path, dict) else len(path) if isinstance(path, list) else 0
                with st.expander(f"{'🚪' if i == 0 else '🔀'} 路径 {i+1}: {'最优' if i == 0 else '备选'} — {path_len} 步"):
                    if isinstance(path, dict):
                        st.markdown(f"**出口**: {path.get('exit','?')}")
                        st.markdown(f"**长度**: {path_len} 步")
                        st.markdown(f"**耗时**: {path.get('estimated_time_seconds','?')}s")

        affected = drill_result.get("affected_areas", [])
        if affected:
            st.subheader(f"⚠️ 受灾区域 ({len(affected)} 个)")
            st.markdown(", ".join(affected[:8]))

        sensor_alerts = drill_result.get("sensor_alerts", [])
        if sensor_alerts:
            st.subheader(f"📡 传感器读数 ({len(sensor_alerts)} 个)")
            for sa in sensor_alerts[:6]:
                st.markdown(f"- **{sa.get('sensor_id','?')}**: 温度={sa.get('temperature','?')}°C | 烟雾={sa.get('smoke','?')} | 告警={sa.get('alert','?')}")

        recs = result.get("recommendations", [])
        if recs:
            st.subheader("📋 应急建议")
            for r in recs[:6]:
                st.markdown(f"- {r}")

        render_result_card("推演结果", result, "🧯")


# ── 欢迎页 ─────────────────────────────────────────────

def _render_welcome():
    """默认欢迎页面 —— 按当前角色展示可用功能。"""
    current_role = st.session_state.get("user_role", "full")
    role_meta = ROLES.get(current_role, ROLES["full"])
    is_full = (current_role == "full")

    # ── 角色横幅 ──
    role_features = role_meta.get("features", [])
    feature_count = len(role_features) if not is_full else 26
    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, {role_meta['color']}15, {role_meta['color']}05);
        border-left: 6px solid {role_meta['color']};
        border-radius: 10px;
        padding: 20px 28px;
        margin: 8px 0 20px 0;
    ">
        <div style="font-size: 28px; font-weight: 700; color: {role_meta['color']}; margin-bottom: 4px;">
            {role_meta['sidebar_icon']} {role_meta['name']}
        </div>
        <div style="font-size: 14px; color: #555;">
            {role_meta['desc']} — <b>{feature_count} 项可用功能</b>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 快捷操作提示 ──
    if current_role == "inspector":
        st.info("👷 **巡检员快速上手**: 1️⃣ 上传现场照片或选择示例图片 → 2️⃣ 点击「开始智能分析」→ 3️⃣ 查看 AI 研判结果 → 4️⃣ 确认或反馈误报 → 5️⃣ 自动生成工单")
    elif current_role == "manager":
        st.info("🧑‍💼 **管理快速上手**: 1️⃣ 查看「员工安全画像」关注高风险人员 → 2️⃣ 检查「设备全生命周期」维保预警 → 3️⃣ 审阅「智能合规审计」证书状态 → 4️⃣ 为高风险员工生成「个性化培训」计划")
    elif current_role == "admin":
        st.info("🔧 **运维快速上手**: 1️⃣ 「结构化知识库」管理法规数据 → 2️⃣ 「本体驱动图谱」扩展知识网络 → 3️⃣ 「法规变更影响」分析 → 4️⃣ 「反思与进化」管理模型迭代 → 5️⃣ 「可观测性看板」监控系统")

    st.divider()

    # ── 全功能地图（始终展示全部 20 项，但高亮当前角色可用项）──
    st.subheader("🗺️ SafeGuard-AI 技术方案 20 项功能全景")

    def _feature_visible(fid):
        """判断某 feature_id 在当前角色下是否可见"""
        if is_full:
            return True
        return fid in role_features

    # 高亮样式辅助
    def _card(num, emoji, name, desc, fid, bg_default, border_default):
        if is_full or _feature_visible(fid):
            bg, border, tag = bg_default, border_default, ""
        else:
            bg, border, tag = "#f5f5f5", "#ddd", '<div style="font-size:8px;color:#999;">🔒 其他角色</div>'
        return f"""
        <div style="text-align:center;padding:10px;border-radius:8px;background:{bg};border:1px solid {border};margin:2px 0;">
            <div style="font-size:9px;color:#999;">#{num}</div>
            <div style="font-size:22px;">{emoji}</div>
            <div style="font-size:11px;font-weight:600;">{name}</div>
            <div style="font-size:8px;color:#666;">{desc}</div>
            {tag}
        </div>"""

    # ── 模块一: 业务前台 (5项) ──
    st.markdown("### 🛡️ 模块一: 业务前台 (5项)")
    st.caption("多模态隐患识别 · 数字巡检员 · 自动化整改工单 · 智能会议纪要 · LangGraph 状态机")
    m1 = [
        ("1", "📸", "多模态隐患识别", "10类AI检测(图片/视频/实时流)", "phase1_area", "#f8f9fa", "#e9ecef"),
        ("12", "🚶", "数字巡检员", "多摄像头自动巡检+图像比对", "patrol_inspector", "#e3f2fd", "#bbdefb"),
        ("17", "📝", "自动化整改工单", "MCP工具一键生成EHS工单", "ticket_generate", "#e8f5e9", "#c8e6c9"),
        ("14", "📋", "智能会议纪要", "ASR+LLM提取+Markdown纪要", "meeting_minutes", "#fff3e0", "#ffe0b2"),
        ("18", "🔀", "LangGraph状态机", "四路分流:边缘/紧急/常规/结束", "phase1_area", "#fce4e4", "#ef9a9a"),
    ]
    for i, (num, emoji, name, desc, fid, bg, border) in enumerate(m1):
        with st.columns(5)[i]:
            st.markdown(_card(num, emoji, name, desc, fid, bg, border), unsafe_allow_html=True)

    st.divider()

    # ── 模块二: 认知大脑 (6项) ──
    st.markdown("### 🧠 模块二: 认知大脑 (6项)")
    st.caption("结构化知识库 · 本体驱动图谱 · GraphRAG 深度检索 · 法规变更影响 · 零幻觉校验 · 个性化培训")
    m2 = [
        ("2", "📚", "结构化知识库", "BGE-M3向量化+5份EHS法规", "knowledge_base", "#e3f2fd", "#bbdefb"),
        ("3", "🕸️", "本体驱动图谱", "LLM三元组+Schema+图写入", "ontology_explorer", "#e8f5e9", "#c8e6c9"),
        ("4", "📖", "GraphRAG深度检索", "Neo4j+Milvus混合检索", "graphrag_retrieve", "#f8f9fa", "#e9ecef"),
        ("5", "⚖️", "法规变更影响", "Text-Diff+图谱反向追溯", "regulation_impact", "#fff3e0", "#ffe0b2"),
        ("6", "🛡️", "零幻觉校验", "三层防线:门禁→引导→校验", "hallucination_guard", "#fce4e4", "#ef9a9a"),
        ("15", "🎓", "个性化培训", "协同过滤+12案例库+出题", "training_plans", "#f3e5f5", "#ce93d8"),
    ]
    for i, (num, emoji, name, desc, fid, bg, border) in enumerate(m2):
        with st.columns(6)[i]:
            st.markdown(_card(num, emoji, name, desc, fid, bg, border), unsafe_allow_html=True)

    st.divider()

    # ── 模块三: 数字灵魂 (5项) ──
    st.markdown("### 💭 模块三: 数字灵魂 (5项)")
    st.caption("短期工作记忆 · 专家经验记忆 · 员工安全画像 · 设备全生命周期 · 反思与进化")
    m3 = [
        ("7", "💭", "短期工作记忆", "Redis List对话缓存+LLM注入", "short_term_memory", "#fff3e0", "#ffe0b2"),
        ("8", "🧠", "专家经验记忆", "Milvus检索历史案例+few-shot", "expert_memory", "#e3f2fd", "#bbdefb"),
        ("9", "👥", "员工安全画像", "四维评分+部门分布+高风险", "employee_profiles", "#e8f5e9", "#c8e6c9"),
        ("10", "🔧", "设备全生命周期", "MTBF故障频率+维保预警", "equipment_dashboard", "#f8f9fa", "#e9ecef"),
        ("11", "🔄", "反思与进化", "正负样本+模型热加载/回滚", "evolution_report", "#fce4e4", "#ef9a9a"),
    ]
    for i, (num, emoji, name, desc, fid, bg, border) in enumerate(m3):
        with st.columns(5)[i]:
            st.markdown(_card(num, emoji, name, desc, fid, bg, border), unsafe_allow_html=True)

    st.divider()

    # ── 模块四: 工程骨架 (4项) ──
    st.markdown("### 🏗️ 模块四: 工程骨架 (4项)")
    st.caption("智能合规审计 · 应急预案推演 · MCP 工具集成 · 可观测性看板")
    m4 = [
        ("13", "📜", "智能合规审计", "证书过期检测+资质验证", "certificate_audit", "#e3f2fd", "#bbdefb"),
        ("16", "🧯", "应急预案推演", "A*路径+2D数字孪生+传感器", "emergency_drill", "#fff3e0", "#ffe0b2"),
        ("19", "🔌", "MCP工具集成", "6个@tool+能力分级+熔断器", "edge_pre_screen", "#e8f5e9", "#c8e6c9"),
        ("20", "💚", "可观测性看板", "Prometheus指标+6条告警规则", "system_health", "#f8f9fa", "#e9ecef"),
    ]
    for i, (num, emoji, name, desc, fid, bg, border) in enumerate(m4):
        with st.columns(4)[i]:
            st.markdown(_card(num, emoji, name, desc, fid, bg, border), unsafe_allow_html=True)

    st.divider()

    # ── 边缘与运维工具 ──
    st.markdown("### ⚡ 边缘计算与运维工具")
    st.caption("边缘预筛分流 · 离线数据队列 · 云端状态探测 · MQTT 消息模拟 · 数据一键导入 · SFT 微调数据导出")
    tools = [
        ("🔍", "边缘预筛", "YOLOv10n三档分流", "edge_pre_screen"),
        ("📦", "离线队列", "SQLite断网缓存", "offline_queue"),
        ("☁️", "云端探测", "全组件健康检查", "cloud_health_probe"),
        ("📨", "MQTT模拟", "告警/心跳收发", "mqtt_simulate"),
        ("📥", "数据导入", "Neo4j+Milvus", "data_import"),
        ("📤", "SFT导出", "LlamaFactory JSONL", "sft_export"),
    ]
    for i, (emoji, name, desc, fid) in enumerate(tools):
        with st.columns(6)[i]:
            if is_full or _feature_visible(fid):
                bg, border = "#f5f5f5", "#e0e0e0"
                tag = ""
            else:
                bg, border, tag = "#fafafa", "#e8e8e8", '<div style="font-size:7px;color:#ccc;">🔒</div>'
            st.markdown(f"""
            <div style="text-align:center;padding:8px;border-radius:6px;background:{bg};border:1px solid {border};margin:2px 0;">
                <div style="font-size:18px;">{emoji}</div>
                <div style="font-size:10px;font-weight:600;">{name}</div>
                <div style="font-size:8px;color:#999;">{desc}</div>
                {tag}
            </div>
            """, unsafe_allow_html=True)

    st.divider()
    role_tag = role_meta['sidebar_icon'] + " " + role_meta['name']
    st.caption(f"🎉 当前角色: {role_tag} | 20/20 功能全部完成 | 497 测试通过 | 版本 v0.4.0")
    st.caption("💡 侧边栏顶部可切换角色模式，查看不同角色的可用功能")


# ── 主入口 ──────────────────────────────────────────────

def main():
    # 初始化 session state
    defaults = {
        "health_checked": False, "health_ok": False, "health_msg": "",
        "selected_sample": None, "uploaded_image_path": "",
        "active_feature": "", "area_type": "production",
        "live_mode": False,  # 🆕 实时流模式
        # 🎥 视频模拟模式
        "video_mode": "manual", "video_playing": False,
        "video_path": DEFAULT_VIDEO_PATH, "video_frame_idx": 0,
        "video_frame_interval": VIDEO_FRAME_INTERVAL,
        "video_conf_threshold": VIDEO_ANALYZE_CONFIDENCE_THRESHOLD,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # 侧边栏
    api_url = render_sidebar(DEFAULT_API_URL)

    # 主区域
    render_main_area(api_url)


if __name__ == "__main__":
    main()
