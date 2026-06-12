"""
Phase 2: MQTT 边缘-云端通信客户端
===================================
定义边缘节点与云端之间的 MQTT 消息协议。
支持 Mock 模式（本地文件模拟），开发阶段无需真实 MQTT Broker。

Topic 规范:
    safeguard/{edge_id}/alert      — 边缘→云端：上报告警/工单
    safeguard/{edge_id}/heartbeat  — 边缘→云端：定期心跳
    safeguard/{edge_id}/feedback   — 云端→边缘：工单回执/模型更新通知

消息 Schema (JSON):
    {
        "msg_id": "uuid",
        "timestamp": "ISO8601",
        "edge_node_id": "EDGE-DG-01",
        "msg_type": "alert | heartbeat | feedback_ack",
        "priority": "high | medium | low",
        "payload": { ... },
        "need_cloud_analysis": true/false
    }
"""
import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("safeguard-edge.mqtt")

# =========================
# Topic 常量
# =========================

TOPIC_ALERT = "safeguard/{edge_id}/alert"
TOPIC_HEARTBEAT = "safeguard/{edge_id}/heartbeat"
TOPIC_FEEDBACK = "safeguard/{edge_id}/feedback"

# 默认 Mock 消息存储目录
MOCK_MQTT_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "mqtt_mock"


# =========================
# 消息 Schema 构建
# =========================

def build_message(
    edge_node_id: str,
    msg_type: str,
    payload: Dict[str, Any],
    priority: str = "medium",
    need_cloud: bool = False,
) -> Dict[str, Any]:
    """
    构建标准 MQTT 消息体。

    Args:
        edge_node_id: 边缘节点 ID
        msg_type: 消息类型 (alert / heartbeat / feedback_ack)
        payload: 消息负载
        priority: 优先级
        need_cloud: 是否需要云端精算

    Returns:
        标准化的消息字典
    """
    return {
        "msg_id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().isoformat(),
        "edge_node_id": edge_node_id,
        "msg_type": msg_type,
        "priority": priority,
        "payload": payload,
        "need_cloud_analysis": need_cloud,
    }


# =========================
# Mock 模式 — 本地文件模拟
# =========================

class _MockMQTTBackend:
    """本地文件模拟 MQTT 收发——开发阶段无需真实 Broker。"""

    def __init__(self, edge_id: str):
        self.edge_id = edge_id
        self.outbox: list[Dict[str, Any]] = []
        self.inbox: list[Dict[str, Any]] = []
        MOCK_MQTT_DIR.mkdir(parents=True, exist_ok=True)

    def publish(self, topic: str, message: Dict[str, Any]) -> bool:
        """模拟发布消息到指定 topic。"""
        self.outbox.append({
            "topic": topic.format(edge_id=self.edge_id),
            "message": message,
            "published_at": datetime.now().isoformat(),
        })
        # 持久化到文件
        self._persist()
        logger.info(f"[MQTT Mock] 发布 → {topic.format(edge_id=self.edge_id)} | msg_id={message.get('msg_id')}")
        return True

    def _persist(self):
        """将 outbox 持久化到本地文件。"""
        outbox_file = MOCK_MQTT_DIR / f"outbox_{self.edge_id}.json"
        try:
            with open(outbox_file, "w", encoding="utf-8") as f:
                json.dump(self.outbox[-100:], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[MQTT Mock] 持久化失败: {e}")


# =========================
# EdgeMQTTClient — 统一接口
# =========================

class EdgeMQTTClient:
    """
    边缘 MQTT 客户端——统一的边缘-云端消息通道。

    自动检测模式:
        - use_mock=True (默认) → 本地文件模拟 (开发阶段)
        - use_mock=False → 连接真实 MQTT Broker (生产阶段，需 paho-mqtt)

    Usage:
        mqtt = EdgeMQTTClient(edge_node_id="EDGE-DG-01")
        await mqtt.publish_alert(ticket_data, need_cloud=False)
        await mqtt.publish_heartbeat()
    """

    def __init__(
        self,
        edge_node_id: str = "EDGE-DG-01",
        use_mock: bool = True,
        broker_host: str = "localhost",
        broker_port: int = 1883,
    ):
        self.edge_id = edge_node_id
        self.use_mock = use_mock
        self.broker_host = broker_host
        self.broker_port = broker_port
        self._backend: Optional[_MockMQTTBackend] = None
        self._connected = False

        if use_mock:
            self._backend = _MockMQTTBackend(edge_id=edge_node_id)
            self._connected = True
            logger.info(f"[MQTT] Mock 模式已启用 (edge={edge_node_id})")
        else:
            # 真实模式：延迟连接 paho-mqtt（首次 publish 时）
            logger.info(f"[MQTT] 真实模式: {broker_host}:{broker_port} (首次 publish 时连接)")

    @property
    def connected(self) -> bool:
        return self._connected

    # ---- 发布接口 ----

    async def publish_alert(
        self,
        ticket_data: Dict[str, Any],
        detection_result: Optional[Dict[str, Any]] = None,
        need_cloud: bool = False,
    ) -> str:
        """
        发布告警/工单到云端。

        对应 Topic: safeguard/{edge_id}/alert

        Args:
            ticket_data: 工单数据
            detection_result: 检测结果（可选）
            need_cloud: 是否需要云端精算

        Returns:
            msg_id
        """
        payload = {"ticket": ticket_data}
        if detection_result:
            payload["detection"] = {
                "risk_level": detection_result.get("risk_level"),
                "findings_count": len(detection_result.get("findings", [])),
            }

        msg = build_message(
            edge_node_id=self.edge_id,
            msg_type="alert",
            payload=payload,
            priority=ticket_data.get("priority", 3) <= 2 and "high" or "medium",
            need_cloud=need_cloud,
        )

        topic = TOPIC_ALERT.format(edge_id=self.edge_id)
        self._publish(topic, msg)
        return msg["msg_id"]

    async def publish_heartbeat(self, status: str = "healthy") -> str:
        """
        发布边缘节点心跳。

        对应 Topic: safeguard/{edge_id}/heartbeat

        Args:
            status: 边缘节点状态 (healthy / degraded / offline)

        Returns:
            msg_id
        """
        msg = build_message(
            edge_node_id=self.edge_id,
            msg_type="heartbeat",
            payload={
                "status": status,
                "uptime_seconds": time.time() - getattr(self, "_start_time", time.time()),
            },
            priority="low",
        )

        topic = TOPIC_HEARTBEAT.format(edge_id=self.edge_id)
        self._publish(topic, msg)
        return msg["msg_id"]

    async def subscribe_feedback(self) -> list[Dict[str, Any]]:
        """
        拉取云端下发的反馈消息（工单回执/模型更新通知）。

        对应 Topic: safeguard/{edge_id}/feedback

        Returns:
            反馈消息列表（Mock 模式下返回空，真实模式下从 Broker 拉取）
        """
        if self.use_mock:
            # Mock: 云端无反馈
            return []
        # TODO: 真实 paho-mqtt 订阅实现
        return []

    # ---- 内部 ----

    def _publish(self, topic: str, message: Dict[str, Any]):
        if self.use_mock and self._backend:
            self._backend.publish(topic, message)
        else:
            # TODO: paho-mqtt client.publish(topic, json.dumps(message), qos=1)
            logger.info(f"[MQTT] (真实模式-待实现) 发布 → {topic}")
