"""
数字巡检员模块 (Digital Patrol Inspector)

实现技术方案功能 12 — 数字巡检员：
    1. APScheduler 7×24 定时巡检计划
    2. 图像哈希差异检测（历史帧 vs 当前帧）
    3. "由通变堵"/"由在变无" 状态变化识别

核心类:
    ImageHasher      — 图像感知哈希（aHash/pHash/dHash）
    ImageDiffer      — 图像差异检测器（历史基线 vs 当前帧）
    StateChangeDetector — 状态变化分类器
    PatrolScheduler  — 定时巡检调度器
"""

from app.core.patrol.scheduler import PatrolScheduler
from app.core.patrol.image_differ import ImageHasher, ImageDiffer
from app.core.patrol.state_monitor import StateChangeDetector, ChangeType

__all__ = [
    "PatrolScheduler",
    "ImageHasher",
    "ImageDiffer",
    "StateChangeDetector",
    "ChangeType",
]
