"""
可观测性看板模块单元测试
"""
import pytest

from app.core.observability.metrics import (
    MetricsCollector,
    MetricsExporter,
    AlertRules,
    AlertRule,
    Metric,
    MetricType,
)


class TestMetricsCollector:
    """测试指标采集器"""

    def setup_method(self):
        self.collector = MetricsCollector()
        self.collector.reset()

    def test_singleton(self):
        """单例模式"""
        c1 = MetricsCollector.get_instance()
        c2 = MetricsCollector.get_instance()
        assert c1 is c2

    def test_increment_counter(self):
        self.collector.increment("safeguard_request_total")
        assert self.collector.get("safeguard_request_total").value == 1
        self.collector.increment("safeguard_request_total", 3)
        assert self.collector.get("safeguard_request_total").value == 4

    def test_set_gauge(self):
        self.collector.set_gauge("safeguard_rag_recall_rate", 0.85)
        assert self.collector.get("safeguard_rag_recall_rate").value == 0.85

    def test_observe_histogram(self):
        self.collector.observe("safeguard_request_duration_seconds", 0.5)
        self.collector.observe("safeguard_request_duration_seconds", 1.2)
        m = self.collector.get("safeguard_request_duration_seconds")
        assert m.count == 2
        assert m.sum == 1.7

    def test_uptime(self):
        assert self.collector.uptime_seconds() >= 0

    def test_get_all(self):
        all_m = self.collector.get_all()
        assert "safeguard_request_total" in all_m
        assert "safeguard_error_total" in all_m


class TestMetricsExporter:
    """测试 Prometheus 格式导出"""

    def test_export_prometheus(self):
        collector = MetricsCollector()
        collector.reset()
        collector.increment("safeguard_request_total", 10)
        collector.set_gauge("safeguard_ticket_closure_rate", 0.85)

        text = MetricsExporter.export(collector)
        assert "safeguard_request_total" in text
        assert "safeguard_ticket_closure_rate 0.85" in text
        assert "# HELP" in text
        assert "# TYPE" in text

    def test_export_json(self):
        collector = MetricsCollector()
        collector.reset()
        collector.increment("safeguard_request_total", 5)

        data = MetricsExporter.export_json(collector)
        assert data["metrics"]["safeguard_request_total"]["value"] == 5


class TestAlertRules:
    """测试告警规则"""

    def test_circuit_breaker_open_triggers(self):
        collector = MetricsCollector()
        collector.reset()
        collector.set_gauge("safeguard_circuit_breaker_state", 1)

        rules = AlertRules()
        triggered = rules.evaluate(collector)
        alert_names = {a["alert_name"] for a in triggered}
        assert "circuit_breaker_open" in alert_names

    def test_low_rag_recall_triggers(self):
        collector = MetricsCollector()
        collector.reset()
        collector.set_gauge("safeguard_rag_recall_rate", 0.3)

        rules = AlertRules()
        triggered = rules.evaluate(collector)
        alert_names = {a["alert_name"] for a in triggered}
        assert "low_rag_recall" in alert_names

    def test_normal_state_no_alerts(self):
        collector = MetricsCollector()
        collector.reset()
        collector.set_gauge("safeguard_circuit_breaker_state", 0)
        collector.set_gauge("safeguard_rag_recall_rate", 0.9)
        collector.set_gauge("safeguard_ticket_closure_rate", 0.8)

        rules = AlertRules()
        triggered = rules.evaluate(collector)
        alert_names = {a["alert_name"] for a in triggered}
        assert "circuit_breaker_open" not in alert_names
        assert "low_rag_recall" not in alert_names
