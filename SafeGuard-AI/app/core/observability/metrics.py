"""
可观测性指标采集与导出

实现技术方案功能 20：
    - Prometheus text format 导出器（/metrics 端点）
    - 业务指标采集：延迟、Token 消耗、RAG 召回率、工单闭环率
    - 告警规则配置与评估

指标分类:
    1. 请求指标: request_total, request_duration_seconds
    2. LLM 指标: llm_token_total, llm_call_duration_seconds
    3. RAG 指标: rag_retrieval_total, rag_recall_rate
    4. 业务指标: ticket_closure_rate, edge_cloud_ratio
    5. 错误指标: error_total, circuit_breaker_state

使用方式:
    collector = MetricsCollector.get_instance()
    collector.increment("request_total", labels={"endpoint": "/analyze"})
    collector.observe("request_duration", 0.35)
    # 导出 Prometheus 格式:
    exporter = MetricsExporter()
    prometheus_text = exporter.export(collector)
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# =========================
# 指标类型
# =========================


class MetricType:
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class Metric:
    """单个指标定义"""
    name: str
    type: str                     # counter / gauge / histogram
    help: str                     # 指标说明
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)

    # Histogram 专用
    buckets: List[float] = field(default_factory=list)
    bucket_counts: List[int] = field(default_factory=list)
    sum: float = 0.0
    count: int = 0


# =========================
# 指标采集器（线程安全单例）
# =========================


class MetricsCollector:
    """
    指标采集器（线程安全单例）。

    支持 Counter、Gauge、Histogram 三种指标类型。
    """

    _instance: Optional["MetricsCollector"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._metrics: Dict[str, Metric] = {}
        self._start_time = time.time()
        self._init_metrics()

    @classmethod
    def get_instance(cls) -> "MetricsCollector":
        """获取全局单例。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _init_metrics(self):
        """初始化预定义指标。"""
        # 请求指标
        self._register(Metric(
            name="safeguard_request_total",
            type=MetricType.COUNTER,
            help="Total number of API requests",
        ))
        self._register(Metric(
            name="safeguard_request_duration_seconds",
            type=MetricType.HISTOGRAM,
            help="Request duration in seconds",
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0],
        ))

        # LLM 指标
        self._register(Metric(
            name="safeguard_llm_token_total",
            type=MetricType.COUNTER,
            help="Total LLM tokens consumed",
        ))
        self._register(Metric(
            name="safeguard_llm_call_duration_seconds",
            type=MetricType.HISTOGRAM,
            help="LLM call duration in seconds",
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
        ))

        # RAG 指标
        self._register(Metric(
            name="safeguard_rag_retrieval_total",
            type=MetricType.COUNTER,
            help="Total RAG retrieval calls",
        ))
        self._register(Metric(
            name="safeguard_rag_recall_rate",
            type=MetricType.GAUGE,
            help="RAG recall rate (0.0-1.0)",
        ))

        # 业务指标
        self._register(Metric(
            name="safeguard_ticket_closure_rate",
            type=MetricType.GAUGE,
            help="Ticket closure rate (0.0-1.0)",
        ))
        self._register(Metric(
            name="safeguard_edge_cloud_ratio",
            type=MetricType.GAUGE,
            help="Edge vs Cloud processing ratio",
        ))
        self._register(Metric(
            name="safeguard_hallucination_refusal_rate",
            type=MetricType.GAUGE,
            help="Zero-hallucination refusal rate (0.0-1.0)",
        ))

        # 错误指标
        self._register(Metric(
            name="safeguard_error_total",
            type=MetricType.COUNTER,
            help="Total error count",
        ))
        self._register(Metric(
            name="safeguard_circuit_breaker_state",
            type=MetricType.GAUGE,
            help="Circuit breaker state (0=closed, 1=open, 2=half_open)",
        ))

    def _register(self, metric: Metric):
        """注册指标（按 name 去重）。"""
        self._metrics[metric.name] = metric

    # ---- Counter 操作 ----

    def increment(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """增加计数器。"""
        m = self._metrics.get(name)
        if m and m.type == MetricType.COUNTER:
            m.value += value
            if labels:
                m.labels.update(labels)

    # ---- Gauge 操作 ----

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """设置仪表值。"""
        m = self._metrics.get(name)
        if m and m.type == MetricType.GAUGE:
            m.value = value
            if labels:
                m.labels.update(labels)

    def inc_gauge(self, name: str, delta: float = 1.0):
        """调整仪表值。"""
        m = self._metrics.get(name)
        if m and m.type == MetricType.GAUGE:
            m.value += delta

    # ---- Histogram 操作 ----

    def observe(self, name: str, value: float):
        """记录 Histogram 观测值。"""
        m = self._metrics.get(name)
        if m and m.type == MetricType.HISTOGRAM:
            m.sum += value
            m.count += 1
            # 分桶统计
            if m.buckets and not m.bucket_counts:
                m.bucket_counts = [0] * (len(m.buckets) + 1)
            for i, bound in enumerate(m.buckets):
                if value <= bound:
                    m.bucket_counts[i] += 1
                    break
            else:
                m.bucket_counts[-1] += 1  # +Inf bucket

    # ---- 查询 ----

    def get(self, name: str) -> Optional[Metric]:
        """获取指定指标。"""
        return self._metrics.get(name)

    def get_all(self) -> Dict[str, Metric]:
        """获取所有指标。"""
        return dict(self._metrics)

    def uptime_seconds(self) -> float:
        """采集器运行时间（秒）。"""
        return time.time() - self._start_time

    def reset(self):
        """重置所有指标（仅供测试用）。"""
        self._metrics.clear()
        self._start_time = time.time()
        self._init_metrics()


# =========================
# Prometheus 格式导出器
# =========================


class MetricsExporter:
    """
    Prometheus text format 导出器。

    将 MetricsCollector 中的指标导出为标准的 Prometheus 文本格式，
    可直接挂载到 FastAPI 的 /metrics 端点。

    使用方式:
        collector = MetricsCollector.get_instance()
        exporter = MetricsExporter()
        # 在 FastAPI route 中:
        @app.get("/metrics")
        async def metrics():
            return Response(content=exporter.export(collector), media_type="text/plain")
    """

    @staticmethod
    def export(collector: MetricsCollector) -> str:
        """
        导出 Prometheus text format。

        Args:
            collector: 指标采集器

        Returns:
            Prometheus 格式文本
        """
        lines = []

        for name, metric in collector.get_all().items():
            # HELP 行
            lines.append(f"# HELP {name} {metric.help}")
            # TYPE 行
            lines.append(f"# TYPE {name} {metric.type}")

            if metric.type == MetricType.HISTOGRAM:
                # Histogram 输出
                lines.extend(
                    MetricsExporter._format_histogram(name, metric)
                )
            elif metric.type == MetricType.GAUGE:
                lines.append(
                    MetricsExporter._format_metric_line(name, metric.value, metric.labels)
                )
            else:
                # Counter
                lines.append(
                    MetricsExporter._format_metric_line(name, metric.value, metric.labels)
                )

        return "\n".join(lines) + "\n"

    @staticmethod
    def export_json(collector: MetricsCollector) -> Dict[str, Any]:
        """
        导出 JSON 格式（用于 API 消费）。

        Args:
            collector: 指标采集器

        Returns:
            JSON 友好的字典
        """
        result = {
            "uptime_seconds": round(collector.uptime_seconds(), 1),
            "metrics": {},
        }
        for name, m in collector.get_all().items():
            entry = {"type": m.type, "help": m.help}
            if m.type == MetricType.HISTOGRAM:
                entry["count"] = m.count
                entry["sum"] = round(m.sum, 6)
                entry["avg"] = round(m.sum / max(m.count, 1), 6)
            else:
                entry["value"] = m.value
            result["metrics"][name] = entry
        return result

    @staticmethod
    def _format_metric_line(name: str, value: float, labels: Dict[str, str]) -> str:
        """格式化单行指标。"""
        if labels:
            label_parts = [f'{k}="{v}"' for k, v in labels.items()]
            label_str = "{" + ",".join(label_parts) + "}"
            return f"{name}{label_str} {value}"
        return f"{name} {value}"

    @staticmethod
    def _format_histogram(name: str, metric: Metric) -> List[str]:
        """格式化 Histogram 指标。"""
        lines = []
        # 各 bucket
        cumulative = 0
        for i, bound in enumerate(metric.buckets):
            if metric.bucket_counts:
                cumulative += metric.bucket_counts[i] if i < len(metric.bucket_counts) else 0
            lines.append(
                f'{name}_bucket{{le="{bound}"}} {cumulative}'
            )
        # +Inf bucket
        inf_count = metric.bucket_counts[-1] if metric.bucket_counts else metric.count
        lines.append(f"{name}_bucket{{le=\"+Inf\"}} {metric.count}")
        # sum & count
        lines.append(f"{name}_sum {metric.sum}")
        lines.append(f"{name}_count {metric.count}")
        return lines


# =========================
# 告警规则
# =========================


@dataclass
class AlertRule:
    """告警规则定义"""
    name: str
    metric_name: str
    condition: str              # e.g., "> 0.05" , ">= 3"
    severity: str               # "critical" / "warning" / "info"
    description: str
    for_duration_seconds: int = 60  # 持续时间（秒）


class AlertRules:
    """
    告警规则引擎。

    评估预定义的告警规则，返回触发的告警列表。

    预定义规则:
        1. error_rate > 5%  → critical
        2. circuit_breaker_open → critical
        3. rag_recall < 0.5  → warning
        4. ticket_closure < 0.6 → warning
        5. llm_latency > 5s  → warning
    """

    DEFAULT_RULES = [
        AlertRule(
            name="high_error_rate",
            metric_name="safeguard_error_total",
            condition="rate > 0.05",
            severity="critical",
            description="错误率超过 5%",
        ),
        AlertRule(
            name="circuit_breaker_open",
            metric_name="safeguard_circuit_breaker_state",
            condition=">= 1",
            severity="critical",
            description="熔断器已触发",
        ),
        AlertRule(
            name="low_rag_recall",
            metric_name="safeguard_rag_recall_rate",
            condition="< 0.5",
            severity="warning",
            description="RAG 召回率低于 50%",
        ),
        AlertRule(
            name="low_ticket_closure",
            metric_name="safeguard_ticket_closure_rate",
            condition="< 0.6",
            severity="warning",
            description="工单闭环率低于 60%",
        ),
        AlertRule(
            name="high_llm_latency",
            metric_name="safeguard_llm_call_duration_seconds",
            condition="avg > 5.0",
            severity="warning",
            description="LLM 平均响应时间超过 5 秒",
        ),
        AlertRule(
            name="high_hallucination_refusal",
            metric_name="safeguard_hallucination_refusal_rate",
            condition="> 0.3",
            severity="info",
            description="零幻觉拒答率超过 30%（需关注知识库覆盖率）",
        ),
    ]

    def __init__(self, rules: Optional[List[AlertRule]] = None):
        self.rules = rules or self.DEFAULT_RULES

    def evaluate(self, collector: MetricsCollector) -> List[Dict[str, Any]]:
        """
        评估所有告警规则，返回触发的告警。

        Args:
            collector: 指标采集器

        Returns:
            触发的告警列表
        """
        triggered = []
        metrics = collector.get_all()

        for rule in self.rules:
            metric = metrics.get(rule.metric_name)
            if not metric:
                continue

            is_triggered = self._check_condition(rule, metric)
            if is_triggered:
                triggered.append({
                    "alert_name": rule.name,
                    "severity": rule.severity,
                    "description": rule.description,
                    "metric_name": rule.metric_name,
                    "current_value": self._get_metric_value(metric),
                    "condition": rule.condition,
                })

        return triggered

    def _check_condition(self, rule: AlertRule, metric: Metric) -> bool:
        """检查单个规则条件。"""
        try:
            condition = rule.condition

            if "rate >" in condition:
                # 错误率检查：error_total / request_total > threshold
                return self._check_rate_condition(condition)

            if "avg >" in condition:
                threshold = float(condition.split(">")[1].strip())
                if metric.type == MetricType.HISTOGRAM:
                    avg = metric.sum / max(metric.count, 1)
                    return avg > threshold
                return metric.value > threshold

            if ">=" in condition:
                threshold = float(condition.split(">=")[1].strip())
                return metric.value >= threshold

            if "> " in condition or ">" in condition.replace("> ", ">"):
                threshold = float(condition.replace("> ", ">").split(">")[1].strip())
                return metric.value > threshold

            if "< " in condition or "<" in condition.replace("< ", "<"):
                threshold = float(condition.replace("< ", "<").split("<")[1].strip())
                if metric.type == MetricType.HISTOGRAM:
                    avg = metric.sum / max(metric.count, 1)
                    return avg < threshold
                return metric.value < threshold

        except (ValueError, IndexError, ZeroDivisionError) as e:
            logger.warning(f"[AlertRules] 条件解析失败: {rule.condition}: {e}")

        return False

    def _check_rate_condition(self, condition: str) -> bool:
        """处理 rate 条件（需要访问多个指标）。"""
        threshold = float(condition.split(">")[1].strip())
        collector = MetricsCollector.get_instance()
        error_total = collector.get("safeguard_error_total")
        request_total = collector.get("safeguard_request_total")

        if error_total and request_total and request_total.value > 0:
            error_rate = error_total.value / request_total.value
            return error_rate > threshold
        return False

    @staticmethod
    def _get_metric_value(metric: Metric) -> float:
        """获取指标当前值。"""
        if metric.type == MetricType.HISTOGRAM:
            return round(metric.sum / max(metric.count, 1), 6)
        return metric.value
