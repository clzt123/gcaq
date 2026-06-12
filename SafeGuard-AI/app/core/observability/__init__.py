"""
可观测性看板模块 (Observability Dashboard)

实现技术方案功能 20 — 可观测性看板：
    1. Prometheus metrics 导出（/metrics 端点）
    2. 业务指标采集（延迟/Token成本/RAG召回率/工单闭环率）
    3. 告警规则配置

核心类:
    MetricsCollector — 指标采集器
    MetricsExporter   — Prometheus 格式导出器
    AlertRules        — 告警规则引擎
"""

from app.core.observability.metrics import (
    MetricsCollector,
    MetricsExporter,
    AlertRules,
)

__all__ = [
    "MetricsCollector",
    "MetricsExporter",
    "AlertRules",
]
