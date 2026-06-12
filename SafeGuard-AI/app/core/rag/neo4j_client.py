"""
Neo4j 图数据库客户端

提供异步 Neo4j 连接管理、Cypher 查询执行和 Mock 模式（开发阶段无需真实 Neo4j）。

设计模式参考:
    - Base/Client/neo4jClient.py 的连接管理与 CRUD 封装模式
    - Base/Repository/base/baseConnection.py 的可用性标记与优雅降级
    - 按 CLAUDE.md 要求: async/await 优先、logging 替代 print

Mock 模式:
    当 Neo4j 不可用或配置为 mock 时，自动解析 mock_data/init_graph.cypher
    构建内存图谱，支持基本的 MATCH 查询模式。
"""
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.utils import get_mock_path

logger = logging.getLogger(__name__)

# =========================
# Mock 内存图谱
# =========================


class _MockGraph:
    """
    内存图谱（Mock 模式使用）。

    解析 init_graph.cypher 中的 CREATE 语句，构建节点和关系索引，
    支持基本的 MATCH 查询模式。
    """

    def __init__(self, cypher_file: Optional[Path] = None):
        """
        初始化内存图谱。

        Args:
            cypher_file: Cypher 初始化脚本路径，None 时使用默认 mock_data/init_graph.cypher

        Raises:
            FileNotFoundError: Cypher 文件不存在
        """
        self._nodes: List[Dict[str, Any]] = []    # [{label, properties}]
        self._edges: List[Dict[str, Any]] = []    # [{from_label, from_props, rel_type, rel_props, to_label, to_props}]

        if cypher_file is None:
            cypher_file = get_mock_path("init_graph.cypher")

        if not cypher_file.exists():
            raise FileNotFoundError(f"Mock Cypher 文件不存在: {cypher_file}")

        self._parse_cypher_file(cypher_file)
        logger.info(
            f"Mock 图谱已初始化: {len(self._nodes)} 个节点, {len(self._edges)} 条关系"
        )

    # ---- 解析 ----

    def _parse_cypher_file(self, filepath: Path) -> None:
        """
        解析 Cypher 文件，提取所有 CREATE 语句。

        支持两种分隔方式：
            - 分号分隔（标准 Cypher）
            - 换行分隔（init_graph.cypher 实际格式）
        """
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # 移除注释
        content = re.sub(r"//.*$", "", content, flags=re.MULTILINE)

        # 先尝试按分号分割，若只有一条则按 CREATE 关键字分割
        semicolon_parts = [s.strip() for s in content.split(";") if s.strip()]
        if len(semicolon_parts) <= 1:
            # 按 CREATE 关键字拆分（保留 CREATE 前缀）
            raw_parts = re.split(r"\n\s*(?=CREATE\s)", content)
        else:
            raw_parts = semicolon_parts

        var_to_label: Dict[str, str] = {}
        var_to_props: Dict[str, Dict[str, Any]] = {}

        for raw in raw_parts:
            stmt = " ".join(raw.split())  # 压缩空白
            if not stmt.upper().startswith("CREATE"):
                continue

            # 尝试匹配: CREATE (var:Label {props})
            node_match = re.match(
                r"CREATE\s+\((\w+):(\w+)\s*(\{.*\})\)", stmt, re.DOTALL
            )
            if node_match:
                var = node_match.group(1)
                label = node_match.group(2)
                props_str = node_match.group(3)
                props = self._parse_props(props_str)
                var_to_label[var] = label
                var_to_props[var] = props
                self._nodes.append({"label": label, "properties": props})
                continue

            # 尝试匹配: CREATE (var)-[:REL_TYPE {props}]->(var2)
            edge_match = re.match(
                r"CREATE\s+\((\w+)\)-\[:(\w+)\s*(\{.*?\})?\]->\((\w+)\)",
                stmt, re.DOTALL,
            )
            if edge_match:
                from_var = edge_match.group(1)
                rel_type = edge_match.group(2)
                rel_props_str = edge_match.group(3)
                to_var = edge_match.group(4)

                rel_props = self._parse_props(rel_props_str) if rel_props_str else {}
                from_label = var_to_label.get(from_var, from_var)
                from_props = var_to_props.get(from_var, {})
                to_label = var_to_label.get(to_var, to_var)
                to_props = var_to_props.get(to_var, {})

                self._edges.append({
                    "from_label": from_label,
                    "from_props": from_props,
                    "rel_type": rel_type,
                    "rel_props": rel_props,
                    "to_label": to_label,
                    "to_props": to_props,
                })
                continue

            # 多关系: CREATE (a)-[:R1]->(b), (b)-[:R2]->(c) — 简化为忽略
            if "), (" in stmt or ")->" not in stmt:
                logger.debug(f"Mock: 跳过复杂语句: {stmt[:60]}...")
                continue

    @staticmethod
    def _parse_props(props_str: str) -> Dict[str, Any]:
        """
        解析 Cypher 属性字符串为 dict。

        支持格式: {key: "value", key2: 123}
        注：简化解析，不处理嵌套。
        """
        if not props_str or not props_str.strip():
            return {}
        props_str = props_str.strip().strip("{}").strip()
        if not props_str:
            return {}

        result: Dict[str, Any] = {}
        # 匹配 key: value 对
        pairs = re.findall(
            r'(\w+):\s*("(?:[^"\\]|\\.)*"|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false)',
            props_str,
        )
        for key, val in pairs:
            val = val.strip()
            if val.startswith('"') and val.endswith('"'):
                result[key] = val[1:-1]
            elif val.lower() == "true":
                result[key] = True
            elif val.lower() == "false":
                result[key] = False
            elif "." in val or "e" in val.lower():
                result[key] = float(val)
            else:
                result[key] = int(val)
        return result

    # ---- 查询 ----

    def run(self, cypher: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        执行简化 Cypher 查询，返回结果列表。

        支持的查询模式:
            - MATCH (n:Label) RETURN n
            - MATCH (n:Label) WHERE n.key = value RETURN n
            - MATCH (n:Label {key: value}) RETURN n
            - MATCH (a:Label1)-[r:REL_TYPE]->(b:Label2) RETURN a, r, b
            - MATCH (a)-[r]->(b) RETURN a, r, b

        Args:
            cypher: Cypher 查询语句
            parameters: 查询参数

        Returns:
            结果列表，每项为 dict
        """
        params = parameters or {}
        cypher_norm = " ".join(cypher.split()).strip()

        # 参数替换：将 $param_name 替换为字面值（Mock 模式下模拟 Neo4j 参数绑定）
        for key, val in params.items():
            if isinstance(val, str):
                cypher_norm = cypher_norm.replace(f"${key}", f'"{val}"')
            else:
                cypher_norm = cypher_norm.replace(f"${key}", str(val))

        # --- 模式 1: MATCH (var:Label) RETURN var ---
        m = re.match(
            r"MATCH\s+\((\w+)\s*:\s*(\w+)\)\s*RETURN\s+\1(?:\s+LIMIT\s+(\d+))?",
            cypher_norm, re.IGNORECASE,
        )
        if m:
            var = m.group(1)
            label = m.group(2)
            limit = int(m.group(3)) if m.group(3) else None
            results = [{"n": n["properties"]} for n in self._nodes if n["label"] == label]
            return results[:limit] if limit else results

        # --- 模式 2: MATCH (var:Label {key: val}) RETURN var ---
        m = re.match(
            r"MATCH\s+\((\w+):(\w+)\s*\{(\w+):\s*\"([^\"]+)\"\}\)\s*RETURN\s+\1",
            cypher_norm, re.IGNORECASE,
        )
        if m:
            var = m.group(1)
            label = m.group(2)
            key = m.group(3)
            value = m.group(4)
            results = [
                {"n": n["properties"]}
                for n in self._nodes
                if n["label"] == label and n["properties"].get(key) == value
            ]
            return results

        # --- 模式 3: MATCH (var:Label) WHERE var.key = "value" RETURN var ---
        m = re.match(
            r"MATCH\s+\((\w+):(\w+)\)\s*WHERE\s+\1\.(\w+)\s*=\s*\"([^\"]+)\"\s*RETURN\s+\1",
            cypher_norm, re.IGNORECASE,
        )
        if m:
            var = m.group(1)
            label = m.group(2)
            key = m.group(3)
            value = m.group(4)
            results = [
                {"n": n["properties"]}
                for n in self._nodes
                if n["label"] == label and n["properties"].get(key) == value
            ]
            return results

        # --- 模式 4: MATCH (a:Label1)-[r:REL_TYPE]->(b:Label2) RETURN a, r, b ---
        m = re.match(
            r"MATCH\s+\((\w+):(\w+)\)-\[(\w+):(\w+)\]->\((\w+):(\w+)\)\s*RETURN\s+\1,\s*\3,\s*\5",
            cypher_norm, re.IGNORECASE,
        )
        if m:
            a_var, a_label, r_var, rel_type, b_var, b_label = m.groups()
            results = [
                {"a": e["from_props"], "r": e["rel_props"], "b": e["to_props"]}
                for e in self._edges
                if e["from_label"] == a_label
                and e["rel_type"] == rel_type
                and e["to_label"] == b_label
            ]
            return results

        # --- 模式 5: MATCH (a)-[r]->(b) RETURN a, r, b (全图谱) ---
        m = re.match(
            r"MATCH\s+\((\w+)\)-\[(\w+)\]->\((\w+)\)\s*RETURN\s+\1,\s*\2,\s*\3(?:\s+LIMIT\s+(\d+))?",
            cypher_norm, re.IGNORECASE,
        )
        if m:
            limit = int(m.group(4)) if m.group(4) else None
            results = [
                {"a": e["from_props"], "r": e["rel_props"], "b": e["to_props"]}
                for e in self._edges
            ]
            return results[:limit] if limit else results

        # --- 模式 6: MATCH (var:Label) RETURN var.key ---
        m = re.match(
            r"MATCH\s+\((\w+):(\w+)\)\s*RETURN\s+\1\.(\w+)",
            cypher_norm, re.IGNORECASE,
        )
        if m:
            var = m.group(1)
            label = m.group(2)
            key = m.group(3)
            results = [
                {key: n["properties"].get(key)}
                for n in self._nodes
                if n["label"] == label and key in n["properties"]
            ]
            return results

        # --- 模式 7a: MATCH (a:Label {key: "val"})-[:REL]->(b:Label2) RETURN b (无关系变量) ---
        m = re.match(
            r"MATCH\s+\((\w+):(\w+)\s*\{(\w+):\s*\"([^\"]+)\"\}\)"
            r"-\[:(\w+)\]->\((\w+):(\w+)\)\s*RETURN\s+\6",
            cypher_norm, re.IGNORECASE,
        )
        if m:
            a_var, a_label, a_key, a_val = m.group(1), m.group(2), m.group(3), m.group(4)
            rel_type = m.group(5)
            b_var, b_label = m.group(6), m.group(7)
            edges = self._query_edges_by_source(a_label, a_key, a_val, rel_type, b_label)
            return [{b_var: e["to_props"]} for e in edges]

        # --- 模式 7b: MATCH (a:Label {key: "val"})-[r:REL]->(b:Label2) RETURN b ---
        m = re.match(
            r"MATCH\s+\((\w+):(\w+)\s*\{(\w+):\s*\"([^\"]+)\"\}\)"
            r"-\[(\w+):(\w+)\]->\((\w+):(\w+)\)\s*RETURN\s+\7",
            cypher_norm, re.IGNORECASE,
        )
        if m:
            a_var, a_label, a_key, a_val = m.group(1), m.group(2), m.group(3), m.group(4)
            r_var, rel_type, b_var, b_label = m.group(5), m.group(6), m.group(7), m.group(8)
            edges = self._query_edges_by_source(a_label, a_key, a_val, rel_type, b_label)
            return [{b_var: e["to_props"]} for e in edges]

        # --- 模式 8: MATCH (a:Label {key: "val"})-[r:REL]->(b:Label2) RETURN h, r ---
        m = re.match(
            r"MATCH\s+\((\w+):(\w+)\s*\{(\w+):\s*\"([^\"]+)\"\}\)"
            r"-\[(\w+):(\w+)\]->\((\w+):(\w+)\)\s*RETURN\s+\7,\s*\5",
            cypher_norm, re.IGNORECASE,
        )
        if m:
            a_var, a_label, a_key, a_val = m.group(1), m.group(2), m.group(3), m.group(4)
            r_var, rel_type, b_var, b_label = m.group(5), m.group(6), m.group(7), m.group(8)
            edges = self._query_edges_by_source(a_label, a_key, a_val, rel_type, b_label)
            return [{b_var: e["to_props"], r_var: e["rel_props"]} for e in edges]

        # --- 模式 9: MATCH (a:Label {key: "val"})-[r:REL]->(b:Label2) RETURN a, r, b ---
        m = re.match(
            r"MATCH\s+\((\w+):(\w+)\s*\{(\w+):\s*\"([^\"]+)\"\}\)"
            r"-\[(\w+):(\w+)\]->\((\w+):(\w+)\)\s*RETURN\s+\1,\s*\5,\s*\7",
            cypher_norm, re.IGNORECASE,
        )
        if m:
            a_var, a_label, a_key, a_val = m.group(1), m.group(2), m.group(3), m.group(4)
            r_var, rel_type, b_var, b_label = m.group(5), m.group(6), m.group(7), m.group(8)
            edges = self._query_edges_by_source(a_label, a_key, a_val, rel_type, b_label)
            return [{a_var: e["from_props"], r_var: e["rel_props"], b_var: e["to_props"]} for e in edges]

        logger.warning(f"Mock: 不支持的 Cypher 查询模式: {cypher_norm[:80]}...")
        return []

    def _query_edges_by_source(
        self, from_label: str, from_key: str, from_val: str,
        rel_type: str, to_label: str,
    ) -> List[Dict[str, Any]]:
        """
        按来源节点属性查询匹配的边（消除模式 7a-9 中重复的过滤逻辑）。

        Args:
            from_label: 来源节点标签
            from_key: 来源节点属性键
            from_val: 来源节点属性值
            rel_type: 关系类型
            to_label: 目标节点标签

        Returns:
            匹配的边列表
        """
        return [
            e for e in self._edges
            if (e["from_label"] == from_label
                and e["from_props"].get(from_key) == from_val
                and e["rel_type"] == rel_type
                and e["to_label"] == to_label)
        ]

    @property
    def nodes(self) -> List[Dict[str, Any]]:
        """节点列表（用于调用方遍历）"""
        return list(self._nodes)

    @property
    def edges(self) -> List[Dict[str, Any]]:
        """边列表（用于调用方遍历）"""
        return list(self._edges)

    def get_all_labels(self) -> List[str]:
        """获取图谱中所有标签类型"""
        return sorted(set(n["label"] for n in self._nodes))

    def get_all_relation_types(self) -> List[str]:
        """获取图谱中所有关系类型"""
        return sorted(set(e["rel_type"] for e in self._edges))


# =========================
# Neo4j 客户端
# =========================


class Neo4jClient:
    """
    Neo4j 图数据库异步客户端。

    封装连接管理、Cypher 执行、实体关系查询。
    当 Neo4j 不可用时自动降级为 Mock 内存图谱。

    使用方式:
        async with Neo4jClient() as client:
            results = await client.run("MATCH (n:Equipment) RETURN n")
    """

    def __init__(self, use_mock: Optional[bool] = None):
        """
        初始化 Neo4j 客户端。

        Args:
            use_mock: 是否强制使用 Mock 模式。
                      None 时读取配置 NEO4J_USE_MOCK（默认 True，开发环境零延迟）。
                      显式传入 True/False 时覆盖配置。
        """
        settings = get_settings()
        self._uri = settings.neo4j.uri
        self._user = settings.neo4j.user
        self._password = settings.neo4j.password
        self._database = settings.neo4j.database
        self._driver = None
        self._mock_graph: Optional[_MockGraph] = None

        # 模式判定：参数优先 → 配置 fallback（默认 Mock，消除 auto-detect 延迟）
        if use_mock is not None:
            self._mock_mode = use_mock
        else:
            self._mock_mode = settings.neo4j.use_mock

        logger.info(
            f"Neo4jClient 已初始化: uri={self._uri}, mock={self._mock_mode}"
        )

    # ---- 连接管理 ----

    async def _ensure_connected(self) -> None:
        """确保客户端处于可用状态（自动降级）。"""
        if self._mock_mode:
            if self._mock_graph is None:
                self._mock_graph = _MockGraph()
            return

        if self._driver is not None:
            return

        try:
            from neo4j import AsyncGraphDatabase

            self._driver = AsyncGraphDatabase.driver(
                self._uri, auth=(self._user, self._password)
            )
            # 验证连接
            async with self._driver.session(database=self._database) as session:
                await session.run("RETURN 1")
            logger.info(f"Neo4j 连接成功: {self._uri}")
        except Exception as e:
            logger.warning(
                f"Neo4j 连接失败 ({e})，自动降级为 Mock 模式"
            )
            # 清理可能已部分创建的驱动对象，防止资源泄漏
            if self._driver:
                await self._driver.close()
                self._driver = None
            self._mock_mode = True
            if self._mock_graph is None:
                self._mock_graph = _MockGraph()

    async def close(self) -> None:
        """关闭驱动连接。"""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Neo4j 连接已关闭")

    async def __aenter__(self) -> "Neo4jClient":
        await self._ensure_connected()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    # ---- 查询执行 ----

    async def run(
        self,
        cypher: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        执行 Cypher 查询并返回结果列表。

        Args:
            cypher: Cypher 查询语句
            parameters: 查询参数

        Returns:
            结果列表，查询失败时返回空列表（优雅降级）
        """
        await self._ensure_connected()

        if self._mock_mode and self._mock_graph:
            logger.debug(f"[Neo4j Mock] 执行: {cypher[:80]}...")
            return self._mock_graph.run(cypher, parameters)

        try:
            async with self._driver.session(database=self._database) as session:
                result = await session.run(cypher, parameters or {})
                records = [record.data() async for record in result]
                logger.debug(f"[Neo4j] 查询返回 {len(records)} 条")
                return records
        except Exception as e:
            logger.error(
                f"[Neo4j] Cypher 执行失败: {e}\n  query: {cypher[:120]}",
                exc_info=True,
            )
            return []  # 优雅降级

    # ---- 高级查询 ----

    async def get_entity_by_name(
        self, label: str, name: str
    ) -> Optional[Dict[str, Any]]:
        """
        按名称查找实体节点。

        Args:
            label: 节点标签 (e.g., "Hazard", "Equipment")
            name: 实体名称

        Returns:
            节点属性字典，未找到返回 None
        """
        cypher = f"MATCH (n:{label} {{name: $name}}) RETURN n"
        results = await self.run(cypher, {"name": name})
        return results[0]["n"] if results else None

    async def get_related_entities(
        self,
        from_label: str,
        from_name: str,
        rel_type: Optional[str] = None,
        to_label: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        查询与指定实体关联的其他实体。

        Args:
            from_label: 起始节点标签
            from_name: 起始节点名称
            rel_type: 关系类型过滤（None 表示任意）
            to_label: 目标节点标签过滤（None 表示任意）

        Returns:
            关联实体列表 [(relation, target_node), ...]
        """
        rel_pattern = f":{rel_type}" if rel_type else ""
        to_pattern = f":{to_label}" if to_label else ""
        cypher = (
            f"MATCH (a:{from_label} {{name: $from_name}})"
            f"-[r{rel_pattern}]->(b{to_pattern})"
            f"RETURN a, r, b"
        )
        return await self.run(cypher, {"from_name": from_name})

    async def get_governing_laws(
        self, hazard_name: str
    ) -> List[Dict[str, Any]]:
        """
        查询指定隐患的适用法规。

        Args:
            hazard_name: 隐患名称

        Returns:
            法规节点列表
        """
        cypher = (
            f"MATCH (h:Hazard {{name: $hazard_name}})"
            f"-[:GOVERNED_BY]->(r:Regulation) RETURN r"
        )
        results = await self.run(cypher, {"hazard_name": hazard_name})
        return [r["r"] for r in results]

    async def get_mitigation_sops(
        self, hazard_name: str
    ) -> List[Dict[str, Any]]:
        """
        查询指定隐患的应急处置 SOP。

        Args:
            hazard_name: 隐患名称

        Returns:
            SOP 节点列表
        """
        cypher = (
            f"MATCH (h:Hazard {{name: $hazard_name}})"
            f"-[:MITIGATED_BY]->(s:SOP) RETURN s"
        )
        results = await self.run(cypher, {"hazard_name": hazard_name})
        return [s["s"] for s in results]

    async def get_equipment_hazards(
        self, equipment_name: str
    ) -> List[Dict[str, Any]]:
        """
        查询指定设备关联的隐患。

        Args:
            equipment_name: 设备名称

        Returns:
            隐患节点列表（含关系属性）
        """
        cypher = (
            f"MATCH (e:Equipment {{name: $equipment_name}})"
            f"-[r:HAS_HAZARD]->(h:Hazard) RETURN h, r"
        )
        return await self.run(cypher, {"equipment_name": equipment_name})

    @staticmethod
    def _tokenize(keyword: str) -> List[str]:
        """
        将长查询文本拆分为可搜索的关键词片段。

        策略：
            1. 按空格/标点分词（中文无空格则保留完整词组）
            2. 过滤过短（≤1 字符）和过长（>10 字符）的片段
            3. 去重，保留最有区分度的前 10 个词

        这样 "油渍泄漏 化学品泄漏 液压油 切削液..." 会被拆成
        ["油渍泄漏", "化学品泄漏", "液压油", "切削液", ...]，逐个匹配。

        Args:
            keyword: 原始查询字符串

        Returns:
            去重后的关键词列表
        """
        import re

        # 按空格 / 中文标点 / 英文标点拆分
        raw_tokens = re.split(r"[\s，。！？、：；""''（）,!?.]+", keyword)
        # 过滤无效 token
        tokens = [t.strip() for t in raw_tokens if 2 <= len(t.strip()) <= 10]
        # 去重保序
        seen: set = set()
        unique: List[str] = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        # 最多取前 10 个高价值词
        return unique[:10]

    async def search_by_keyword(
        self, keyword: str, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        关键词模糊搜索（遍历所有节点）。

        支持长查询文本：自动拆分为独立关键词，对每个词做子串匹配，
        匹配任意一个关键词即返回该节点。

        Args:
            keyword: 搜索关键词（支持长文本，自动分词）
            top_k: 返回数量上限

        Returns:
            匹配的节点列表
        """
        tokens = self._tokenize(keyword)
        if not tokens:
            return []

        results: List[Dict[str, Any]] = []  # 类型注解避免重复初始化警告
        seen_labels: set = set()  # 按 (label, name) 去重

        if self._mock_mode and self._mock_graph:
            for node in self._mock_graph.nodes:
                props = node["properties"]
                for val in props.values():
                    if not isinstance(val, str):
                        continue
                    # 任意一个 token 匹配即视为命中
                    if any(t in val or val in t for t in tokens):
                        node_key = (node["label"], props.get("name", str(props)))
                        if node_key not in seen_labels:
                            seen_labels.add(node_key)
                            results.append({
                                "label": node["label"],
                                "properties": props,
                                "match_field": [k for k, v in props.items()
                                                if isinstance(v, str) and any(t in v or v in t for t in tokens)],
                            })
                        break
        else:
            # 真实 Neo4j：对每个 token 做 OR 匹配
            for label in ["Equipment", "Hazard", "Regulation", "SOP"]:
                # 构建 OR 链: CONTAINS $t0 OR CONTAINS $t1 OR ...
                or_clauses = " OR ".join(
                    f"toString(n[k]) CONTAINS $t{i}" for i in range(len(tokens))
                )
                cypher = (
                    f"MATCH (n:{label}) "
                    f"WHERE any(k in keys(n) WHERE {or_clauses}) "
                    f"RETURN n LIMIT $limit"
                )
                params = {f"t{i}": t for i, t in enumerate(tokens)}
                params["limit"] = top_k
                rows = await self.run(cypher, params)
                for row in rows:
                    node = row.get("n", row)
                    if isinstance(node, dict):
                        nk = (label, node.get("name", str(node)))
                        if nk not in seen_labels:
                            seen_labels.add(nk)
                            results.append({"label": label, "properties": node})

        return results[:top_k]

    @property
    def is_mock(self) -> bool:
        """是否运行在 Mock 模式。"""
        return self._mock_mode


# =========================
# 便捷工厂函数
# =========================


async def create_neo4j_client(
    use_mock: Optional[bool] = None,
) -> Neo4jClient:
    """
    创建并连接 Neo4j 客户端。

    Args:
        use_mock: 是否强制 Mock 模式

    Returns:
        已连接的 Neo4jClient 实例
    """
    client = Neo4jClient(use_mock=use_mock)
    await client._ensure_connected()
    return client
