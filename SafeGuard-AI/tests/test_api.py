"""
API 端到端集成测试

使用 FastAPI TestClient 验证全部 HTTP 接口：
    - GET  /health
    - GET  /api/v1/hazard/alerts
    - GET  /api/v1/hazard/alerts/{alert_id}
    - POST /api/v1/hazard/analyze (high/medium/low/unknown 四种场景)

测试策略:
    - TestClient 无需启动真实服务器
    - 全部 Mock 模式（无 LLM/Neo4j 依赖）
    - client fixture 支持 pytest-xdist 并行
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """模块级 TestClient fixture，支持并行测试。"""
    return TestClient(app)


# =========================
# 健康检查
# =========================


class TestHealthCheck:
    """测试 /health 端点"""

    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_body(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"
        assert data["app"] == "SafeGuard-AI"
        assert "version" in data
        assert "timestamp" in data


# =========================
# 告警列表 & 详情
# =========================


class TestAlertsAPI:
    """测试 GET /api/v1/hazard/alerts 系列接口"""

    def test_list_alerts_returns_200(self, client):
        response = client.get("/api/v1/hazard/alerts")
        assert response.status_code == 200

    def test_list_alerts_has_data(self, client):
        response = client.get("/api/v1/hazard/alerts")
        data = response.json()
        assert "total" in data
        assert "alerts" in data
        assert data["total"] >= 4  # Mock 数据有 4 条

    def test_list_alerts_limit(self, client):
        response = client.get("/api/v1/hazard/alerts?limit=2")
        data = response.json()
        assert len(data["alerts"]) <= 2

    def test_get_alert_by_id_found(self, client):
        response = client.get("/api/v1/hazard/alerts/ALT-20240520-001")
        assert response.status_code == 200
        data = response.json()
        assert data["alert_id"] == "ALT-20240520-001"
        assert "description" in data

    def test_get_alert_by_id_not_found(self, client):
        response = client.get("/api/v1/hazard/alerts/NON-EXISTENT")
        assert response.status_code == 404


# =========================
# POST /analyze — 隐患研判
# =========================


class TestAnalyzeAPI:
    """测试 POST /api/v1/hazard/analyze 隐患研判接口"""

    def test_analyze_oil_leak(self, client):
        """🆕 Phase 2: 油泄漏(置信度0.93) → edge_handler 边缘即时处置"""
        response = client.post("/api/v1/hazard/analyze", json={
            "image_url": "/images/inj_mold_leak.jpg",
            "alert_id": "ALT-TEST-001",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["risk_level"] == "high"
        assert data["ticket_status"] == "sent"
        assert data["next_action"] == "edge_handler"  # Phase 2: >=0.90 → 边缘
        assert len(data["ticket_data"]) > 0
        assert len(data["messages"]) > 0

    def test_analyze_blocked_exit(self, client):
        """🆕 Phase 2: 通道堵塞(置信度0.91) → edge_handler 边缘即时处置"""
        response = client.post("/api/v1/hazard/analyze", json={
            "image_url": "/images/blocked_fire_exit.jpg",
            "alert_id": "ALT-TEST-002",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["risk_level"] == "medium"
        assert data["next_action"] == "edge_handler"  # Phase 2: >=0.90 → 边缘

    def test_analyze_fire_smoke(self, client):
        """🆕 Phase 2: 烟火(置信度0.97) → edge_handler 边缘即时处置"""
        response = client.post("/api/v1/hazard/analyze", json={
            "image_url": "/images/chemical_smoke.jpg",
            "alert_id": "ALT-TEST-003",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["risk_level"] == "high"
        assert data["next_action"] == "edge_handler"  # Phase 2: >=0.90 → 边缘
        assert data["ticket_status"] == "sent"

    def test_analyze_unknown_image(self, client):
        """未知图片 → low risk → end (不生成工单)"""
        response = client.post("/api/v1/hazard/analyze", json={
            "image_url": "/images/random_unknown.jpg",
            "alert_id": "ALT-TEST-004",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["risk_level"] == "low"
        assert data["next_action"] == "end"

    def test_analyze_with_optional_fields(self, client):
        """带可选字段的完整请求"""
        response = client.post("/api/v1/hazard/analyze", json={
            "image_url": "/images/inj_mold_leak.jpg",
            "alert_id": "ALT-FULL-001",
            "edge_node_id": "EDGE_DG_01",
            "area_type": "production",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["alert_id"] == "ALT-FULL-001"

    def test_analyze_returns_graph_context(self, client):
        """响应应包含 GraphRAG 知识上下文"""
        response = client.post("/api/v1/hazard/analyze", json={
            "image_url": "/images/inj_mold_leak.jpg",
        })
        data = response.json()
        assert "graph_context" in data
        assert len(data["graph_context"]) > 0

    def test_analyze_returns_retry_count(self, client):
        """响应应包含 retry_count"""
        response = client.post("/api/v1/hazard/analyze", json={
            "image_url": "/images/inj_mold_leak.jpg",
        })
        data = response.json()
        assert "retry_count" in data
        assert data["retry_count"] == 0  # 首次成功不重试

    def test_analyze_returns_extra_fields(self, client):
        """响应应包含 need_cloud_analysis / area_type / edge_node_id"""
        response = client.post("/api/v1/hazard/analyze", json={
            "image_url": "/images/inj_mold_leak.jpg",
        })
        data = response.json()
        assert "need_cloud_analysis" in data
        assert "area_type" in data
        assert "edge_node_id" in data

    def test_analyze_missing_image_returns_422(self, client):
        """缺少必填字段 image_url → 422"""
        response = client.post("/api/v1/hazard/analyze", json={})
        assert response.status_code == 422

    def test_analyze_empty_image(self, client):
        """空 image_url → 仍能处理（返回 low/none 等级）"""
        response = client.post("/api/v1/hazard/analyze", json={
            "image_url": "",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["risk_level"] in ("low", "none")
