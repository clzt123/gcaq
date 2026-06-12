"""
零幻觉校验模块 (Hallucination Guard)

实现技术方案功能 6 — 零幻觉校验：
    1. LLM 应答层强制 Citation Chaining（引用条款号）
    2. 显式"置信度 < 0.7 拒答"校验
    3. 拒答机制从检索层扩展到 Prompt/LLM 生成层

核心类:
    CitationVerifier  — 引用链格式验证器
    HallucinationGuard — 零幻觉校验门控（Pre/Prompt/Post 三层防线）
"""

from app.core.guard.hallucination_guard import (
    CitationVerifier,
    HallucinationGuard,
    REFUSAL_CONFIDENCE_THRESHOLD,
    HIGH_CITATION_THRESHOLD,
)

__all__ = [
    "CitationVerifier",
    "HallucinationGuard",
    "REFUSAL_CONFIDENCE_THRESHOLD",
    "HIGH_CITATION_THRESHOLD",
]
