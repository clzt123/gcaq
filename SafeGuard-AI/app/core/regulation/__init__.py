"""
法规变更影响分析模块

实现技术方案功能 5 — 法规变更影响分析：
    1. Text-Diff 对比新旧法规文本，识别变更条款
    2. Neo4j 图谱反向追溯受影响的设备和 SOP 节点
    3. 影响评估报告生成

依赖: 功能 3（本体驱动图谱 ✅ 已就绪）、Neo4jClient
"""

from app.core.regulation.text_differ import TextDiffer, DiffResult, ClauseChange
from app.core.regulation.impact_analyzer import ImpactAnalyzer, ImpactReport
from app.core.regulation.regulation_manager import RegulationManager

__all__ = [
    "TextDiffer",
    "DiffResult",
    "ClauseChange",
    "ImpactAnalyzer",
    "ImpactReport",
    "RegulationManager",
]
