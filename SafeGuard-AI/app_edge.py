"""
SafeGuard-AI Edge — 边缘节点精简入口
======================================
Phase 2 边缘专属 FastAPI 应用。仅加载边缘端能力：
  - LangGraph 状态机 (mock-only, 无 Neo4j/Milvus/DashScope 依赖)
  - MCP 边缘工具 (edge_pre_screen / get_system_health)
  - 边缘健康探测

与云端 main.py 差异:
  ❌ 无 LangSmith 追踪初始化
  ❌ 无 hazard_router (依赖 Neo4j/DashScope 导入链)
  ❌ 无 GraphRAG / Memory / Vision 模块导入
  ✅ 仅边缘工具 + 轻量工作流

启动: uvicorn app_edge:app --host 0.0.0.0 --port 8001
"""
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("safeguard-edge")


# ── 生命周期 ────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🟢 SafeGuard-AI Edge 正在启动...")
    logger.info("   模式: EDGE (边缘节点)")
    logger.info("   能力: edge_pre_screen / get_system_health / MQTT / 离线队列")
    logger.info("   依赖: 全部 Mock (无 Neo4j/Milvus/DashScope)")

    # 初始化 MQTT 客户端
    from app.tools.mqtt_client import EdgeMQTTClient
    edge_id = os.getenv("EDGE_NODE_ID", "EDGE-DG-01")
    app.state.mqtt = EdgeMQTTClient(edge_node_id=edge_id, use_mock=True)
    logger.info(f"   MQTT: Mock 模式 (edge={edge_id})")

    # 初始化离线队列
    from app.tools.offline_queue import OfflineQueue
    app.state.queue = OfflineQueue(edge_node_id=edge_id)
    pending = app.state.queue.size("pending")
    logger.info(f"   离线队列: SQLite (pending={pending})")

    yield

    # 关闭时冲洗队列
    if hasattr(app.state, "queue") and app.state.queue.size("pending") > 0:
        logger.info("🔴 正在冲洗离线队列...")
        try:
            sent = app.state.queue.flush(app.state.mqtt)
            logger.info(f"   冲洗完成: {sent} 条已发送")
        except Exception as e:
            logger.warning(f"   冲洗失败: {e}")
    logger.info("🔴 SafeGuard-AI Edge 正在关闭...")


# ── FastAPI 实例 ────────────────────────────────────
app = FastAPI(
    title="SafeGuard-AI Edge (安卫智脑 - 边缘节点)",
    description="工业安全智能体 — 边缘端轻量服务 (Phase 2)",
    version="0.2.0-edge",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 健康检查 ────────────────────────────────────────
@app.get("/health", tags=["系统"])
async def edge_health():
    """边缘节点健康检查（含 MQTT + 离线队列状态）。"""
    mqtt_ok = False
    queue_stats = {}
    try:
        mqtt_ok = app.state.mqtt.connected if hasattr(app.state, "mqtt") else False
    except Exception:
        pass
    try:
        if hasattr(app.state, "queue"):
            queue_stats = app.state.queue.stats()
    except Exception:
        pass

    return {
        "status": "healthy",
        "app": "SafeGuard-AI-Edge",
        "version": "0.2.0-edge",
        "mode": "edge",
        "capabilities": [
            "edge_pre_screen", "get_system_health",
            "mqtt_publish", "offline_queue", "local_ticket",
        ],
        "mqtt_connected": mqtt_ok,
        "offline_queue": queue_stats,
        "timestamp": datetime.now().isoformat(),
    }


# ── 边缘路由 ────────────────────────────────────────
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

edge_router = APIRouter(prefix="/api/v1/edge", tags=["边缘节点"])


class CloudHealthResponse(BaseModel):
    """云端健康探测响应"""
    overall_status: str = ""
    load_level: str = ""
    active_llm_requests: int = 0
    estimated_latency_ms: int = 0
    timestamp: str = ""
    message: str = ""


@edge_router.get("/health/cloud", response_model=dict)
async def probe_cloud_health():
    """
    探测云端系统健康状态。

    边缘节点在发起云端精算前调用此接口确认云端可用。
    调用 MCP 工具 get_system_health 获取云端各组件的健康状态。
    """
    try:
        from app.tools.mcp_tools import get_system_health

        result = await get_system_health.ainvoke({
            "edge_node_id": f"EDGE-{datetime.now().strftime('%H%M%S')}",
            "include_details": True,
        })

        return result

    except Exception as e:
        logger.error(f"[Edge] 云端健康探测失败: {e}")
        return {
            "overall_status": "unreachable",
            "load_level": "unknown",
            "message": f"无法连接云端: {e}",
            "timestamp": datetime.now().isoformat(),
        }


class EdgePreScreenRequest(BaseModel):
    """边缘预筛请求"""
    image_chunk: str = Field("", description="Base64 图像数据（空则返回 Mock）")
    model_type: str = Field("yolov10n", description="边缘模型类型")
    confidence_threshold_high: float = Field(0.90, ge=0.0, le=1.0)
    confidence_threshold_low: float = Field(0.70, ge=0.0, le=1.0)


@edge_router.post("/pre-screen", response_model=dict)
async def run_edge_pre_screen(request: EdgePreScreenRequest):
    """
    执行边缘端快速预筛推理。

    返回分流决策: edge_resolved(边缘处置) / pending_cloud(上升云端) / ignored(忽略)。
    """
    try:
        from app.tools.mcp_tools import edge_pre_screen

        image_chunk = request.image_chunk if request.image_chunk else None
        result = await edge_pre_screen.ainvoke({
            "image_chunk": image_chunk,
            "model_type": request.model_type,
            "confidence_threshold_high": request.confidence_threshold_high,
            "confidence_threshold_low": request.confidence_threshold_low,
        })

        return result

    except Exception as e:
        logger.error(f"[Edge] 预筛失败: {e}")
        raise HTTPException(status_code=500, detail=f"边缘预筛失败: {e}")


class EdgeAnalyzeRequest(BaseModel):
    """边缘分析请求（轻量版，仅需图片路径）"""
    image_path: str = Field("", description="图片本地路径")
    edge_node_id: str = Field("", description="边缘节点 ID")
    area_type: str = Field("production", description="区域类型")


@edge_router.post("/analyze", response_model=dict)
async def edge_analyze(request: EdgeAnalyzeRequest):
    """
    边缘端隐患分析（高置信度场景）。

    调用 supervisor 四路分流，max_confidence >= 0.90 时走 edge_handler 边缘即时处置。
    置信度不足时标记 need_cloud_analysis=True，交由调用方决定是否上传。
    """
    try:
        # 仅导入边缘可用的模块（不含 Neo4j/Milvus/DashScope 导入链）
        from app.core.graph.state import HazardState
        from app.core.graph.nodes import (
            detection_node,
            supervisor_node,
            edge_handler_node,
        )

        # 构建初始状态
        initial: HazardState = {
            "messages": [],
            "current_image": request.image_path,
            "detection_result": {},
            "ticket_data": {},
            "graph_context": "",
            "memory_context": "",
            "next_action": "",
            "ticket_status": "",
            "retry_count": 0,
            "edge_node_id": request.edge_node_id,
            "area_type": request.area_type,
            "need_cloud_analysis": False,
        }

        # Step 1: 视觉检测 (Mock 关键词匹配)
        det_result = await detection_node(initial)
        state = {**initial, **det_result}

        # Step 2: Supervisor 四路分流
        sup_result = await supervisor_node(state)
        state = {**state, **sup_result}

        # Step 3: 根据分流结果执行
        if state.get("next_action") == "edge_handler":
            edge_result = await edge_handler_node(state)
            state = {**state, **edge_result}
        elif state.get("next_action") in ("urgent_handler", "normal_handler"):
            # 边缘端无法执行云端全链路 → 标记需上传
            state["need_cloud_analysis"] = True
            state["messages"].append({
                "role": "system",
                "content": (
                    f"[Edge] 置信度不足，需上传云端执行 "
                    f"{state.get('next_action')}。"
                ),
            })

        # 提取响应字段
        detection = state.get("detection_result", {})
        dispatch_mode = "edge" if state.get("next_action") == "edge_handler" else "pending_cloud"
        result = {
            "alert_id": f"EDGE-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "risk_level": detection.get("risk_level", "none"),
            "next_action": state.get("next_action", "end"),
            "need_cloud_analysis": state.get("need_cloud_analysis", False),
            "ticket_status": state.get("ticket_status", ""),
            "ticket_data": state.get("ticket_data", {}),
            "graph_context": state.get("graph_context", ""),
            "messages": state.get("messages", []),
            "dispatch_mode": dispatch_mode,
        }

        # ---- Phase 2: MQTT 上报告警 ----
        try:
            mqtt = app.state.mqtt
            queue = app.state.queue

            if mqtt.connected:
                # 在线 → 直接 MQTT 发布
                msg_id = await mqtt.publish_alert(
                    ticket_data=state.get("ticket_data", {}),
                    detection_result=detection,
                    need_cloud=state.get("need_cloud_analysis", False),
                )
                result["mqtt_msg_id"] = msg_id
                result["mqtt_status"] = "published"
            else:
                # 离线 → 入队等待
                from app.tools.mqtt_client import build_message, TOPIC_ALERT
                msg = build_message(
                    edge_node_id=request.edge_node_id or "EDGE-DG-01",
                    msg_type="alert",
                    payload={"ticket": state.get("ticket_data", {}), "result": result},
                    need_cloud=state.get("need_cloud_analysis", False),
                )
                topic = TOPIC_ALERT.format(edge_id=request.edge_node_id or "EDGE-DG-01")
                queue.enqueue(topic, msg, need_cloud=state.get("need_cloud_analysis", False))
                result["mqtt_status"] = "queued"
                result["queue_size"] = queue.size("pending")
        except Exception as mqtt_err:
            logger.warning(f"[Edge] MQTT 发布失败，入离线队列: {mqtt_err}")
            try:
                from app.tools.mqtt_client import build_message, TOPIC_ALERT
                queue = app.state.queue
                msg = build_message(
                    edge_node_id=request.edge_node_id or "EDGE-DG-01",
                    msg_type="alert",
                    payload={"ticket": state.get("ticket_data", {}), "result": result},
                    need_cloud=state.get("need_cloud_analysis", False),
                )
                topic = TOPIC_ALERT.format(edge_id=request.edge_node_id or "EDGE-DG-01")
                queue.enqueue(topic, msg, need_cloud=state.get("need_cloud_analysis", False))
                result["mqtt_status"] = "queued_fallback"
            except Exception as q_err:
                logger.error(f"[Edge] 离线队列也失败: {q_err}")
                result["mqtt_status"] = "failed"

        return result

    except Exception as e:
        logger.error(f"[Edge] 分析失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"边缘分析失败: {e}")


# ── Phase 2: MQTT + 离线队列端点 ─────────────────
@edge_router.post("/mqtt/heartbeat", response_model=dict)
async def send_heartbeat():
    """
    发送边缘节点心跳到云端。

    Topic: safeguard/{edge_id}/heartbeat
    """
    mqtt = app.state.mqtt
    msg_id = await mqtt.publish_heartbeat(status="healthy")
    return {
        "msg_id": msg_id,
        "mqtt_connected": mqtt.connected,
        "timestamp": datetime.now().isoformat(),
    }


@edge_router.get("/queue/stats", response_model=dict)
async def get_queue_stats():
    """查询离线队列统计信息。"""
    queue = app.state.queue
    return {
        "stats": queue.stats(),
        "db_path": queue.db_path,
        "timestamp": datetime.now().isoformat(),
    }


@edge_router.post("/queue/flush", response_model=dict)
async def flush_offline_queue():
    """
    手动冲洗离线队列 — 将所有待发送消息推送至 MQTT 通道。

    通常在网络恢复后由自动化脚本或管理员手动触发。
    """
    queue = app.state.queue
    pending_before = queue.size("pending")
    sent = queue.flush(app.state.mqtt)
    pending_after = queue.size("pending")
    return {
        "sent": sent,
        "pending_before": pending_before,
        "pending_after": pending_after,
        "timestamp": datetime.now().isoformat(),
    }


@edge_router.post("/queue/purge", response_model=dict)
async def purge_queue(days: int = 7):
    """清理 N 天前的已发送消息。"""
    queue = app.state.queue
    deleted = queue.purge_sent(before_days=days)
    return {
        "deleted": deleted,
        "before_days": days,
        "timestamp": datetime.now().isoformat(),
    }


app.include_router(edge_router)


# ── 启动入口 ────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [EDGE] %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    uvicorn.run(app, host="0.0.0.0", port=8001)
