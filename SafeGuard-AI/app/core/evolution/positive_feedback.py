"""
正反馈收集器

实现技术方案功能 11 — "点赞/采纳→存入正样本"的用户反馈闭环。

工作流:
    1. 用户对 AI 建议点赞/采纳
    2. 系统记录正反馈（包含原始输入、AI输出、采纳结果）
    3. 正反馈存入正样本库（用于后续 SFT 训练和 Few-shot 示例）
    4. 正反馈统计与趋势分析
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils import get_mock_path

logger = logging.getLogger(__name__)

# 正反馈类型
POSITIVE_FEEDBACK_TYPES = ["approved", "adopted", "liked", "useful"]


@dataclass
class PositiveSample:
    """
    正样本记录。

    Attributes:
        sample_id: 样本唯一标识
        feedback_type: 反馈类型 (approved/adopted/liked/useful)
        user_id: 操作者ID
        input_context: 输入上下文（图片/文本/告警ID）
        ai_response: AI 原始响应
        user_comment: 用户评价
        recorded_at: 记录时间
        usage_count: 作为 Few-shot 示例被使用的次数
    """

    sample_id: str
    feedback_type: str  # approved / adopted / liked / useful
    user_id: str = ""
    input_context: Dict[str, Any] = field(default_factory=dict)
    ai_response: Dict[str, Any] = field(default_factory=dict)
    user_comment: str = ""
    recorded_at: str = ""
    usage_count: int = 0


class PositiveFeedbackCollector:
    """
    正反馈收集器。

    功能:
        1. 记录用户点赞/采纳行为
        2. 正样本持久化存储
        3. 正样本检索（用于 Few-shot 和 SFT 数据导出）
        4. 正反馈统计

    使用方式:
        coll = PositiveFeedbackCollector()
        coll.record_positive(
            feedback_type="adopted",
            user_id="EMP_001",
            input_context={"image_id": "IMG-001"},
            ai_response={"type": "oil_leak", "action": "create_ticket"},
        )
        samples = coll.get_positive_samples(limit=10)
    """

    def __init__(self, storage_dir: Optional[str] = None):
        """
        初始化正反馈收集器。

        Args:
            storage_dir: 存储目录，None 时使用默认 data/ 目录
        """
        if storage_dir:
            self._storage_dir = Path(storage_dir)
        else:
            self._storage_dir = (
                Path(__file__).resolve().parent.parent.parent.parent / "data"
            )
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._samples_file = self._storage_dir / "positive_samples.json"
        self._samples: List[PositiveSample] = []
        self._load()

    # ---- 反馈记录 ----

    def record_positive(
        self,
        feedback_type: str,
        user_id: str,
        input_context: Dict[str, Any],
        ai_response: Dict[str, Any],
        user_comment: str = "",
    ) -> str:
        """
        记录一条正反馈。

        Args:
            feedback_type: 反馈类型 (approved/adopted/liked/useful)
            user_id: 操作者ID
            input_context: 输入上下文
            ai_response: AI 响应
            user_comment: 评价

        Returns:
            sample_id

        Raises:
            ValueError: 无效的反馈类型
        """
        if feedback_type not in POSITIVE_FEEDBACK_TYPES:
            raise ValueError(
                f"无效的正反馈类型: '{feedback_type}'。"
                f"可选: {POSITIVE_FEEDBACK_TYPES}"
            )

        sample_id = f"POS-{datetime.now().strftime('%Y%m%d%H%M%S')}-{len(self._samples):04d}"

        sample = PositiveSample(
            sample_id=sample_id,
            feedback_type=feedback_type,
            user_id=user_id,
            input_context=input_context,
            ai_response=ai_response,
            user_comment=user_comment,
            recorded_at=datetime.now().isoformat(),
        )

        self._samples.append(sample)
        self._save()

        logger.info(
            f"[PositiveFeedback] 记录正反馈: {sample_id} | "
            f"type={feedback_type} | user={user_id} | "
            f"total={len(self._samples)}"
        )
        return sample_id

    def record_batch(
        self,
        feedbacks: List[Dict[str, Any]],
    ) -> List[str]:
        """
        批量记录正反馈。

        Args:
            feedbacks: 反馈列表 [{feedback_type, user_id, input_context, ai_response, user_comment}]

        Returns:
            sample_id 列表
        """
        ids = []
        for fb in feedbacks:
            sid = self.record_positive(
                feedback_type=fb["feedback_type"],
                user_id=fb.get("user_id", ""),
                input_context=fb.get("input_context", {}),
                ai_response=fb.get("ai_response", {}),
                user_comment=fb.get("user_comment", ""),
            )
            ids.append(sid)
        return ids

    # ---- 样本检索 ----

    def get_positive_samples(
        self,
        feedback_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[PositiveSample]:
        """
        检索正样本。

        Args:
            feedback_type: 按类型过滤（None=全部）
            limit: 返回数量上限

        Returns:
            PositiveSample 列表（按时间倒序）
        """
        samples = self._samples
        if feedback_type:
            samples = [s for s in samples if s.feedback_type == feedback_type]

        # 按时间倒序
        sorted_samples = sorted(
            samples,
            key=lambda s: s.recorded_at,
            reverse=True,
        )
        return sorted_samples[:limit]

    def get_samples_as_fewshot(
        self,
        limit: int = 3,
        feedback_type: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """
        导出正样本为 Few-shot 格式。

        Args:
            limit: 数量
            feedback_type: 类型过滤

        Returns:
            Few-shot 示例列表 [{input, output}]
        """
        samples = self.get_positive_samples(feedback_type, limit)
        fewshot = []
        for s in samples:
            fewshot.append({
                "input": json.dumps(s.input_context, ensure_ascii=False),
                "output": json.dumps(s.ai_response, ensure_ascii=False),
                "sample_id": s.sample_id,
                "quality": s.feedback_type,
            })
            s.usage_count += 1
        return fewshot

    # ---- 数据导出 ----

    def export_sft_data(self, output_path: Optional[str] = None) -> str:
        """
        导出正反馈为 SFT 训练数据 (JSONL 格式)。

        Args:
            output_path: 输出路径（None 时自动生成）

        Returns:
            输出文件路径
        """
        if not output_path:
            output_path = str(
                self._storage_dir / f"sft_positive_{datetime.now().strftime('%Y%m%d')}.jsonl"
            )

        count = 0
        with open(output_path, "w", encoding="utf-8") as f:
            for sample in self._samples:
                record = {
                    "messages": [
                        {"role": "user", "content": json.dumps(sample.input_context, ensure_ascii=False)},
                        {"role": "assistant", "content": json.dumps(sample.ai_response, ensure_ascii=False)},
                    ],
                    "metadata": {
                        "sample_id": sample.sample_id,
                        "feedback_type": sample.feedback_type,
                        "quality": "positive",
                    },
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1

        logger.info(
            f"[PositiveFeedback] 导出 SFT 数据: {count} 条 → {output_path}"
        )
        return output_path

    # ---- 统计 ----

    def stats(self) -> Dict[str, Any]:
        """获取正反馈统计。"""
        type_counts: Dict[str, int] = {}
        user_counts: Dict[str, int] = {}
        monthly_counts: Dict[str, int] = {}

        for s in self._samples:
            type_counts[s.feedback_type] = type_counts.get(s.feedback_type, 0) + 1
            if s.user_id:
                user_counts[s.user_id] = user_counts.get(s.user_id, 0) + 1
            if s.recorded_at:
                month_key = s.recorded_at[:7]  # YYYY-MM
                monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1

        return {
            "total_samples": len(self._samples),
            "by_type": type_counts,
            "top_users": sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:5],
            "monthly_trend": monthly_counts,
            "is_ready_for_sft": len(self._samples) >= 20,
        }

    # ---- 持久化 ----

    def _save(self):
        """持久化正样本到 JSON。"""
        try:
            data = []
            for s in self._samples:
                data.append({
                    "sample_id": s.sample_id,
                    "feedback_type": s.feedback_type,
                    "user_id": s.user_id,
                    "input_context": s.input_context,
                    "ai_response": s.ai_response,
                    "user_comment": s.user_comment,
                    "recorded_at": s.recorded_at,
                    "usage_count": s.usage_count,
                })

            with open(self._samples_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[PositiveFeedback] 持久化失败: {e}")

    def _load(self):
        """从 JSON 恢复正样本。"""
        if self._samples_file.exists():
            try:
                with open(self._samples_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                for d in data:
                    self._samples.append(PositiveSample(
                        sample_id=d["sample_id"],
                        feedback_type=d["feedback_type"],
                        user_id=d.get("user_id", ""),
                        input_context=d.get("input_context", {}),
                        ai_response=d.get("ai_response", {}),
                        user_comment=d.get("user_comment", ""),
                        recorded_at=d.get("recorded_at", ""),
                        usage_count=d.get("usage_count", 0),
                    ))

                logger.info(
                    f"[PositiveFeedback] 恢复 {len(self._samples)} 条正样本"
                )
            except Exception as e:
                logger.warning(f"[PositiveFeedback] 恢复失败: {e}")
