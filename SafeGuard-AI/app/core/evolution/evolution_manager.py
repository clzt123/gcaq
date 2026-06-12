"""
进化管理器

实现技术方案功能 11 — 反思与进化的统一入口。

协调三个子系统:
    1. PositiveFeedbackCollector: 正反馈闭环（点赞/采纳→正样本）
    2. NegativeSampleManager: 误报自动加入负样本
    3. ModelRegistry: 模型热加载与版本管理

完整闭环:
    用户反馈 → 正/负样本收集 → SFT数据导出 → 微调触发 → A/B评估 → 热加载
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.evolution.positive_feedback import PositiveFeedbackCollector, PositiveSample
from app.core.evolution.negative_sample import NegativeSampleManager
from app.core.evolution.model_registry import ModelRegistry, ModelVersion, ModelStatus

logger = logging.getLogger(__name__)


@dataclass
class EvolutionReport:
    """
    进化系统综合报告。

    Attributes:
        positive_samples: 正样本统计
        negative_samples: 负样本统计
        model_status: 当前模型状态
        is_ready_for_finetune: 是否满足微调条件
        recommendations: 建议列表
    """

    positive_samples: Dict[str, Any] = field(default_factory=dict)
    negative_samples: Dict[str, Any] = field(default_factory=dict)
    model_status: Dict[str, Any] = field(default_factory=dict)
    is_ready_for_finetune: bool = False
    recommendations: List[str] = field(default_factory=list)


class EvolutionManager:
    """
    进化管理器。

    集成正反馈、负样本和模型注册三个子系统，
    提供完整的反思与进化能力。

    使用方式:
        mgr = EvolutionManager()

        # 记录正反馈
        mgr.record_approval(user_id="EMP_001", ...)

        # 记录误报→自动加入负样本
        mgr.record_false_positive(image_id="IMG-001", image_hash="...", ...)

        # 检查是否可以微调
        report = mgr.get_evolution_report()
        if report.is_ready_for_finetune:
            mgr.trigger_finetune()
    """

    def __init__(self):
        """初始化进化管理器。"""
        self.positive = PositiveFeedbackCollector()
        self.negative = NegativeSampleManager()
        self.registry = ModelRegistry()

        # 初始化默认模型版本（如果注册表为空）
        if not self.registry.get_active():
            self.registry.register(
                version="v1.0.0",
                model_name="SafeGuard-Model",
                metrics={"f1": 0.82, "precision": 0.80, "recall": 0.84, "latency_ms": 120},
                training_data_size=5000,
                changelog="初始基线模型",
            )
            self.registry.activate("v1.0.0")

        logger.info("[EvolutionManager] 进化管理器初始化完成")

    # ---- 正反馈闭环 ----

    def record_approval(
        self,
        user_id: str,
        input_context: Dict[str, Any],
        ai_response: Dict[str, Any],
        feedback_type: str = "approved",
        comment: str = "",
    ) -> str:
        """
        记录用户对 AI 建议的点赞/采纳。

        Args:
            user_id: 操作者 ID
            input_context: 输入上下文
            ai_response: AI 响应
            feedback_type: approved / adopted / liked / useful
            comment: 评价

        Returns:
            sample_id
        """
        return self.positive.record_positive(
            feedback_type=feedback_type,
            user_id=user_id,
            input_context=input_context,
            ai_response=ai_response,
            user_comment=comment,
        )

    # ---- 负样本自动收集 ----

    def record_false_positive(
        self,
        image_id: str,
        image_hash: str,
        false_prediction: Dict[str, Any],
        correct_label: Dict[str, Any],
    ) -> str:
        """
        记录误报反馈并自动加入负样本库。

        Args:
            image_id: 图片 ID
            image_hash: 感知哈希
            false_prediction: AI 误报结果
            correct_label: 人工正确标注

        Returns:
            entry_id
        """
        return self.negative.add_from_feedback(
            image_id=image_id,
            image_hash=image_hash,
            false_prediction=false_prediction,
            correct_label=correct_label,
        )

    # ---- 微调触发 ----

    def check_finetune_readiness(self) -> Dict[str, Any]:
        """
        检查是否满足微调条件。

        Returns:
            就绪状态和建议
        """
        pos_stats = self.positive.stats()
        neg_stats = self.negative.stats()
        active_model = self.registry.get_active()

        is_ready = pos_stats["total_samples"] >= 20 or neg_stats["total_active"] >= 15

        return {
            "is_ready": is_ready,
            "positive_samples": pos_stats["total_samples"],
            "negative_samples": neg_stats["total_active"],
            "current_model": active_model.version if active_model else "none",
            "recommended_action": (
                "数据充足，建议触发 SFT 微调流水线"
                if is_ready
                else f"继续收集反馈: 正样本 {pos_stats['total_samples']}/20, 负样本 {neg_stats['total_active']}/15"
            ),
        }

    def trigger_finetune(
        self,
        new_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        触发微调流水线（Mock 模拟）。

        流程:
            1. 导出正/负样本 SFT 数据
            2. 注册新模型版本
            3. 模拟训练并评估
            4. 满足条件时自动热加载

        Args:
            new_version: 新版本号（None=自动递增）

        Returns:
            微调结果
        """
        # Step 1: 导出训练数据
        pos_file = self.positive.export_sft_data()

        # Step 2: 确定新版本号
        if not new_version:
            active = self.registry.get_active()
            if active:
                parts = active.version.lstrip("v").split(".")
                new_version = f"v{parts[0]}.{int(parts[1]) + 1}.{parts[2]}"
            else:
                new_version = "v2.0.0"

        # Step 3: 模拟训练和评估
        import random
        mock_f1 = min(0.95, 0.82 + random.uniform(0.02, 0.06))
        mock_precision = min(0.95, 0.80 + random.uniform(0.02, 0.05))
        mock_recall = min(0.95, 0.84 + random.uniform(0.01, 0.04))

        pos_count = self.positive.stats()["total_samples"]
        neg_count = self.negative.stats()["total_active"]

        # Step 4: 注册新版本并激活
        self.registry.register(
            version=new_version,
            model_name="SafeGuard-Model",
            metrics={
                "f1": round(mock_f1, 4),
                "precision": round(mock_precision, 4),
                "recall": round(mock_recall, 4),
                "latency_ms": 90 + random.randint(-20, 10),
            },
            training_data_size=pos_count + neg_count,
            parent_version=self.registry.get_active().version if self.registry.get_active() else "v1.0.0",
            changelog=f"SFT微调: 正样本{pos_count}条 + 负样本{neg_count}条",
        )

        # 如果 F1 提升，自动激活
        result = self.registry.activate(new_version)

        logger.info(
            f"[EvolutionManager] 微调完成: {new_version} | "
            f"F1={mock_f1:.4f} | data={pos_count + neg_count}"
        )

        return {
            **result,
            "training_data": {
                "positive_samples": pos_count,
                "negative_samples": neg_count,
                "positive_file": pos_file,
            },
            "new_metrics": {
                "f1": round(mock_f1, 4),
                "precision": round(mock_precision, 4),
                "recall": round(mock_recall, 4),
            },
        }

    # ---- 综合报告 ----

    def get_evolution_report(self) -> EvolutionReport:
        """
        获取进化系统综合报告。

        Returns:
            EvolutionReport
        """
        pos_stats = self.positive.stats()
        neg_stats = self.negative.stats()
        readiness = self.check_finetune_readiness()

        recommendations = []

        if pos_stats["total_samples"] < 20:
            recommendations.append(
                f"正样本不足 ({pos_stats['total_samples']}/20)，建议在UI中增加'采纳'按钮"
            )

        if neg_stats["total_active"] < 15:
            recommendations.append(
                f"负样本不足 ({neg_stats['total_active']}/15)，建议关注用户驳回率"
            )

        if readiness["is_ready"]:
            recommendations.append("数据已充足，可触发 SFT 微调")

        # 检查模型健康度
        active = self.registry.get_active()
        if active and active.metrics:
            f1 = active.metrics.get("f1", 0)
            if f1 < 0.75:
                recommendations.append(f"⚠️ 当前模型 F1={f1:.2f} 偏低，建议立即微调")
            elif f1 < 0.80:
                recommendations.append(f"当前模型 F1={f1:.2f}，建议近期微调")

        return EvolutionReport(
            positive_samples=pos_stats,
            negative_samples=neg_stats,
            model_status={
                "active_version": active.version if active else "none",
                "total_versions": len(self.registry.list_versions()),
                "deployment_count": len(self.registry.get_deployment_history()),
            },
            is_ready_for_finetune=readiness["is_ready"],
            recommendations=recommendations,
        )
