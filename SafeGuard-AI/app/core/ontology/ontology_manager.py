"""
本体驱动图谱管理器

实现技术方案功能 3 — 本体驱动图谱的统一入口。

协调三元组抽取、Schema 验证和 Neo4j 图谱写入的完整流程。

流程:
    文本 → TripletExtractor 三元组抽取 → SchemaManager 校验
    → Cypher 生成 → Neo4jClient 写入图谱

支持 Mock 模式和真实 Neo4j 连接。
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.ontology.triplet_extractor import TripletExtractor, Triplet, ExtractionResult
from app.core.ontology.schema_manager import SchemaManager, NodeType, RelationType

logger = logging.getLogger(__name__)


@dataclass
class GraphExpansionResult:
    """
    图谱扩展结果。

    Attributes:
        source_text: 源文本摘要
        extracted_count: 抽取的三元组总数
        validated_count: 通过 Schema 验证的数量
        inserted_count: 成功写入图谱的数量
        cypher_statements: 生成的 Cypher 语句列表
        new_relations_registered: 新注册的关系类型
        errors: 错误信息列表
    """

    source_text: str = ""
    extracted_count: int = 0
    validated_count: int = 0
    inserted_count: int = 0
    cypher_statements: List[str] = field(default_factory=list)
    new_relations_registered: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class OntologyManager:
    """
    本体驱动图谱管理器。

    提供从非结构化文本到 Neo4j 图谱的完整知识抽取管道。

    使用方式:
        mgr = OntologyManager()
        result = await mgr.expand_graph(
            "新的安全生产法要求所有焊接设备必须配备防火毯...",
        )
        print(f"成功写入 {result.inserted_count} 个三元组到图谱")
    """

    def __init__(self):
        """初始化管理器。"""
        self._extractor = TripletExtractor()
        self._schema = SchemaManager()
        self._neo4j: Optional[Any] = None
        logger.info("[OntologyManager] 管理器初始化完成")

    async def expand_graph(
        self,
        text: str,
        source_description: str = "",
    ) -> GraphExpansionResult:
        """
        从文本中抽取知识并扩展 Neo4j 图谱。

        完整流程:
            1. 三元组抽取（LLM + 正则兜底）
            2. Schema 校验（动态注册新类型）
            3. Cypher 语句生成
            4. 写入 Neo4j（Mock 或真实）

        Args:
            text: 输入文本
            source_description: 文本来源描述

        Returns:
            GraphExpansionResult
        """
        result = GraphExpansionResult(
            source_text=source_description or text[:100],
        )
        errors: List[str] = []

        # Step 1: 三元组抽取
        extraction = await self._extractor.extract(text)
        result.extracted_count = extraction.total_extracted

        if not extraction.triplets:
            logger.info("[OntologyManager] 三元组抽取结果为空")
            return result

        # Step 2: Schema 校验 + 动态类型注册
        validated_triplets: List[Triplet] = []
        for triplet in extraction.triplets:
            # 确保节点类型存在
            if not self._schema.has_node_type(triplet.subject_type):
                self._schema.register_node(
                    triplet.subject_type,
                    f"动态注册: {triplet.subject_type}",
                )

            if not self._schema.has_node_type(triplet.object_type):
                self._schema.register_node(
                    triplet.object_type,
                    f"动态注册: {triplet.object_type}",
                )

            # 确保关系类型存在
            if not self._schema.has_relation_type(triplet.relation):
                self._schema.ensure_relation_type(triplet.relation)
                result.new_relations_registered.append(triplet.relation)

            # 校验三元组
            valid, reason = self._schema.validate_triplet(
                triplet.subject_type,
                triplet.relation,
                triplet.object_type,
            )

            if valid:
                validated_triplets.append(triplet)
            else:
                errors.append(reason)
                logger.debug(f"[OntologyManager] 校验失败: {reason}")

        result.validated_count = len(validated_triplets)
        result.errors = errors
        logger.info(
            f"[OntologyManager] 校验: {result.validated_count}/{result.extracted_count} "
            f"通过 (新增关系类型: {len(result.new_relations_registered)})"
        )

        # Step 3: 生成 Cypher 语句
        cypher_statements = self._generate_cypher(validated_triplets)
        result.cypher_statements = cypher_statements

        # Step 4: 写入图谱
        result.inserted_count = await self._write_to_graph(cypher_statements)

        logger.info(
            f"[OntologyManager] 图谱扩展完成: "
            f"extracted={result.extracted_count}, "
            f"validated={result.validated_count}, "
            f"inserted={result.inserted_count}"
        )
        return result

    def _generate_cypher(self, triplets: List[Triplet]) -> List[str]:
        """
        将三元组转换为 Cypher MERGE 语句。

        使用 MERGE（而非 CREATE）防止重复节点。
        每个节点用 name 属性做唯一标识。

        Args:
            triplets: 验证通过的三元组列表

        Returns:
            Cypher 语句列表
        """
        statements = []
        for t in triplets:
            # 转义特殊字符防止 Cypher 注入
            safe_subj = self._escape_cypher(t.subject)
            safe_obj = self._escape_cypher(t.object)
            safe_rel = self._escape_cypher(t.relation)

            # 合并节点和关系
            cypher = (
                f"MERGE (a:{t.subject_type} {{name: '{safe_subj}'}}) "
                f"MERGE (b:{t.object_type} {{name: '{safe_obj}'}}) "
                f"MERGE (a)-[:{safe_rel} {{confidence: {t.confidence}}}]->(b)"
            )
            statements.append(cypher)

        return statements

    def _escape_cypher(self, text: str) -> str:
        """
        Cypher 字符串转义（防注入）。

        Args:
            text: 原始字符串

        Returns:
            转义后的字符串
        """
        # 转义单引号和反斜杠
        escaped = text.replace("\\", "\\\\").replace("'", "\\'")
        # 限制长度
        if len(escaped) > 500:
            escaped = escaped[:500]
        return escaped

    async def _write_to_graph(self, cypher_statements: List[str]) -> int:
        """
        将 Cypher 语句写入 Neo4j 图谱。

        优先使用真实 Neo4j，不可用时降级为 Mock 图谱。

        Args:
            cypher_statements: Cypher 语句列表

        Returns:
            成功写入的语句数
        """
        if not cypher_statements:
            return 0

        # 尝试真实 Neo4j
        try:
            real_count = await self._try_real_neo4j_write(cypher_statements)
            if real_count > 0:
                return real_count
        except Exception as e:
            logger.warning(f"[OntologyManager] 真实 Neo4j 写入失败 ({e})，使用 Mock")

        # Mock 降级
        return await self._mock_graph_write(cypher_statements)

    async def _try_real_neo4j_write(self, cypher_statements: List[str]) -> int:
        """尝试真实 Neo4j 写入。"""
        try:
            from app.core.rag.neo4j_client import Neo4jClient

            async with Neo4jClient() as client:
                count = 0
                for cypher in cypher_statements:
                    await client.run(cypher)
                    count += 1
                logger.info(
                    f"[OntologyManager] 真实 Neo4j 写入: {count} 条语句"
                )
                return count
        except ImportError:
            logger.info("[OntologyManager] Neo4jClient 不可用")
            return 0
        except Exception as e:
            logger.warning(f"[OntologyManager] 真实 Neo4j 写入异常: {e}")
            return 0

    async def _mock_graph_write(self, cypher_statements: List[str]) -> int:
        """
        Mock 图谱写入 — 解析 Cypher MERGE 更新内存图谱。

        维持与现有 _MockGraph 相同的语义。

        Args:
            cypher_statements: Cypher 语句列表

        Returns:
            成功解析的语句数
        """
        # 在 Mock 模式下，我们解析 MERGE 语句并直接操作 _MockGraph
        from app.core.rag.neo4j_client import Neo4jClient

        try:
            async with Neo4jClient() as client:
                if client._mode == "mock" and hasattr(client, '_graph'):
                    count = 0
                    for cypher in cypher_statements:
                        try:
                            # 解析 MERGE 语句提取节点和关系信息
                            parsed = self._parse_merge_cypher(cypher)
                            if parsed:
                                client._graph._nodes.append(parsed["subject"])
                                client._graph._nodes.append(parsed["object"])
                                client._graph._edges.append({
                                    "from_label": parsed["subject"].get("label", ""),
                                    "from_props": parsed["subject"].get("properties", {}),
                                    "rel_type": parsed["relation"],
                                    "rel_props": {"confidence": parsed.get("confidence", 0.5)},
                                    "to_label": parsed["object"].get("label", ""),
                                    "to_props": parsed["object"].get("properties", {}),
                                })
                                count += 1
                        except Exception:
                            pass  # 单条解析失败不影响其他
                    logger.info(f"[OntologyManager] Mock 图谱写入: {count} 条")
                    return count
                else:
                    # 非 mock 模式但真实写入失败
                    logger.warning("[OntologyManager] 无法写入 Mock 图谱")
                    return 0
        except Exception as e:
            logger.warning(f"[OntologyManager] Mock 图谱写入失败: {e}")
            return 0

    def _parse_merge_cypher(self, cypher: str) -> Optional[Dict[str, Any]]:
        """
        解析简单 MERGE 语句提取节点/关系信息。

        Args:
            cypher: MERGE Cypher 语句

        Returns:
            解析结果或 None
        """
        import re

        # MERGE (a:Label {name: 'xxx'}) MERGE (b:Label {name: 'yyy'}) MERGE (a)-[:REL]->(b)
        pattern = (
            r"MERGE\s*\(a:(\w+)\s*\{name:\s*'([^']*)'\}\)\s*"
            r"MERGE\s*\(b:(\w+)\s*\{name:\s*'([^']*)'\}\)\s*"
            r"MERGE\s*\(a\)-\[:(\w+)\s*\{confidence:\s*([\d.]+)\}\]->\(b\)"
        )
        match = re.search(pattern, cypher)
        if match:
            subj_label = match.group(1)
            subj_name = match.group(2)
            obj_label = match.group(3)
            obj_name = match.group(4)
            rel_type = match.group(5)
            confidence = float(match.group(6))

            return {
                "subject": {"label": subj_label, "properties": {"name": subj_name}},
                "object": {"label": obj_label, "properties": {"name": obj_name}},
                "relation": rel_type,
                "confidence": confidence,
            }
        return None

    def get_schema_summary(self) -> Dict[str, Any]:
        """获取当前 Schema 摘要。"""
        return self._schema.export_schema()
