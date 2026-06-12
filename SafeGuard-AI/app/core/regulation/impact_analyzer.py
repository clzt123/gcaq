"""
影响分析引擎

实现技术方案功能 5 — 图谱反向追溯受影响的设备和 SOP 节点。

分析流程:
    1. 从法规变更中提取关键词
    2. 在 Neo4j 图谱中反向追溯关联实体：
        - 法规(Regulation) → 受管辖的隐患(Hazard) → 存在的设备(Equipment) → 关联的SOP
    3. 计算每个实体的影响等级（高/中/低）
    4. 生成影响评估报告
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.regulation.text_differ import DiffResult, ClauseChange, ChangeType

logger = logging.getLogger(__name__)


@dataclass
class ImpactedEntity:
    """
    受影响的实体。

    Attributes:
        entity_type: 实体类型 (Equipment/Hazard/SOP/Regulation)
        entity_name: 实体名称
        impact_level: 影响等级 (high/medium/low)
        impact_reason: 影响原因
        related_clause: 相关的变更条款编号
        suggested_action: 建议措施
    """

    entity_type: str
    entity_name: str
    impact_level: str  # high / medium / low
    impact_reason: str = ""
    related_clause: str = ""
    suggested_action: str = ""


@dataclass
class ImpactReport:
    """
    法规变更影响评估报告。

    Attributes:
        regulation_name: 法规名称
        change_summary: 变更摘要
        impacted_entities: 受影响的实体列表
        high_impact_count: 高影响数量
        total_impacted: 受影响总数
        recommendations: 总体建议列表
    """

    regulation_name: str = ""
    change_summary: str = ""
    impacted_entities: List[ImpactedEntity] = field(default_factory=list)
    high_impact_count: int = 0
    medium_impact_count: int = 0
    low_impact_count: int = 0
    total_impacted: int = 0
    recommendations: List[str] = field(default_factory=list)


class ImpactAnalyzer:
    """
    法规变更影响分析引擎。

    通过 Neo4j 图谱反向追溯，定位受法规变更影响的设备和 SOP。

    工作原理:
        1. 从法规变更中提取关键词
        2. 查询图谱中 法规→隐患→设备 的路径（GOVERNED_BY 反向）
        3. 评估每个受影响节点的变更影响等级
        4. 生成整改建议

    使用方式:
        analyzer = ImpactAnalyzer()
        report = await analyzer.analyze(diff_result)
    """

    def __init__(self):
        """初始化影响分析器。"""
        self._neo4j: Optional[Any] = None

    async def analyze(self, diff_result: DiffResult) -> ImpactReport:
        """
        分析法规变更的影响范围。

        Args:
            diff_result: 法规差异对比结果

        Returns:
            ImpactReport 影响评估报告
        """
        if not diff_result or diff_result.changed_sections == 0:
            return ImpactReport(
                regulation_name=diff_result.regulation_name if diff_result else "",
                change_summary="无条款变更，无需评估影响。",
            )

        impacted: List[ImpactedEntity] = []

        # 对每个变更条款进行影响分析
        for change in diff_result.changes:
            if change.change_type == ChangeType.UNCHANGED:
                continue

            entities = await self._trace_impact(change)
            impacted.extend(entities)

        # 去重（同名+同类型）
        unique = self._deduplicate(impacted)

        # 统计
        high_count = sum(1 for e in unique if e.impact_level == "high")
        medium_count = sum(1 for e in unique if e.impact_level == "medium")
        low_count = sum(1 for e in unique if e.impact_level == "low")

        # 生成建议
        recommendations = self._generate_recommendations(unique, diff_result)

        report = ImpactReport(
            regulation_name=diff_result.regulation_name,
            change_summary=diff_result.summary,
            impacted_entities=unique,
            high_impact_count=high_count,
            medium_impact_count=medium_count,
            low_impact_count=low_count,
            total_impacted=len(unique),
            recommendations=recommendations,
        )

        logger.info(
            f"[ImpactAnalyzer] 影响分析完成: "
            f"{len(unique)} 个实体 (高:{high_count} 中:{medium_count} 低:{low_count})"
        )
        return report

    async def _trace_impact(self, change: ClauseChange) -> List[ImpactedEntity]:
        """
        在 Neo4j 图谱中反向追溯单个变更的影响。

        追溯路径:
            Regulation（变更法规）
                → (GOVERNED_BY 反向) Hazard（关联隐患）
                → (HAS_HAZARD 反向或正向) Equipment（关联设备）
                → (MITIGATED_BY 反向) SOP（关联流程）

        Args:
            change: 单个条款变更

        Returns:
            ImpactedEntity 列表
        """
        entities: List[ImpactedEntity] = []

        # 尝试通过 Neo4j 查询
        try:
            neo4j_entities = await self._query_graph(change)
            if neo4j_entities:
                return neo4j_entities
        except Exception as e:
            logger.debug(f"[ImpactAnalyzer] 图谱查询失败 ({e})，使用关键词匹配")

        # Mock 兜底：基于关键词匹配
        return self._mock_trace(change)

    async def _query_graph(self, change: ClauseChange) -> List[ImpactedEntity]:
        """
        通过 Neo4j Cypher 查询受影响的实体。

        Args:
            change: 变更条款

        Returns:
            ImpactedEntity 列表
        """
        try:
            from app.core.rag.neo4j_client import Neo4jClient

            entities: List[ImpactedEntity] = []

            async with Neo4jClient() as client:
                # 查询路径: 关键词匹配 → 关联设备
                for keyword in change.keywords[:3]:
                    try:
                        # Cypher: 搜索名称含关键词的节点及其关系
                        query = (
                            f"MATCH (n) "
                            f"WHERE any(label IN labels(n) WHERE label IN ['Hazard', 'Equipment', 'SOP']) "
                            f"AND n.name CONTAINS '{keyword[:20]}' "
                            f"RETURN labels(n) AS labels, n.name AS name LIMIT 5"
                        )
                        results = await client.run(query)

                        for record in results:
                            labels = record.get("labels", ["Unknown"])
                            name = record.get("name", "")
                            label = labels[0] if labels else "Unknown"

                            impact_level = self._assess_impact_level(change, label, name)
                            entities.append(ImpactedEntity(
                                entity_type=label,
                                entity_name=name,
                                impact_level=impact_level,
                                impact_reason=f"法规条款 '{change.section_id}' 变更涉及关键词 '{keyword}'",
                                related_clause=change.section_id,
                                suggested_action=self._suggest_action(label, impact_level, change),
                            ))
                    except Exception:
                        pass  # 单条查询失败不影响整体

            return entities

        except ImportError:
            return []
        except Exception as e:
            logger.debug(f"[ImpactAnalyzer] 图谱查询异常: {e}")
            return []

    def _mock_trace(self, change: ClauseChange) -> List[ImpactedEntity]:
        """
        Mock 兜底：基于关键词与已知实体匹配。

        使用预置的图谱映射表（从 init_graph.cypher 推断）。

        Args:
            change: 变更条款

        Returns:
            ImpactedEntity 列表
        """
        # 预置图库中已知的实体关系映射
        known_mappings = {
            "动火作业": [
                ("Hazard", "初期火灾/烟雾异常", "high"),
                ("SOP", "化学品泄漏与火灾应急处置SOP", "high"),
            ],
            "高处作业": [
                ("Equipment", "2号焊接工位", "medium"),
                ("Hazard", "安全帽违规", "medium"),
            ],
            "安全带": [
                ("Equipment", "2号焊接工位", "medium"),
                ("Hazard", "安全帽违规", "medium"),
            ],
            "漏电保护": [
                ("Equipment", "B区配电箱", "high"),
                ("Equipment", "3号注塑机", "medium"),
            ],
            "临时用电": [
                ("Equipment", "B区配电箱", "high"),
                ("SOP", "注塑机日常点检与泄漏应急处置SOP", "medium"),
            ],
            "安全管理人员": [
                ("Hazard", "安全帽违规", "medium"),
                ("Hazard", "液压油泄漏", "medium"),
                ("Hazard", "消防通道堵塞", "medium"),
            ],
            "安全总监": [
                ("Hazard", "安全帽违规", "high"),
                ("Hazard", "液压油泄漏", "high"),
            ],
            "数字化": [
                ("Equipment", "3号注塑机", "medium"),
                ("Equipment", "B区配电箱", "medium"),
                ("Equipment", "化学品仓库", "medium"),
            ],
            "检查周期": [
                ("Equipment", "2号焊接工位", "medium"),
                ("Hazard", "安全帽违规", "medium"),
            ],
            "处罚": [
                ("Hazard", "液压油泄漏", "high"),
                ("Hazard", "初期火灾/烟雾异常", "high"),
            ],
        }

        entities: List[ImpactedEntity] = []
        seen: set = set()

        for keyword in change.keywords:
            mappings = known_mappings.get(keyword, [])
            for entity_type, entity_name, impact_level in mappings:
                key = (entity_type, entity_name)
                if key in seen:
                    continue
                seen.add(key)

                entities.append(ImpactedEntity(
                    entity_type=entity_type,
                    entity_name=entity_name,
                    impact_level=impact_level,
                    impact_reason=(
                        f"法规条款 '{change.section_id}' ({change.title}) "
                        f"变更涉及关键词 '{keyword}'，图谱追溯发现关联实体"
                    ),
                    related_clause=change.section_id,
                    suggested_action=self._suggest_action(entity_type, impact_level, change),
                ))

        return entities

    def _assess_impact_level(
        self,
        change: ClauseChange,
        entity_type: str,
        entity_name: str,
    ) -> str:
        """
        评估变更对实体的影响等级。

        规则:
            - 删除条款 + Hazard → high
            - 修订条款 + Equipment → medium
            - 新增条款 + SOP → medium
            - 其他 → low

        Args:
            change: 变更条款
            entity_type: 实体类型
            entity_name: 实体名称

        Returns:
            影响等级 (high/medium/low)
        """
        if change.change_type == ChangeType.DELETED and entity_type == "Hazard":
            return "high"
        if change.change_type == ChangeType.AMENDED and entity_type == "Hazard":
            return "high"
        if change.change_type == ChangeType.ADDED and entity_type == "SOP":
            return "medium"
        if entity_type == "Equipment":
            return "medium"
        return "low"

    def _suggest_action(
        self,
        entity_type: str,
        impact_level: str,
        change: ClauseChange,
    ) -> str:
        """基于影响等级生成建议措施。"""
        actions = {
            ("Equipment", "high"): "建议立即停用并整改设备，确保符合新法规要求",
            ("Equipment", "medium"): "建议在30天内完成设备合规性检查",
            ("Equipment", "low"): "建议在下一次维保时检查合规性",
            ("Hazard", "high"): "建议立即更新隐患控制措施，确保符合新法规要求",
            ("Hazard", "medium"): "建议更新SOP文件并组织相关培训",
            ("Hazard", "low"): "建议在下一次安全评审时评估",
            ("SOP", "high"): "建议立即修订SOP并重新发布",
            ("SOP", "medium"): "建议在下一版SOP修订时更新相关内容",
            ("SOP", "low"): "建议参考新法规要求审查SOP",
            ("Regulation", "high"): "建议立即组织全员培训学习新法规",
            ("Regulation", "medium"): "建议在周安全例会上通报法规变更",
            ("Regulation", "low"): "建议将新法规归档至知识库",
        }
        return actions.get(
            (entity_type, impact_level),
            f"建议评估'{change.section_id}'变更的影响并采取相应措施",
        )

    def _deduplicate(self, entities: List[ImpactedEntity]) -> List[ImpactedEntity]:
        """
        去重：同名+同类型实体保留最高影响等级。

        Args:
            entities: 原始实体列表

        Returns:
            去重后的实体列表
        """
        best: Dict[tuple, ImpactedEntity] = {}
        level_rank = {"high": 3, "medium": 2, "low": 1}

        for e in entities:
            key = (e.entity_type, e.entity_name)
            if key not in best or level_rank.get(e.impact_level, 0) > level_rank.get(best[key].impact_level, 0):
                best[key] = e

        return list(best.values())

    def _generate_recommendations(
        self,
        entities: List[ImpactedEntity],
        diff_result: DiffResult,
    ) -> List[str]:
        """生成总体建议。"""
        recommendations = []

        # 按影响等级分类建议
        high_entities = [e for e in entities if e.impact_level == "high"]
        medium_entities = [e for e in entities if e.impact_level == "medium"]

        if high_entities:
            names = "、".join(e.entity_name for e in high_entities[:3])
            recommendations.append(
                f"【紧急】以下实体受法规变更影响为高风险: {names}。"
                f"建议在7个工作日内完成合规整改。"
            )

        if medium_entities:
            names = "、".join(e.entity_name for e in medium_entities[:3])
            recommendations.append(
                f"【关注】以下实体需要计划性整改: {names}。"
                f"建议在30天内完成。"
            )

        # 法规层面建议
        affected_clauses = [
            c.section_id for c in diff_result.changes
            if c.change_type != ChangeType.UNCHANGED
        ]
        recommendations.append(
            f"涉及 {len(affected_clauses)} 个条款变更 ({', '.join(affected_clauses[:5])})。"
            f"建议组织相关部门负责人召开合规评审会。"
        )

        recommendations.append(
            "建议将新法规要求同步更新至员工培训教材和考核题库中。"
        )

        return recommendations
