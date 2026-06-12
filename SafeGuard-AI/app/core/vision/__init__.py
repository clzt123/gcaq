"""
视觉分析模块

提供基于 Qwen-VL 的工业安全隐患图像识别能力。
支持安全帽、反光衣、吸烟、玩手机、违规闯入等各类隐患检测。

核心函数:
    analyze_image_with_qwen: 异步调用 Qwen-VL API 进行隐患识别
"""
from app.core.vision.analyzer import analyze_image_with_qwen

__all__ = ["analyze_image_with_qwen"]
