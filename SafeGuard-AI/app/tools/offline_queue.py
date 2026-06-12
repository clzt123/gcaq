"""
Phase 2: 边缘离线队列 — SQLite 本地缓存
==========================================
网络中断时本地持久化待发送消息，恢复连接后自动冲洗至 MQTT 通道。

架构:
    Edge App → OfflineQueue.enqueue() → SQLite (pending)
                    ↓ 网络恢复
            OfflineQueue.flush() → EdgeMQTTClient.publish_alert()

Schema (SQLite):
    CREATE TABLE offline_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        msg_id TEXT UNIQUE,
        timestamp TEXT,
        edge_node_id TEXT,
        msg_type TEXT,
        priority TEXT,
        topic TEXT,
        payload_json TEXT,
        need_cloud INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',   -- pending | sending | sent | failed
        retry_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
"""
import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("safeguard-edge.queue")

# 默认数据库路径
DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_DB_PATH = str(DB_DIR / "edge_offline_queue.db")

# 最大重试次数
MAX_RETRIES = 5
# 单次冲洗批量上限
FLUSH_BATCH_SIZE = 50


# =========================
# OfflineQueue
# =========================

class OfflineQueue:
    """
    边缘离线队列——SQLite 持久化 + 自动冲洗。

    特性:
        - 断网时消息自动入队（status=pending）
        - 恢复连接后调用 flush() 批量推送
        - 失败自动重试（retry_count < MAX_RETRIES）
        - 线程安全（sqlite3 check_same_thread=False + 写锁）

    Usage:
        queue = OfflineQueue(edge_node_id="EDGE-DG-01")
        queue.enqueue(topic="safeguard/EDGE-DG-01/alert", message={...})
        queue.flush(mqtt_client)  # 连接恢复时调用
    """

    def __init__(self, edge_node_id: str = "EDGE-DG-01", db_path: str = DEFAULT_DB_PATH):
        self.edge_id = edge_node_id
        self.db_path = db_path
        self._lock = threading.Lock()

        # 确保目录存在
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # 初始化表结构
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接（每线程独立）。"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """创建队列表（如不存在）。"""
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS offline_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    msg_id TEXT UNIQUE,
                    timestamp TEXT NOT NULL,
                    edge_node_id TEXT NOT NULL,
                    msg_type TEXT NOT NULL DEFAULT 'alert',
                    priority TEXT NOT NULL DEFAULT 'medium',
                    topic TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    need_cloud INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    retry_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            # 索引加速查询
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_queue_status
                ON offline_queue(status, edge_node_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_queue_retry
                ON offline_queue(retry_count, status)
            """)
            conn.commit()
            logger.info(f"[Queue] 数据库已初始化: {self.db_path}")
        finally:
            conn.close()

    # ---- 入队 ----

    def enqueue(
        self,
        topic: str,
        message: Dict[str, Any],
        need_cloud: bool = False,
    ) -> int:
        """
        将消息写入离线队列（持久化）。

        通常在 MQTT publish 失败时调用。

        Args:
            topic: MQTT Topic
            message: 消息体（dict，自动序列化为 JSON）
            need_cloud: 是否需要云端精算

        Returns:
            队列中的 row id
        """
        msg_id = message.get("msg_id", "")
        msg_type = message.get("msg_type", "alert")
        priority = message.get("priority", "medium")
        timestamp = message.get("timestamp", datetime.now().isoformat())

        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    """
                    INSERT OR REPLACE INTO offline_queue
                        (msg_id, timestamp, edge_node_id, msg_type, priority,
                         topic, payload_json, need_cloud, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        msg_id,
                        timestamp,
                        self.edge_id,
                        msg_type,
                        priority,
                        topic,
                        json.dumps(message, ensure_ascii=False),
                        1 if need_cloud else 0,
                    ),
                )
                conn.commit()
                row_id = cursor.lastrowid
                logger.info(f"[Queue] 入队 #{row_id} | msg_id={msg_id} | topic={topic}")
                return row_id
            finally:
                conn.close()

    # ---- 冲洗 ----

    def flush(self, mqtt_client) -> int:
        """
        批量冲洗待发送消息到 MQTT 通道。

        通常在网络恢复或定期定时器触发时调用。

        Args:
            mqtt_client: EdgeMQTTClient 实例（用于实际发送）

        Returns:
            成功发送的消息数
        """
        pending = self._get_pending()
        if not pending:
            return 0

        logger.info(f"[Queue] 冲洗开始: {len(pending)} 条待发送")

        sent_count = 0
        for row in pending[:FLUSH_BATCH_SIZE]:
            msg_id = row["msg_id"]
            topic = row["topic"]
            try:
                payload = json.loads(row["payload_json"])
                message = json.loads(payload) if isinstance(payload, str) else payload
            except (json.JSONDecodeError, TypeError):
                message = {"msg_id": msg_id}

            try:
                # 尝试通过 MQTT 客户端发送
                mqtt_client._publish(topic, message)
                self._mark_sent(msg_id)
                sent_count += 1
            except Exception as e:
                logger.warning(f"[Queue] 冲洗失败 #{row['id']} | msg_id={msg_id}: {e}")
                self._mark_failed(msg_id)

        logger.info(f"[Queue] 冲洗完成: {sent_count}/{len(pending)} 成功")
        return sent_count

    def _get_pending(self) -> List[sqlite3.Row]:
        """获取待发送消息（pending + retry 未超限）。"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT * FROM offline_queue
                WHERE status = 'pending'
                   OR (status = 'failed' AND retry_count < ?)
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (MAX_RETRIES, FLUSH_BATCH_SIZE),
            ).fetchall()
            return rows
        finally:
            conn.close()

    def _mark_sent(self, msg_id: str):
        """标记消息为已发送。"""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE offline_queue SET status='sent', updated_at=datetime('now') WHERE msg_id=?",
                (msg_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def _mark_failed(self, msg_id: str):
        """标记发送失败，递增重试计数。"""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                UPDATE offline_queue
                SET status='failed',
                    retry_count = retry_count + 1,
                    updated_at = datetime('now')
                WHERE msg_id = ?
                """,
                (msg_id,),
            )
            conn.commit()
        finally:
            conn.close()

    # ---- 查询 ----

    def size(self, status: str = "pending") -> int:
        """查询队列中待发送消息数。"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM offline_queue WHERE status=?",
                (status,),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    def stats(self) -> Dict[str, int]:
        """队列统计信息。"""
        conn = self._get_conn()
        try:
            result = {}
            for s in ("pending", "sending", "sent", "failed"):
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM offline_queue WHERE status=?",
                    (s,),
                ).fetchone()
                result[s] = row["cnt"] if row else 0
            result["total"] = sum(result.values())
            return result
        finally:
            conn.close()

    def purge_sent(self, before_days: int = 7) -> int:
        """清理 N 天前已发送的消息。"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                DELETE FROM offline_queue
                WHERE status = 'sent'
                  AND updated_at < datetime('now', ?)
                """,
                (f"-{before_days} days",),
            )
            conn.commit()
            deleted = cursor.rowcount
            if deleted:
                logger.info(f"[Queue] 清理 {deleted} 条过期已发送消息")
            return deleted
        finally:
            conn.close()
