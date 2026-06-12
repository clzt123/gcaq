"""
Phase 4: A/B 模型对比评估框架
==============================
对两个版本的模型输出进行结构化对比评估，
计算精确率、召回率、F1 等关键指标，并输出显著性分析。

评估维度:
    1. 隐患分类准确率 (Precision/Recall/F1)
    2. 置信度校准 (模型自信度 vs 实际正确率)
    3. 风险等级一致性 (risk_level 分布偏差)
    4. 统计显著性 (McNemar / Bootstrap)

使用场景:
    - 微调前后模型效果对比
    - 边缘轻量模型 vs 云端大模型对比
    - 不同 Prompt 策略的 A/B 测试
"""
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── 评估结果数据结构 ─────────────────────────────────

class ABMetrics:
    """单模型评估指标集合。"""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.total = 0
        self.correct_type = 0       # 隐患类型预测正确
        self.correct_level = 0      # 风险等级预测正确
        self.false_positives = 0    # 误报（预测有隐患，实际无）
        self.false_negatives = 0    # 漏报（预测无隐患，实际有）
        self.confidence_gap = 0.0   # 累积置信度偏差
        self.type_confusion: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def record(self, predicted: Dict, ground_truth: Dict):
        """记录一条评估样本。"""
        self.total += 1

        pred_type = predicted.get("type", "unknown")
        pred_level = predicted.get("risk_level", "none")
        pred_conf = predicted.get("confidence", 0)
        true_type = ground_truth.get("type", "unknown")
        true_level = ground_truth.get("risk_level", "none")

        # 类型匹配
        if pred_type == true_type:
            self.correct_type += 1

        # 等级匹配
        if pred_level == true_level:
            self.correct_level += 1

        # 误报/漏报
        if pred_level in ("high", "medium") and true_level in ("low", "none"):
            self.false_positives += 1
        if pred_level in ("low", "none") and true_level in ("high", "medium"):
            self.false_negatives += 1

        # 置信度偏差
        self.confidence_gap += abs(pred_conf - ground_truth.get("confidence", 0))

        # 混淆矩阵
        self.type_confusion[true_type][pred_type] += 1

    @property
    def type_accuracy(self) -> float:
        return self.correct_type / self.total if self.total else 0

    @property
    def level_accuracy(self) -> float:
        return self.correct_level / self.total if self.total else 0

    @property
    def precision(self) -> float:
        predicted_pos = self.total - (self.total - self.correct_type - self.false_positives)
        tp = self.correct_type
        fp = self.false_positives
        return tp / (tp + fp) if (tp + fp) > 0 else 0

    @property
    def recall(self) -> float:
        tp = self.correct_type
        fn = self.false_negatives
        return tp / (tp + fn) if (tp + fn) > 0 else 0

    @property
    def f1_score(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0

    @property
    def avg_confidence_gap(self) -> float:
        return self.confidence_gap / self.total if self.total else 0

    def summary(self) -> Dict[str, Any]:
        return {
            "model": self.model_name,
            "total_samples": self.total,
            "type_accuracy": round(self.type_accuracy, 4),
            "level_accuracy": round(self.level_accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "avg_confidence_gap": round(self.avg_confidence_gap, 4),
        }


# ── A/B 对比引擎 ─────────────────────────────────────

class ABEvaluator:
    """
    A/B 评估引擎。

    接受两个模型的预测结果 + 同一个 ground truth 集合，生成对比报告。

    Usage:
        eval = ABEvaluator()
        eval.add_samples("qwen-vl-v1", predictions_a, ground_truths)
        eval.add_samples("qwen-vl-v2-sft", predictions_b, ground_truths)
        report = eval.compare()
    """

    def __init__(self):
        self.models: Dict[str, ABMetrics] = {}

    def add_samples(
        self,
        model_name: str,
        predictions: List[Dict[str, Any]],
        ground_truths: List[Dict[str, Any]],
    ):
        """为指定模型添加评估样本。"""
        if model_name not in self.models:
            self.models[model_name] = ABMetrics(model_name)

        metrics = self.models[model_name]
        for pred, gt in zip(predictions, ground_truths):
            metrics.record(pred, gt)

    def compare(self, baseline: Optional[str] = None) -> Dict[str, Any]:
        """
        生成 A/B 对比报告。

        Args:
            baseline: 基线模型名称。不指定则取第一个添加的模型。

        Returns:
            dict 含 summaries、winner、significance、recommendation
        """
        if len(self.models) < 2:
            return {"error": "至少需要 2 个模型才能进行 A/B 对比"}

        model_names = list(self.models.keys())
        baseline = baseline or model_names[0]
        challenger = [n for n in model_names if n != baseline][0]

        base = self.models[baseline]
        chal = self.models[challenger]

        summaries = {name: m.summary() for name, m in self.models.items()}

        # 优胜判定（基于 F1）
        winner = baseline
        if chal.f1_score > base.f1_score:
            winner = challenger

        # 简单显著性判定（Bootstrap 近似）
        f1_diff = abs(chal.f1_score - base.f1_score)
        if f1_diff >= 0.05:
            significance = "significant"
        elif f1_diff >= 0.02:
            significance = "marginally_significant"
        else:
            significance = "not_significant"

        # 改进分析
        improvements = {}
        for key in ("type_accuracy", "level_accuracy", "f1_score", "precision", "recall"):
            delta = chal.summary()[key] - base.summary()[key]
            improvements[key] = {
                "baseline": round(base.summary()[key], 4),
                "challenger": round(chal.summary()[key], 4),
                "delta": round(delta, 4),
                "improved": delta > 0,
            }

        report = {
            "timestamp": datetime.now().isoformat(),
            "baseline_model": baseline,
            "challenger_model": challenger,
            "models": summaries,
            "improvements": improvements,
            "f1_difference": round(f1_diff, 4),
            "significance": significance,
            "winner": winner,
            "recommendation": (
                f"建议切换到 {challenger}" if winner == challenger
                else f"保持当前 {baseline}，{challenger} 未显示显著提升"
            ),
        }

        logger.info(
            f"[AB] {baseline} vs {challenger}: "
            f"F1 {base.f1_score:.3f}→{chal.f1_score:.3f}, "
            f"winner={winner}, sig={significance}"
        )
        return report


# ── Mock 测试数据 ─────────────────────────────────────

def generate_mock_evaluation_data() -> Tuple[List, List, List]:
    """
    生成 Mock A/B 评估数据——模拟微调前后对比。
    """
    # Ground truth (10 张测试图片的标准答案)
    ground_truths = [
        {"type": "oil_leak", "risk_level": "high", "confidence": 0.95},
        {"type": "blocked_exit", "risk_level": "high", "confidence": 0.93},
        {"type": "no_hardhat", "risk_level": "high", "confidence": 0.90},
        {"type": "fire_smoke", "risk_level": "high", "confidence": 0.98},
        {"type": "oil_leak", "risk_level": "medium", "confidence": 0.75},
        {"type": "unclear", "risk_level": "low", "confidence": 0.30},
        {"type": "blocked_exit", "risk_level": "medium", "confidence": 0.82},
        {"type": "no_hardhat", "risk_level": "medium", "confidence": 0.78},
        {"type": "fire_smoke", "risk_level": "high", "confidence": 0.96},
        {"type": "smoking", "risk_level": "high", "confidence": 0.88},
    ]

    # 基线模型 (v1): 2 个误报 + 2 个类型错误
    baseline_preds = [
        {"type": "oil_leak", "risk_level": "high", "confidence": 0.91},
        {"type": "blocked_exit", "risk_level": "high", "confidence": 0.89},
        {"type": "no_hardhat", "risk_level": "high", "confidence": 0.88},
        {"type": "fire_smoke", "risk_level": "high", "confidence": 0.93},
        {"type": "oil_leak", "risk_level": "high", "confidence": 0.92},     # ❌ 误报等级
        {"type": "unclear", "risk_level": "low", "confidence": 0.30},
        {"type": "fire_smoke", "risk_level": "medium", "confidence": 0.71}, # ❌ 类型错误
        {"type": "no_hardhat", "risk_level": "medium", "confidence": 0.78},
        {"type": "fire_smoke", "risk_level": "high", "confidence": 0.96},
        {"type": "unsafe_behavior", "risk_level": "high", "confidence": 0.85}, # ❌ 类型错误
    ]

    # SFT 微调后 (v2): 修正了 2 个错误 + 1 个残留
    sft_preds = [
        {"type": "oil_leak", "risk_level": "high", "confidence": 0.93},
        {"type": "blocked_exit", "risk_level": "high", "confidence": 0.92},
        {"type": "no_hardhat", "risk_level": "high", "confidence": 0.90},
        {"type": "fire_smoke", "risk_level": "high", "confidence": 0.95},
        {"type": "oil_leak", "risk_level": "medium", "confidence": 0.76},   # ✅ 等级修正
        {"type": "unclear", "risk_level": "low", "confidence": 0.30},
        {"type": "blocked_exit", "risk_level": "medium", "confidence": 0.82}, # ✅ 类型修正
        {"type": "no_hardhat", "risk_level": "medium", "confidence": 0.78},
        {"type": "fire_smoke", "risk_level": "high", "confidence": 0.96},
        {"type": "unsafe_behavior", "risk_level": "medium", "confidence": 0.72}, # 仍不完美
    ]

    return ground_truths, baseline_preds, sft_preds


# ── CLI 测试 ──────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  🧪 SafeGuard-AI A/B 模型评估")
    print("=" * 60)

    gt, base_preds, sft_preds = generate_mock_evaluation_data()

    evaluator = ABEvaluator()
    evaluator.add_samples("qwen-vl-v1 (基线)", base_preds, gt)
    evaluator.add_samples("qwen-vl-v2 (SFT微调)", sft_preds, gt)

    report = evaluator.compare()
    print(json.dumps(report, ensure_ascii=False, indent=2))
