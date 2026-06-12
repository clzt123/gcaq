"""
本体驱动图谱模块

实现技术方案功能 3 — 本体驱动图谱：
    1. LLM 实时三元组抽取（从文本中提取实体关系）
    2. 动态 Schema 更新机制
    3. Neo4j 图谱写入与验证

依赖: Neo4jClient (功能 4)、LLM (项目已有)
"""

from app.core.ontology.triplet_extractor import TripletExtractor, Triplet, ExtractionResult
from app.core.ontology.schema_manager import SchemaManager, NodeType, RelationType
from app.core.ontology.ontology_manager import OntologyManager

__all__ = [
    "TripletExtractor",
    "Triplet",
    "ExtractionResult",
    "SchemaManager",
    "NodeType",
    "RelationType",
    "OntologyManager",
]
