"""
传感器数据模拟器

实现技术方案功能 16 — 实时传感器数据模拟（烟雾/温度）。

功能:
    1. 模拟火灾/泄漏场景下的传感器读数变化
    2. 温度梯度传播模拟
    3. 烟雾扩散模拟
    4. 异常检测与告警触发
"""
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class SensorReading:
    """
    传感器读数。

    Attributes:
        sensor_id: 传感器 ID
        sensor_type: 类型 (temperature / smoke)
        value: 当前读数
        unit: 单位 (°C / ppm / %)
        position: 传感器位置 (x, y)
        status: 状态 (normal / warning / critical)
        timestamp: 时间戳
    """

    sensor_id: str
    sensor_type: str
    value: float
    unit: str
    position: Tuple[int, int] = (0, 0)
    status: str = "normal"
    timestamp: str = ""


class SensorSimulator:
    """
    传感器数据模拟器。

    模拟火灾/化学品泄漏等紧急场景下的传感器数据变化。

    使用方式:
        sim = SensorSimulator()
        sim.start_fire_scenario(center=(6, 6), intensity=0.8)
        readings = sim.get_readings()
        alerts = sim.check_alerts()
    """

    # 告警阈值
    TEMP_WARNING = 40.0     # 温度警告 °C
    TEMP_CRITICAL = 70.0    # 温度危险 °C
    SMOKE_WARNING = 0.15    # 烟雾警告浓度
    SMOKE_CRITICAL = 0.5    # 烟雾危险浓度

    def __init__(self):
        """初始化传感器模拟器。"""
        self._sensors: List[Dict[str, Any]] = []
        self._hazard_scenarios: List[Dict[str, Any]] = []
        self._loaded = False

    def load_from_mock(self):
        """从 mock_data/factory_layout.json 加载传感器配置。"""
        import json
        from app.utils import get_mock_path

        layout_file = get_mock_path("factory_layout.json")
        if not layout_file.exists():
            logger.error(f"[SensorSim] 布局文件不存在: {layout_file}")
            return

        with open(layout_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._sensors = data.get("sensors", [])
        self._loaded = True
        logger.info(f"[SensorSim] 加载 {len(self._sensors)} 个传感器")

    # ---- 场景模拟 ----

    def start_fire_scenario(
        self,
        center: Tuple[int, int],
        intensity: float = 0.8,
        spread_radius: int = 5,
    ):
        """
        启动火灾场景模拟。

        Args:
            center: 火灾中心 (x, y)
            intensity: 火灾强度 0.0-1.0
            spread_radius: 影响半径（网格单位）
        """
        if not self._loaded:
            self.load_from_mock()

        self._hazard_scenarios.append({
            "type": "fire",
            "center": center,
            "intensity": intensity,
            "spread_radius": spread_radius,
            "started_at": datetime.now().isoformat(),
        })

        logger.info(
            f"[SensorSim] 火灾场景启动: center={center}, "
            f"intensity={intensity:.1%}, radius={spread_radius}"
        )

    def start_chemical_leak(
        self,
        center: Tuple[int, int],
        severity: float = 0.6,
        spread_radius: int = 3,
    ):
        """
        启动化学品泄漏场景模拟。

        Args:
            center: 泄漏中心
            severity: 严重程度 0.0-1.0
            spread_radius: 影响半径
        """
        if not self._loaded:
            self.load_from_mock()

        self._hazard_scenarios.append({
            "type": "chemical_leak",
            "center": center,
            "intensity": severity,
            "spread_radius": spread_radius,
            "started_at": datetime.now().isoformat(),
        })

        logger.info(
            f"[SensorSim] 化学品泄漏场景启动: center={center}, "
            f"severity={severity:.1%}"
        )

    def clear_scenarios(self):
        """清除所有模拟场景。"""
        self._hazard_scenarios.clear()
        logger.info("[SensorSim] 所有场景已清除")

    # ---- 传感器读数 ----

    def get_readings(self) -> List[SensorReading]:
        """
        获取所有传感器的当前读数。

        根据活跃的场景计算每个传感器的模拟读数。

        Returns:
            SensorReading 列表
        """
        if not self._loaded:
            self.load_from_mock()

        readings = []

        for sensor in self._sensors:
            sensor_id = sensor["id"]
            sensor_type = sensor["type"]
            pos = tuple(sensor["position"])
            normal_range = sensor.get("normal_range", [0, 100])

            reading = self._calculate_reading(
                sensor_id=sensor_id,
                sensor_type=sensor_type,
                position=pos,
                normal_range=normal_range,
            )

            reading.timestamp = datetime.now().isoformat()
            readings.append(reading)

        return readings

    def _calculate_reading(
        self,
        sensor_id: str,
        sensor_type: str,
        position: Tuple[int, int],
        normal_range: List[float],
    ) -> SensorReading:
        """
        根据活跃场景计算传感器读数。

        Args:
            sensor_id: 传感器 ID
            sensor_type: 类型
            position: 位置
            normal_range: 正常范围 [min, max]

        Returns:
            SensorReading
        """
        # 基础值：正常范围中值
        base_value = (normal_range[0] + normal_range[1]) / 2.0
        unit = "°C" if sensor_type == "temperature" else "ppm"

        # 添加基线噪声
        noise = random.uniform(-0.05, 0.05) * (normal_range[1] - normal_range[0])
        value = base_value + noise

        # 叠加场景影响
        max_effect = 0.0
        for scenario in self._hazard_scenarios:
            center = scenario["center"]
            intensity = scenario["intensity"]
            radius = scenario["spread_radius"]
            scenario_type = scenario["type"]

            # 计算距离
            dx = position[0] - center[0]
            dy = position[1] - center[1]
            distance = (dx * dx + dy * dy) ** 0.5

            if distance <= radius:
                # 距离衰减因子
                attenuation = max(0.0, 1.0 - (distance / radius))

                if sensor_type == "temperature" and scenario_type == "fire":
                    effect = attenuation * intensity * 100.0  # 最高+100°C
                elif sensor_type == "temperature" and scenario_type == "chemical_leak":
                    effect = attenuation * intensity * 30.0   # 最高+30°C
                elif sensor_type == "smoke":
                    effect = attenuation * intensity * 0.8    # 最高+0.8ppm
                else:
                    effect = attenuation * intensity * 20.0

                max_effect = max(max_effect, effect)

        value += max_effect

        # 确定状态
        if sensor_type == "temperature":
            if value >= self.TEMP_CRITICAL:
                status = "critical"
            elif value >= self.TEMP_WARNING:
                status = "warning"
            else:
                status = "normal"
        else:  # smoke
            if value >= self.SMOKE_CRITICAL:
                status = "critical"
            elif value >= self.SMOKE_WARNING:
                status = "warning"
            else:
                status = "normal"

        return SensorReading(
            sensor_id=sensor_id,
            sensor_type=sensor_type,
            value=round(value, 2),
            unit=unit,
            position=position,
            status=status,
        )

    # ---- 告警 ----

    def check_alerts(self) -> List[Dict[str, Any]]:
        """
        检查并返回所有告警。

        Returns:
            告警列表 [{sensor_id, type, value, status, message}]
        """
        readings = self.get_readings()
        alerts = []

        for r in readings:
            if r.status in ("warning", "critical"):
                alerts.append({
                    "sensor_id": r.sensor_id,
                    "type": r.sensor_type,
                    "value": r.value,
                    "unit": r.unit,
                    "status": r.status,
                    "position": list(r.position),
                    "message": self._format_alert_message(r),
                    "timestamp": r.timestamp,
                })

        return alerts

    def _format_alert_message(self, reading: SensorReading) -> str:
        """格式化告警消息。"""
        if reading.sensor_type == "temperature":
            if reading.status == "critical":
                return (
                    f"🔥 危险！传感器 {reading.sensor_id} 检测到高温 "
                    f"{reading.value}°C（危险阈值: {self.TEMP_CRITICAL}°C），"
                    f"可能发生火灾！"
                )
            else:
                return (
                    f"⚠️ 警告：传感器 {reading.sensor_id} 温度偏高 "
                    f"{reading.value}°C（警告阈值: {self.TEMP_WARNING}°C）"
                )
        else:  # smoke
            if reading.status == "critical":
                return (
                    f"🚨 危险！传感器 {reading.sensor_id} 检测到高浓度烟雾 "
                    f"{reading.value} ppm（危险阈值: {self.SMOKE_CRITICAL} ppm），"
                    f"立即疏散！"
                )
            else:
                return (
                    f"⚠️ 警告：传感器 {reading.sensor_id} 烟雾浓度升高 "
                    f"{reading.value} ppm（警告阈值: {self.SMOKE_WARNING} ppm）"
                )

    # ---- 查询 ----

    def get_hazard_centers(self) -> List[Tuple[int, int]]:
        """获取所有活跃灾害中心坐标。"""
        return [
            tuple(s["center"])
            for s in self._hazard_scenarios
        ]

    def is_active_scenario(self) -> bool:
        """是否有活跃的灾害场景。"""
        return len(self._hazard_scenarios) > 0
