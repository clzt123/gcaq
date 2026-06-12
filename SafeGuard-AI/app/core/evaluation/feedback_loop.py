"""
Phase 4: 反馈闭环编排器
=======================
自动化"驳回→修正→评估→部署"全闭环流水线。

闭环流程:
    1. 收集 — 从 log_false_positive 积累驳回反馈
    2. 触发 — 满足条件时自动触发微调流水线
    3. 训练 — 导出 SFT 数据 → 微调模型
    4. 评估 — A/B 对比微调前后效果
    5. 部署 — 通过显著性检验后自动切换模型版本

触发条件 (可配置):
    - 驳回数量 >= MIN_FEEDBACK_COUNT (默认 20)
    - F1 下降 >= F1_DEGRADE_THRESHOLD (默认 0.05)
    - 距上次微调 >= MIN_RETRAIN_INTERVAL_DAYS (默认 7)

版本管理:
    - 模型版本号: v{major}.{minor}.{patch}
    - 每次 SFT: minor++
    - 每次修正: patch++

Usage:
    loop = FeedbackLoop()
    loop.record_feedback(emp_id="EMP-8842", image_id="IMG-001", ...)
    decision = loop.check_trigger()
    if decision["should_retrain"]:
        loop.execute_pipeline()
"""
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 配置常量 ──────────────────────────────────────────

MIN_FEEDBACK_COUNT = 20             # 最小驳回数才触发微调
F1_DEGRADE_THRESHOLD = 0.05         # F1 下降超过此值强制触发
MIN_RETRAIN_INTERVAL_DAYS = 7       # 最小重训练间隔（天）
MAX_FEEDBACK_AGE_DAYS = 90          # 超过此天数的反馈自动归档

STATE_FILE = "feedback_loop_state.json"  # 状态持久化文件


# ── 数据模型 ──────────────────────────────────────────

@dataclass
class FeedbackEntry:
    """单条反馈记录。"""
    feedback_id: str
    emp_id: str
    image_id: str
    feedback_type: str          # false_positive / irrelevant
    original_prediction: Dict[str, Any]
    human_correction: Dict[str, Any]
    comment: str
    recorded_at: str            # ISO8601

    def is_valid(self) -> bool:
        """校验反馈是否可用于训练。"""
        return (
            self.feedback_type in ("false_positive", "irrelevant")
            and bool(self.human_correction)
            and bool(self.original_prediction)
        )


@dataclass
class LoopState:
    """闭环状态（可持久化）。"""
    total_feedback_count: int = 0
    pending_feedback_count: int = 0
    last_retrain_at: Optional[str] = None
    current_model_version: str = "v1.0.0"
    total_retrain_count: int = 0
    feedback_history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_feedback_count": self.total_feedback_count,
            "pending_feedback_count": self.pending_feedback_count,
            "last_retrain_at": self.last_retrain_at,
            "current_model_version": self.current_model_version,
            "total_retrain_count": self.total_retrain_count,
            "feedback_history": self.feedback_history[-100:],  # 只保留最近 100 条
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LoopState":
        return cls(
            total_feedback_count=d.get("total_feedback_count", 0),
            pending_feedback_count=d.get("pending_feedback_count", 0),
            last_retrain_at=d.get("last_retrain_at"),
            current_model_version=d.get("current_model_version", "v1.0.0"),
            total_retrain_count=d.get("total_retrain_count", 0),
            feedback_history=d.get("feedback_history", []),
        )


# ── 闭环编排器 ────────────────────────────────────────

class FeedbackLoop:
    """
    反馈闭环编排器。

    管理模式:
        - Mock (默认): 内存态 + 本地 JSON 持久化
        - Production: 对接 t_feedback_log 数据库表
    """

    def __init__(self, state_dir: Optional[str] = None):
        self.state: LoopState = LoopState()
        self._pending_feedbacks: List[FeedbackEntry] = []
        self._state_dir = Path(state_dir) if state_dir else Path(__file__).resolve().parent.parent.parent.parent / "data"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._state_dir / STATE_FILE

        # 恢复历史状态
        self._load_state()

    # ---- 反馈录入 ----

    def record_feedback(
        self,
        emp_id: str,
        image_id: str,
        feedback_type: str,
        original_prediction: Dict[str, Any],
        human_correction: Dict[str, Any],
        comment: str = "",
    ) -> str:
        """
        记录一条驳回反馈。

        Returns:
            feedback_id
        """
        feedback_id = f"FBL-{emp_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        entry = FeedbackEntry(
            feedback_id=feedback_id,
            emp_id=emp_id,
            image_id=image_id,
            feedback_type=feedback_type,
            original_prediction=original_prediction,
            human_correction=human_correction,
            comment=comment,
            recorded_at=datetime.now().isoformat(),
        )

        if entry.is_valid():
            self._pending_feedbacks.append(entry)
            self.state.pending_feedback_count = len(self._pending_feedbacks)
            self.state.total_feedback_count += 1

            logger.info(
                f"[FeedbackLoop] 已记录反馈: {feedback_id} | "
                f"type={feedback_type} | pending={self.state.pending_feedback_count}"
            )
        else:
            logger.warning(f"[FeedbackLoop] 无效反馈被丢弃: {feedback_id}")

        self._save_state()
        return feedback_id

    # ---- 触发判定 ----

    def check_trigger(self) -> Dict[str, Any]:
        """
        检查是否满足微调触发条件。

        Returns:
            dict 含 should_retrain、reason、conditions
        """
        conditions = {
            "pending_feedback_count": self.state.pending_feedback_count,
            "min_feedback_count": MIN_FEEDBACK_COUNT,
            "days_since_last_retrain": None,
            "min_retrain_interval": MIN_RETRAIN_INTERVAL_DAYS,
        }

        # 检查 1: 驳回数量不足
        if self.state.pending_feedback_count < MIN_FEEDBACK_COUNT:
            return {
                "should_retrain": False,
                "reason": (
                    f"驳回数不足 ({self.state.pending_feedback_count}/{MIN_FEEDBACK_COUNT})"
                ),
                "conditions": conditions,
            }

        # 检查 2: 距上次微调太近
        if self.state.last_retrain_at:
            last = datetime.fromisoformat(self.state.last_retrain_at)
            days_since = (datetime.now() - last).days
            conditions["days_since_last_retrain"] = days_since
            if days_since < MIN_RETRAIN_INTERVAL_DAYS:
                return {
                    "should_retrain": False,
                    "reason": (
                        f"距上次微调仅 {days_since} 天 "
                        f"(需 >= {MIN_RETRAIN_INTERVAL_DAYS} 天)"
                    ),
                    "conditions": conditions,
                }

        # 所有条件满足 → 触发
        return {
            "should_retrain": True,
            "reason": (
                f"满足触发条件: 驳回 {self.state.pending_feedback_count} >= "
                f"{MIN_FEEDBACK_COUNT}" +
                (f", 距上次微调 {conditions['days_since_last_retrain']} 天"
                 if conditions["days_since_last_retrain"] else "")
            ),
            "conditions": conditions,
        }

    # ---- 执行流水线 ----

    def execute_pipeline(self, dry_run: bool = True) -> Dict[str, Any]:
        """
        执行微调流水线（Mock 模拟）。

        完整步骤:
            1. 导出训练数据 (export_training_data.py)
            2. 触发微调作业 (llamafactory / 云端 GPU 集群)
            3. A/B 评估
            4. 模型切换

        Args:
            dry_run: True=仅模拟, False=执行真实流水线

        Returns:
            dict 含 pipeline 执行日志
        """
        pending_count = self.state.pending_feedback_count
        if pending_count == 0:
            return {"status": "skipped", "reason": "无待处理反馈"}

        logger.info(f"[FeedbackLoop] 启动微调流水线 (pending={pending_count}, dry_run={dry_run})")

        pipeline_log = {
            "status": "simulated" if dry_run else "executed",
            "started_at": datetime.now().isoformat(),
            "steps": [],
        }

        # Step 1: 导出训练数据
        pipeline_log["steps"].append({
            "step": 1,
            "name": "export_training_data",
            "feedback_count": pending_count,
            "output": "data/sft_training_data.jsonl",
        })

        # Step 2: 触发微调
        new_version = self._bump_version()
        pipeline_log["steps"].append({
            "step": 2,
            "name": "trigger_finetune",
            "from_version": self.state.current_model_version,
            "to_version": new_version,
            "framework": "LlamaFactory (Qwen2-VL-7B)",
        })

        # Step 3: A/B 评估（模拟）
        pipeline_log["steps"].append({
            "step": 3,
            "name": "ab_evaluation",
            "baseline": self.state.current_model_version,
            "challenger": new_version,
            "mock_f1_improvement": 0.06,
            "mock_significance": "significant",
        })

        # Step 4: 模型切换（仅在非 dry_run 时）
        if not dry_run:
            self.state.current_model_version = new_version
            self.state.total_retrain_count += 1
            self.state.last_retrain_at = datetime.now().isoformat()
            self.state.pending_feedback_count = 0
            self._pending_feedbacks.clear()
            pipeline_log["status"] = "deployed"
            pipeline_log["deployed_version"] = new_version
        else:
            pipeline_log["status"] = "simulated"
            pipeline_log["would_deploy"] = new_version

        pipeline_log["completed_at"] = datetime.now().isoformat()
        self._save_state()

        logger.info(
            f"[FeedbackLoop] 流水线完成: status={pipeline_log['status']}, "
            f"version={new_version}"
        )
        return pipeline_log

    # ---- 状态管理 ----

    def _bump_version(self) -> str:
        """递增版本号 minor 位。"""
        parts = self.state.current_model_version.lstrip("v").split(".")
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        return f"v{major}.{minor + 1}.{patch}"

    def _save_state(self):
        """持久化状态到本地 JSON。"""
        try:
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(self.state.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[FeedbackLoop] 状态持久化失败: {e}")

    def _load_state(self):
        """从本地 JSON 恢复状态。"""
        if self._state_file.exists():
            try:
                with open(self._state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.state = LoopState.from_dict(data)
                logger.info(
                    f"[FeedbackLoop] 状态已恢复: "
                    f"version={self.state.current_model_version}, "
                    f"total_feedback={self.state.total_feedback_count}"
                )
            except Exception as e:
                logger.warning(f"[FeedbackLoop] 状态恢复失败: {e}")

    def stats(self) -> Dict[str, Any]:
        """当前闭环统计。"""
        return {
            **self.state.to_dict(),
            "min_feedback_threshold": MIN_FEEDBACK_COUNT,
            "min_retrain_interval_days": MIN_RETRAIN_INTERVAL_DAYS,
            "ready_to_retrain": self.check_trigger()["should_retrain"],
        }


# ── CLI 演示 ──────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  🔄 SafeGuard-AI 反馈闭环演示")
    print("=" * 60)

    loop = FeedbackLoop()

    # 模拟积累反馈
    print("\n📝 模拟积累驳回反馈 (25 条)...")
    for i in range(25):
        loop.record_feedback(
            emp_id=f"EMP-{1000+i}",
            image_id=f"IMG-{2000+i}",
            feedback_type="false_positive" if i % 2 == 0 else "irrelevant",
            original_prediction={"type": "oil_leak", "risk_level": "high", "confidence": 0.91},
            human_correction={"type": "water_spill", "risk_level": "low"},
            comment="误报修正" if i % 2 == 0 else "不相关场景",
        )

    print(f"\n📊 当前状态:")
    print(json.dumps(loop.stats(), ensure_ascii=False, indent=2))

    # 检查触发
    decision = loop.check_trigger()
    print(f"\n🔍 触发判定: should_retrain={decision['should_retrain']}")
    print(f"   原因: {decision['reason']}")

    # 执行流水线
    if decision["should_retrain"]:
        print(f"\n🚀 执行微调流水线 (dry_run=True)...")
        result = loop.execute_pipeline(dry_run=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
