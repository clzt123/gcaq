"""
反思与进化模块

实现技术方案功能 11 — 反思与进化：
    1. 正反馈闭环（点赞/采纳→存入正样本）
    2. 误报图片自动加入 Negative Sample 的后台任务
    3. 模型权重热加载/重启机制

依赖: FeedbackLoop（已存在），员工画像（功能 9）
"""

from app.core.evolution.positive_feedback import PositiveFeedbackCollector, PositiveSample
from app.core.evolution.negative_sample import NegativeSampleManager, NegativeSampleEntry
from app.core.evolution.model_registry import ModelRegistry, ModelVersion, ModelStatus
from app.core.evolution.evolution_manager import EvolutionManager

__all__ = [
    "PositiveFeedbackCollector",
    "PositiveSample",
    "NegativeSampleManager",
    "NegativeSampleEntry",
    "ModelRegistry",
    "ModelVersion",
    "ModelStatus",
    "EvolutionManager",
]
