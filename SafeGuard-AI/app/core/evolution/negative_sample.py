"""
负样本管理器

实现技术方案功能 11 — 误报图片自动加入 Negative Sample 的后台任务。

功能:
    1. 自动收集: 从 FeedbackLoop 的驳回记录中提取误报图片特征
    2. 负样本库管理: 存储误报案例的图片特征（哈希/向量）
    3. 检索增强: 为视觉识别模型提供"已知误报"防御性检索
    4. 自动清理: 过期负样本自动归档
"""
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 负样本过期天数
NEGATIVE_SAMPLE_EXPIRY_DAYS = 180
# 相同模式检测相似度阈值
PATTERN_SIMILARITY_THRESHOLD = 0.85


@dataclass
class NegativeSampleEntry:
    """
    负样本条目。

    Attributes:
        entry_id: 条目 ID
        image_id: 原始图片 ID
        image_hash: 图片感知哈希值
        false_prediction: AI 的误报结果
        correct_label: 人工修正后的正确标签
        feedback_count: 此模式被反馈的次数
        first_seen: 首次出现时间
        last_seen: 最近出现时间
        status: active / archived
    """

    entry_id: str
    image_id: str = ""
    image_hash: str = ""  # 感知哈希 (aHash/dHash/pHash)
    false_prediction: Dict[str, Any] = field(default_factory=dict)
    correct_label: Dict[str, Any] = field(default_factory=dict)
    feedback_count: int = 1
    first_seen: str = ""
    last_seen: str = ""
    status: str = "active"


class NegativeSampleManager:
    """
    负样本管理器。

    自动收集误报案例并将其纳入防御性检索的知识库。

    使用方式:
        mgr = NegativeSampleManager()
        mgr.add_from_feedback(
            image_id="IMG-001",
            image_hash="0xABCD1234...",
            false_prediction={"type": "oil_leak", "confidence": 0.88},
            correct_label={"type": "water_spill"},
        )
        similar = mgr.find_similar("0xABCD...")
    """

    def __init__(self, storage_dir: Optional[str] = None):
        """
        初始化负样本管理器。

        Args:
            storage_dir: 存储目录
        """
        if storage_dir:
            self._storage_dir = Path(storage_dir)
        else:
            self._storage_dir = (
                Path(__file__).resolve().parent.parent.parent.parent / "data"
            )
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._store_file = self._storage_dir / "negative_samples.json"
        self._negative_samples: Dict[str, NegativeSampleEntry] = {}
        self._load()

    # ---- 负样本添加 ----

    def add_from_feedback(
        self,
        image_id: str,
        image_hash: str,
        false_prediction: Dict[str, Any],
        correct_label: Dict[str, Any],
    ) -> str:
        """
        从用户反馈中添加负样本。

        如果相同模式的负样本已存在，则增加计数而非新增。

        Args:
            image_id: 原始图片 ID
            image_hash: 图片感知哈希
            false_prediction: AI 的误报结果
            correct_label: 人工正确标注

        Returns:
            entry_id
        """
        now = datetime.now().isoformat()

        # 检查是否已存在相同模式
        existing = self._find_by_pattern(false_prediction)
        if existing:
            existing.feedback_count += 1
            existing.last_seen = now
            existing.status = "active"
            self._save()
            logger.info(
                f"[NegativeSample] 更新现有模式: {existing.entry_id} "
                f"(count={existing.feedback_count})"
            )
            return existing.entry_id

        # 新建负样本
        entry_id = f"NEG-{hashlib.md5(image_hash.encode()).hexdigest()[:12]}"
        entry = NegativeSampleEntry(
            entry_id=entry_id,
            image_id=image_id,
            image_hash=image_hash,
            false_prediction=false_prediction,
            correct_label=correct_label,
            feedback_count=1,
            first_seen=now,
            last_seen=now,
            status="active",
        )

        self._negative_samples[entry_id] = entry
        self._save()

        logger.info(
            f"[NegativeSample] 新增负样本: {entry_id} | "
            f"pred={false_prediction.get('type', 'unknown')} → "
            f"correct={correct_label.get('type', 'unknown')}"
        )
        return entry_id

    def add_batch(
        self,
        feedbacks: List[Dict[str, Any]],
    ) -> int:
        """
        批量添加负样本。

        Args:
            feedbacks: 反馈列表 [{image_id, image_hash, false_prediction, correct_label}]

        Returns:
            新增的负样本数
        """
        new_count = 0
        for fb in feedbacks:
            entry_id = self.add_from_feedback(
                image_id=fb["image_id"],
                image_hash=fb.get("image_hash", ""),
                false_prediction=fb.get("false_prediction", {}),
                correct_label=fb.get("correct_label", {}),
            )
            if entry_id.startswith("NEG-"):
                new_count += 1

        logger.info(f"[NegativeSample] 批量添加完成: {new_count} 个新模式")
        return new_count

    # ---- 负样本检索 ----

    def find_similar(
        self,
        image_hash: str,
        max_distance: int = 5,
    ) -> List[NegativeSampleEntry]:
        """
        查找与指定哈希相似的负样本。

        Args:
            image_hash: 查询图片的感知哈希
            max_distance: 最大汉明距离

        Returns:
            相似负样本列表
        """
        if not image_hash:
            return []

        similar = []
        for entry in self._negative_samples.values():
            if entry.status != "active":
                continue
            if not entry.image_hash:
                continue

            # 计算汉明距离
            distance = self._hamming_distance(image_hash, entry.image_hash)
            if distance <= max_distance:
                similar.append(entry)

        # 按距离排序
        similar.sort(key=lambda e: e.feedback_count, reverse=True)
        return similar

    def get_by_prediction_type(self, prediction_type: str) -> List[NegativeSampleEntry]:
        """
        按误报类型检索负样本。

        Args:
            prediction_type: 误报类型 (e.g., 'oil_leak')

        Returns:
            匹配的负样本列表
        """
        return [
            e for e in self._negative_samples.values()
            if e.false_prediction.get("type") == prediction_type
            and e.status == "active"
        ]

    def get_active_samples(self) -> List[NegativeSampleEntry]:
        """获取所有活跃负样本。"""
        return [e for e in self._negative_samples.values() if e.status == "active"]

    # ---- 后台维护 ----

    def cleanup_expired(self) -> int:
        """
        清理过期负样本（自动归档）。

        超过 NEGATIVE_SAMPLE_EXPIRY_DAYS 天未再出现的负样本自动归档。

        Returns:
            归档的数量
        """
        now = datetime.now()
        expiry_threshold = timedelta(days=NEGATIVE_SAMPLE_EXPIRY_DAYS)
        archived = 0

        for entry in list(self._negative_samples.values()):
            if entry.status != "active":
                continue

            try:
                last_seen = datetime.fromisoformat(entry.last_seen)
                if now - last_seen > expiry_threshold:
                    entry.status = "archived"
                    archived += 1
            except (ValueError, TypeError):
                pass

        if archived > 0:
            self._save()
            logger.info(
                f"[NegativeSample] 清理过期: {archived} 条归档 "
                f"(活跃: {len(self.get_active_samples())})"
            )

        return archived

    # ---- 统计 ----

    def stats(self) -> Dict[str, Any]:
        """获取负样本库统计。"""
        active = self.get_active_samples()
        type_counts: Dict[str, int] = {}

        for e in active:
            pred_type = e.false_prediction.get("type", "unknown")
            type_counts[pred_type] = type_counts.get(pred_type, 0) + 1

        return {
            "total_active": len(active),
            "total_archived": len(self._negative_samples) - len(active),
            "by_false_type": type_counts,
            "most_frequent_patterns": sorted(
                [(e.entry_id, e.feedback_count) for e in active],
                key=lambda x: x[1],
                reverse=True,
            )[:5],
        }

    # ---- 内部方法 ----

    def _find_by_pattern(self, prediction: Dict[str, Any]) -> Optional[NegativeSampleEntry]:
        """
        查找与指定误报模式匹配的已有负样本。

        基于误报类型和置信度范围匹配。

        Args:
            prediction: 误报结果

        Returns:
            匹配的 NegativeSampleEntry 或 None
        """
        pred_type = prediction.get("type", "")
        if not pred_type:
            return None

        for entry in self._negative_samples.values():
            if entry.status != "active":
                continue
            if entry.false_prediction.get("type") == pred_type:
                return entry

        return None

    def _hamming_distance(self, hash1: str, hash2: str) -> int:
        """计算两个哈希字符串的汉明距离。"""
        if len(hash1) != len(hash2):
            return max(len(hash1), len(hash2))

        return sum(c1 != c2 for c1, c2 in zip(hash1, hash2))

    # ---- 持久化 ----

    def _save(self):
        """持久化到 JSON。"""
        try:
            data = {}
            for eid, entry in self._negative_samples.items():
                data[eid] = {
                    "entry_id": entry.entry_id,
                    "image_id": entry.image_id,
                    "image_hash": entry.image_hash,
                    "false_prediction": entry.false_prediction,
                    "correct_label": entry.correct_label,
                    "feedback_count": entry.feedback_count,
                    "first_seen": entry.first_seen,
                    "last_seen": entry.last_seen,
                    "status": entry.status,
                }

            with open(self._store_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[NegativeSample] 持久化失败: {e}")

    def _load(self):
        """从 JSON 恢复。"""
        if self._store_file.exists():
            try:
                with open(self._store_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                for eid, d in data.items():
                    self._negative_samples[eid] = NegativeSampleEntry(
                        entry_id=d["entry_id"],
                        image_id=d.get("image_id", ""),
                        image_hash=d.get("image_hash", ""),
                        false_prediction=d.get("false_prediction", {}),
                        correct_label=d.get("correct_label", {}),
                        feedback_count=d.get("feedback_count", 1),
                        first_seen=d.get("first_seen", ""),
                        last_seen=d.get("last_seen", ""),
                        status=d.get("status", "active"),
                    )

                logger.info(
                    f"[NegativeSample] 恢复 {len(self._negative_samples)} 条负样本"
                )
            except Exception as e:
                logger.warning(f"[NegativeSample] 恢复失败: {e}")
