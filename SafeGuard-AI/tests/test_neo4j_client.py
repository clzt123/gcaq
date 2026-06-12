"""
Neo4j 客户端单元测试

覆盖:
    - Mock 图谱解析（Cypher 语句 → 内存图谱）
    - 基本查询模式（MATCH/RETURN/WHERE）
    - 高级查询（实体查找、关联查询、关键词搜索）
    - 优雅降级（真实 Neo4j 不可用时自动 Mock）

测试策略:
    - 全部使用 Mock 模式（无需安装 Neo4j）
    - 覆盖所有支持的 Cypher 查询模式
"""
import pytest

from app.core.rag.neo4j_client import Neo4jClient, _MockGraph


# =========================
# Fixtures
# =========================


@pytest.fixture
def mock_graph():
    """创建 Mock 图谱实例（解析 init_graph.cypher）。"""
    return _MockGraph()


@pytest.fixture
async def neo4j_client():
    """创建 Mock 模式的 Neo4j 客户端。"""
    client = Neo4jClient(use_mock=True)
    await client._ensure_connected()
    yield client
    await client.close()


# =========================
# MockGraph 测试
# =========================


class TestMockGraphParsing:
    """测试 Mock 图谱的 Cypher 解析"""

    def test_graph_has_nodes(self, mock_graph):
        """解析后应有节点"""
        assert len(mock_graph.nodes) > 0, "图谱应有节点"

    def test_graph_has_edges(self, mock_graph):
        """解析后应有关系"""
        assert len(mock_graph.edges) > 0, "图谱应有关系"

    def test_node_labels(self, mock_graph):
        """应包含四种标签类型"""
        labels = mock_graph.get_all_labels()
        for expected in ("Equipment", "Hazard", "Regulation", "SOP"):
            assert expected in labels, f"缺少标签: {expected}"

    def test_relation_types(self, mock_graph):
        """应包含三种关系类型"""
        rels = mock_graph.get_all_relation_types()
        for expected in ("HAS_HAZARD", "GOVERNED_BY", "MITIGATED_BY"):
            assert expected in rels, f"缺少关系类型: {expected}"

    def test_node_count(self, mock_graph):
        """节点数应 >= 11 (4 Equipment + 4 Hazard + 4 Regulation + 2 SOP)"""
        assert len(mock_graph.nodes) >= 11, (
            f"预期至少 11 个节点，实际 {len(mock_graph.nodes)}"
        )

    def test_edge_count(self, mock_graph):
        """边数应 >= 8"""
        assert len(mock_graph.edges) >= 8, (
            f"预期至少 8 条边，实际 {len(mock_graph.edges)}"
        )


class TestMockGraphQueries:
    """测试 Mock 图谱的 Cypher 查询"""

    def test_match_all_equipment(self, mock_graph):
        """MATCH (n:Equipment) RETURN n"""
        results = mock_graph.run("MATCH (n:Equipment) RETURN n")
        assert len(results) >= 4, f"应至少有 4 台设备，实际 {len(results)}"

    def test_match_all_hazards(self, mock_graph):
        """MATCH (n:Hazard) RETURN n"""
        results = mock_graph.run("MATCH (n:Hazard) RETURN n")
        assert len(results) >= 4, f"应至少有 4 种隐患，实际 {len(results)}"

    def test_match_entity_by_name(self, mock_graph):
        """MATCH (n:Equipment {name: "3号注塑机"}) RETURN n"""
        results = mock_graph.run(
            'MATCH (n:Equipment {name: "3号注塑机"}) RETURN n'
        )
        assert len(results) == 1
        node = results[0]["n"]
        assert node["name"] == "3号注塑机"
        assert node["model"] == "HT-250T"

    def test_match_where_clause(self, mock_graph):
        """MATCH (n:Hazard) WHERE n.risk_level = "Critical" RETURN n"""
        results = mock_graph.run(
            'MATCH (n:Hazard) WHERE n.risk_level = "Critical" RETURN n'
        )
        assert len(results) >= 1
        assert results[0]["n"]["name"] == "初期火灾/烟雾异常"

    def test_match_relationship(self, mock_graph):
        """MATCH (a:Equipment)-[r:HAS_HAZARD]->(b:Hazard) RETURN a, r, b"""
        results = mock_graph.run(
            "MATCH (a:Equipment)-[r:HAS_HAZARD]->(b:Hazard) RETURN a, r, b"
        )
        assert len(results) >= 4

    def test_match_all_edges(self, mock_graph):
        """MATCH (a)-[r]->(b) RETURN a, r, b"""
        results = mock_graph.run("MATCH (a)-[r]->(b) RETURN a, r, b")
        assert len(results) >= 8

    def test_unsupported_query_returns_empty(self, mock_graph):
        """不支持的复杂查询返回空列表，不抛出异常"""
        results = mock_graph.run("MATCH (a)-[*2..3]->(b) RETURN a, b")
        assert results == []


# =========================
# Neo4jClient Mock 模式测试
# =========================


class TestNeo4jClientMock:
    """测试 Neo4jClient 在 Mock 模式下的行为"""

    @pytest.mark.asyncio
    async def test_client_initializes_mock(self, neo4j_client):
        """客户端应成功初始化 Mock 模式"""
        assert neo4j_client.is_mock is True

    @pytest.mark.asyncio
    async def test_run_cypher(self, neo4j_client):
        """run() 方法应执行 Cypher 并返回结果"""
        results = await neo4j_client.run("MATCH (n:Hazard) RETURN n")
        assert len(results) >= 4

    @pytest.mark.asyncio
    async def test_get_entity_by_name_found(self, neo4j_client):
        """按名称查找存在实体"""
        result = await neo4j_client.get_entity_by_name(
            "Equipment", "3号注塑机"
        )
        assert result is not None
        assert result["name"] == "3号注塑机"

    @pytest.mark.asyncio
    async def test_get_entity_by_name_not_found(self, neo4j_client):
        """按名称查找不存在实体"""
        result = await neo4j_client.get_entity_by_name(
            "Equipment", "不存在的设备"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_get_related_entities(self, neo4j_client):
        """查询关联实体"""
        results = await neo4j_client.get_related_entities(
            from_label="Equipment",
            from_name="3号注塑机",
            rel_type="HAS_HAZARD",
            to_label="Hazard",
        )
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_get_governing_laws(self, neo4j_client):
        """查询隐患的适用法规"""
        results = await neo4j_client.get_governing_laws("液压油泄漏")
        assert len(results) >= 1
        assert "企业安全生产标准化基本规范" in results[0].get("name", "")

    @pytest.mark.asyncio
    async def test_get_mitigation_sops(self, neo4j_client):
        """查询隐患的应急处置 SOP"""
        results = await neo4j_client.get_mitigation_sops("液压油泄漏")
        assert len(results) >= 1
        assert "SOP" in results[0].get("doc_id", "")

    @pytest.mark.asyncio
    async def test_get_equipment_hazards(self, neo4j_client):
        """查询设备的关联隐患"""
        results = await neo4j_client.get_equipment_hazards("3号注塑机")
        assert len(results) >= 1
        h = results[0].get("h", {})
        assert "液压油泄漏" in h.get("name", "")

    @pytest.mark.asyncio
    async def test_search_by_keyword(self, neo4j_client):
        """关键词搜索"""
        results = await neo4j_client.search_by_keyword("泄漏")
        assert len(results) >= 1
        # 应找到与"泄漏"相关的节点
        found = False
        for r in results:
            if "泄漏" in str(r.get("properties", {})):
                found = True
                break
        assert found, f"应找到含'泄漏'的结果: {results}"

    @pytest.mark.asyncio
    async def test_search_by_keyword_no_match(self, neo4j_client):
        """无匹配关键词"""
        results = await neo4j_client.search_by_keyword("XYZ不存在的关键词123")
        assert results == []

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """async with 语法"""
        async with Neo4jClient(use_mock=True) as client:
            assert client.is_mock is True
            results = await client.run("MATCH (n:Equipment) RETURN n")
            assert len(results) >= 4

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_bad_cypher(self, neo4j_client):
        """错误 Cypher 返回空列表，不抛异常"""
        results = await neo4j_client.run("INVALID CYPHER SYNTAX !!!")
        assert isinstance(results, list)
