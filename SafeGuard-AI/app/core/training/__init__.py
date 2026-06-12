"""
个性化培训模块

实现技术方案功能 15 — 个性化培训：
    1. Collaborative Filtering 推荐算法（基于员工画像推荐事故案例）
    2. LLM 案例→选择题/判断题自动生成

依赖: 功能 9（员工画像 ✅ 已就绪）
"""

from app.core.training.recommend_engine import RecommendEngine, RecommendationResult
from app.core.training.question_generator import QuestionGenerator, TrainingQuestion
from app.core.training.training_manager import TrainingManager

__all__ = [
    "RecommendEngine",
    "RecommendationResult",
    "QuestionGenerator",
    "TrainingQuestion",
    "TrainingManager",
]
