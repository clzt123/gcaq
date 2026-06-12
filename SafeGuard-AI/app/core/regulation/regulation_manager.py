"""
法规变更影响分析管理器

实现技术方案功能 5 — 统一入口，协调文本对比和影响分析。

完整流程:
    法规变更数据 → TextDiffer 对比 → ImpactAnalyzer 追溯 → 影响报告
"""
import logging
from typing import Any, Dict, List, Optional

from app.core.regulation.text_differ import TextDiffer, DiffResult
from app.core.regulation.impact_analyzer import ImpactAnalyzer, ImpactReport

logger = logging.getLogger(__name__)


class RegulationManager:
    """
    法规变更影响分析管理器。

    提供从法规变更到影响评估的端到端分析。

    使用方式:
        mgr = RegulationManager()
        report = await mgr.analyze_change("REG-CHG-001")
        print(f"影响 {report.total_impacted} 个实体")
    """

    def __init__(self):
        """初始化管理器。"""
        self._differ = TextDiffer()
        self._analyzer = ImpactAnalyzer()

    async def analyze_change(self, change_id: Optional[str] = None) -> Optional[ImpactReport]:
        """
        分析法规变更的影响范围。

        流程:
            1. 加载法规变更数据（Mock 模式）
            2. Text-Diff 执行新旧文本对比
            3. ImpactAnalyzer 反向追溯图谱
            4. 返回完整影响报告

        Args:
            change_id: 法规变更 ID（None 则使用第一个）

        Returns:
            ImpactReport 或 None（无数据时）
        """
        logger.info(f"[RegulationManager] 分析法规变更: {change_id or '默认'}")

        # Step 1: 执行文本对比
        diff_result = self._differ.compare_from_mock(change_id)
        if not diff_result:
            logger.warning("[RegulationManager] 未找到法规变更数据")
            return None

        # Step 2: 执行影响分析
        report = await self._analyzer.analyze(diff_result)

        logger.info(
            f"[RegulationManager] 分析完成: {report.regulation_name} → "
            f"{report.total_impacted} 个实体受影响"
        )
        return report

    async def analyze_custom_change(
        self,
        regulation_name: str,
        sections: List[Dict[str, Any]],
    ) -> ImpactReport:
        """
        分析自定义法规变更（非 Mock 数据）。

        Args:
            regulation_name: 法规名称
            sections: 条款变更列表 [{section_id, title, old_text, new_text, keywords}]

        Returns:
            ImpactReport
        """
        # Step 1: 文本对比
        diff_result = self._differ.compare_regulation(regulation_name, sections)

        # Step 2: 影响分析
        report = await self._analyzer.analyze(diff_result)
        return report

    def list_available_changes(self) -> List[Dict[str, str]]:
        """列出可用的法规变更数据。"""
        return self._differ.list_mock_changes()
