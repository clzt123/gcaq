"""
动态 Schema 管理器

实现技术方案功能 3 — 动态 Schema 更新机制。

管理 Neo4j 图谱中的节点类型、关系类型和属性约束。
支持运行时注册新的节点类型和关系类型。
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# =========================
# 数据模型
# =========================


@dataclass
class NodeType:
    """
    图谱节点类型定义。

    Attributes:
        label: 节点标签 (e.g., "Equipment", "Hazard")
        description: 中文描述
        required_properties: 必填属性列表
        optional_properties: 可选属性列表
        example: 示例实例
    """

    label: str
    description: str
    required_properties: List[str] = field(default_factory=list)
    optional_properties: List[str] = field(default_factory=list)
    example: str = ""


@dataclass
class RelationType:
    """
    图谱关系类型定义。

    Attributes:
        type_name: 关系类型名称 (e.g., "HAS_HAZARD")
        description: 中文描述
        from_labels: 允许的源节点标签
        to_labels: 允许的目标节点标签
        properties: 关系属性列表
    """

    type_name: str
    description: str
    from_labels: List[str] = field(default_factory=list)
    to_labels: List[str] = field(default_factory=list)
    properties: List[str] = field(default_factory=list)


# =========================
# Schema 管理器
# =========================


class SchemaManager:
    """
    动态 Schema 管理器。

    管理 Neo4j 图谱的本体定义，支持：
        1. 预定义节点和关系类型
        2. 运行时注册新的类型
        3. Schema 验证（检查三元组的类型有效性）
        4. Schema 导出/导入

    使用方式:
        mgr = SchemaManager()
        mgr.register_node("FireExtinguisher", "灭火器", required=["name", "location"])
        valid = mgr.validate_triplet(triplet)
    """

    # ---- 预定义 Node Types ----
    PREDEFINED_NODES = {
        "Equipment": NodeType(
            label="Equipment",
            description="设备/设施",
            required_properties=["name"],
            optional_properties=["model", "department", "location", "install_date"],
            example="3号注塑机",
        ),
        "Hazard": NodeType(
            label="Hazard",
            description="隐患/风险",
            required_properties=["name", "risk_level"],
            optional_properties=["category", "description", "detected_at"],
            example="液压油泄漏",
        ),
        "Regulation": NodeType(
            label="Regulation",
            description="法规/标准",
            required_properties=["name"],
            optional_properties=["clause", "version", "effective_date", "authority"],
            example="GB30871-2022",
        ),
        "SOP": NodeType(
            label="SOP",
            description="标准操作规程",
            required_properties=["name"],
            optional_properties=["doc_id", "version", "department", "effective_date"],
            example="动火作业SOP",
        ),
        "Employee": NodeType(
            label="Employee",
            description="员工",
            required_properties=["name"],
            optional_properties=["employee_id", "department", "position"],
            example="张建国",
        ),
        "Department": NodeType(
            label="Department",
            description="部门/区域",
            required_properties=["name"],
            optional_properties=["department_type", "risk_level"],
            example="生产部-焊接车间",
        ),
    }

    # ---- 预定义 Relation Types ----
    PREDEFINED_RELATIONS = {
        "HAS_HAZARD": RelationType(
            type_name="HAS_HAZARD",
            description="设备存在隐患",
            from_labels=["Equipment", "Department"],
            to_labels=["Hazard"],
            properties=["frequency", "last_occurrence", "severity"],
        ),
        "GOVERNED_BY": RelationType(
            type_name="GOVERNED_BY",
            description="受法规约束",
            from_labels=["Hazard", "Equipment", "Department"],
            to_labels=["Regulation"],
            properties=["compliance_status", "effective_date"],
        ),
        "MITIGATED_BY": RelationType(
            type_name="MITIGATED_BY",
            description="由SOP防范",
            from_labels=["Hazard"],
            to_labels=["SOP"],
            properties=["mitigation_type"],
        ),
        "INSPECTED_BY": RelationType(
            type_name="INSPECTED_BY",
            description="按流程巡检",
            from_labels=["Equipment", "Department"],
            to_labels=["SOP"],
            properties=["inspection_frequency", "last_inspection"],
        ),
        "APPLIES_TO": RelationType(
            type_name="APPLIES_TO",
            description="法规适用于",
            from_labels=["Regulation"],
            to_labels=["Equipment", "Department", "Hazard"],
            properties=["scope"],
        ),
        "RELATED_TO": RelationType(
            type_name="RELATED_TO",
            description="通用关联",
            from_labels=["*"],
            to_labels=["*"],
            properties=["note"],
        ),
        "ASSIGNED_TO": RelationType(
            type_name="ASSIGNED_TO",
            description="任务分配",
            from_labels=["Hazard"],
            to_labels=["Employee"],
            properties=["assigned_at", "deadline"],
        ),
        "LOCATED_IN": RelationType(
            type_name="LOCATED_IN",
            description="位于",
            from_labels=["Equipment", "Hazard", "Employee"],
            to_labels=["Department"],
            properties=[],
        ),
    }

    def __init__(self):
        """初始化 Schema 管理器，加载预定义类型。"""
        self._nodes: Dict[str, NodeType] = dict(self.PREDEFINED_NODES)
        self._relations: Dict[str, RelationType] = dict(self.PREDEFINED_RELATIONS)
        logger.info(
            f"[SchemaManager] 初始化: {len(self._nodes)} 种节点类型, "
            f"{len(self._relations)} 种关系类型"
        )

    # ---- 节点类型管理 ----

    def register_node(
        self,
        label: str,
        description: str,
        required: Optional[List[str]] = None,
        optional: Optional[List[str]] = None,
    ) -> NodeType:
        """
        注册新的节点类型（或更新已有类型）。

        Args:
            label: 节点标签
            description: 中文描述
            required: 必填属性
            optional: 可选属性

        Returns:
            NodeType 实例
        """
        node_type = NodeType(
            label=label,
            description=description,
            required_properties=required or ["name"],
            optional_properties=optional or [],
        )
        self._nodes[label] = node_type
        logger.info(f"[SchemaManager] 注册节点类型: {label} ({description})")
        return node_type

    def get_node_type(self, label: str) -> Optional[NodeType]:
        """获取节点类型定义。"""
        return self._nodes.get(label)

    def list_node_types(self) -> List[NodeType]:
        """列出所有节点类型。"""
        return list(self._nodes.values())

    def has_node_type(self, label: str) -> bool:
        """检查节点类型是否已注册。"""
        return label in self._nodes

    # ---- 关系类型管理 ----

    def register_relation(
        self,
        type_name: str,
        description: str,
        from_labels: Optional[List[str]] = None,
        to_labels: Optional[List[str]] = None,
    ) -> RelationType:
        """
        注册新的关系类型。

        Args:
            type_name: 关系类型名称
            description: 中文描述
            from_labels: 允许的源节点标签（["*"] 表示任意）
            to_labels: 允许的目标节点标签

        Returns:
            RelationType 实例
        """
        rel_type = RelationType(
            type_name=type_name,
            description=description,
            from_labels=from_labels or ["*"],
            to_labels=to_labels or ["*"],
        )
        self._relations[type_name] = rel_type
        logger.info(f"[SchemaManager] 注册关系类型: {type_name} ({description})")
        return rel_type

    def get_relation_type(self, type_name: str) -> Optional[RelationType]:
        """获取关系类型定义。"""
        return self._relations.get(type_name)

    def list_relation_types(self) -> List[RelationType]:
        """列出所有关系类型。"""
        return list(self._relations.values())

    def has_relation_type(self, type_name: str) -> bool:
        """检查关系类型是否已注册。"""
        return type_name in self._relations

    # ---- Schema 验证 ----

    def validate_triplet(
        self,
        subject_type: str,
        relation: str,
        object_type: str,
    ) -> tuple[bool, str]:
        """
        验证三元组的类型合法性。

        Args:
            subject_type: 主体节点类型
            relation: 关系类型
            object_type: 客体节点类型

        Returns:
            (is_valid, reason) 元组
        """
        # 检查关系类型是否存在
        if relation not in self._relations:
            return False, f"未定义的关系类型: '{relation}'"

        rel_def = self._relations[relation]

        # 检查源类型
        if "*" not in rel_def.from_labels and subject_type not in rel_def.from_labels:
            return False, (
                f"关系 '{relation}' 不允许源类型 '{subject_type}'，"
                f"允许: {rel_def.from_labels}"
            )

        # 检查目标类型
        if "*" not in rel_def.to_labels and object_type not in rel_def.to_labels:
            return False, (
                f"关系 '{relation}' 不允许目标类型 '{object_type}'，"
                f"允许: {rel_def.to_labels}"
            )

        return True, "验证通过"

    def ensure_relation_type(self, relation: str) -> RelationType:
        """
        确保关系类型存在，不存在则自动注册。

        这是动态 Schema 更新的核心机制：
        当 LLM 抽取到预定义外的新关系类型时，自动注册它。

        Args:
            relation: 关系类型名称

        Returns:
            RelationType 实例
        """
        if relation not in self._relations:
            logger.info(f"[SchemaManager] 自动注册新关系类型: {relation}")
            self._relations[relation] = RelationType(
                type_name=relation,
                description=f"自动注册: {relation}",
                from_labels=["*"],
                to_labels=["*"],
            )
        return self._relations[relation]

    # ---- 导出 ----

    def export_schema(self) -> Dict[str, Any]:
        """
        导出当前 Schema 定义（可序列化格式）。

        Returns:
            dict: 包含 nodes 和 relations 的完整 Schema
        """
        return {
            "nodes": {
                label: {
                    "label": nt.label,
                    "description": nt.description,
                    "required_properties": nt.required_properties,
                    "optional_properties": nt.optional_properties,
                }
                for label, nt in self._nodes.items()
            },
            "relations": {
                name: {
                    "type_name": rt.type_name,
                    "description": rt.description,
                    "from_labels": rt.from_labels,
                    "to_labels": rt.to_labels,
                }
                for name, rt in self._relations.items()
            },
        }
