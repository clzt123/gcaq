"""
多维自适应记忆系统

管理短期工作记忆（滑动窗口缓冲 / Redis）、长期专家经验记忆
（Mock 关键词 / Milvus 向量检索）、员工安全画像与反思进化闭环。

核心类:
    MemoryManager: 统一记忆读写接口
"""
from app.core.memory.manager import MemoryManager

__all__ = ["MemoryManager"]
