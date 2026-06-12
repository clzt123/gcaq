"""
应急预案推演管理器

实现技术方案功能 16 — 应急预案推演的统一入口。

完整流程:
    传感器告警 → 灾害场景扩散 → 危险区域标记 → 逃生路径规划 → 预案生成

输出:
    - 每区域最优逃生路径
    - 预计疏散时间
    - 风险等级评估
    - 应急建议
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.core.emergency.grid_map import GridMap, CellType
from app.core.emergency.path_planner import PathPlanner, EscapePath
from app.core.emergency.sensor_sim import SensorSimulator, SensorReading

logger = logging.getLogger(__name__)


@dataclass
class DrillResult:
    """
    应急推演结果。

    Attributes:
        scenario_type: 场景类型 (fire / chemical_leak)
        scenario_center: 灾害中心
        severity: 严重程度
        escape_paths: 各区域逃生路径
        total_evacuation_time: 预计全厂疏散时间（秒）
        affected_areas: 受影响区域列表
        sensor_alerts: 传感器告警
        recommendations: 应急建议
        is_safe: 推演是否通过（疏散时间在阈值内）
    """

    scenario_type: str = ""
    scenario_center: Tuple[int, int] = (0, 0)
    severity: float = 0.0
    escape_paths: List[EscapePath] = field(default_factory=list)
    total_evacuation_time: float = 0.0
    affected_areas: List[str] = field(default_factory=list)
    sensor_alerts: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    is_safe: bool = True


class EmergencyManager:
    """
    应急预案推演管理器。

    协调地图、传感器和路径规划，输出完整的应急推演报告。

    使用方式:
        mgr = EmergencyManager()
        result = await mgr.run_drill(
            scenario_type="fire",
            center=(6, 6),
            intensity=0.8,
        )
        print(f"预计疏散时间: {result.total_evacuation_time}s")
    """

    # 疏散时间阈值
    EVACUATION_TIME_LIMIT_SECONDS = 300  # 5分钟

    def __init__(self):
        """初始化推演管理器。"""
        self.grid = GridMap()
        self._load_map()

        self.planner = PathPlanner(self.grid, cell_size_meters=2.0)
        self.sensors = SensorSimulator()

    def _load_map(self):
        """加载工厂地图。"""
        try:
            self.grid.load_from_mock()
            self.sensors.load_from_mock()
            logger.info("[EmergencyManager] 地图和传感器加载完成")
        except Exception as e:
            logger.error(f"[EmergencyManager] 加载失败: {e}")

    async def run_drill(
        self,
        scenario_type: str = "fire",
        center: Tuple[int, int] = (6, 6),
        intensity: float = 0.8,
        spread_radius: int = 5,
    ) -> DrillResult:
        """
        执行一次应急推演。

        流程:
            1. 启动灾害场景（传感器数据变化）
            2. 标记危险区域（地图更新）
            3. 为各区域的代表点位规划逃生路径
            4. 计算全厂疏散时间
            5. 生成应急建议

        Args:
            scenario_type: 场景类型 (fire / chemical_leak)
            center: 灾害中心坐标
            intensity: 灾害强度 0.0-1.0
            spread_radius: 影响半径（网格单位）

        Returns:
            DrillResult 推演结果
        """
        logger.info(
            f"[EmergencyManager] 开始推演: type={scenario_type}, "
            f"center={center}, intensity={intensity:.1%}"
        )

        # 重置之前的状态
        self.grid.clear_hazards()
        self.sensors.clear_scenarios()

        # Step 1: 启动灾害场景
        if scenario_type == "fire":
            self.sensors.start_fire_scenario(center, intensity, spread_radius)
        elif scenario_type == "chemical_leak":
            self.sensors.start_chemical_leak(center, intensity, spread_radius)
        else:
            logger.warning(f"[EmergencyManager] 未知场景类型: {scenario_type}")

        # Step 2: 标记危险区域
        self.grid.expand_hazard_zone(center, spread_radius)

        # Step 3: 获取传感器告警
        alerts = self.sensors.check_alerts()

        # Step 4: 为各区域规划逃生路径
        area_start_points = self._get_area_start_points()
        escape_paths = self.planner.plan_multi_escape(
            area_start_points,
            avoid_hazards=True,
        )

        # Step 5: 统计受影响区域
        affected_areas = self._identify_affected_areas(center, spread_radius)

        # Step 6: 计算全厂疏散时间
        # 取最慢路径 + 安全因子
        max_path_time = max(
            (p.estimated_time_seconds for p in escape_paths),
            default=0,
        )
        total_evacuation = max_path_time * 1.3  # 30% 拥堵因子

        # Step 7: 生成建议
        recommendations = self._generate_recommendations(
            scenario_type, intensity, escape_paths, alerts, total_evacuation
        )

        result = DrillResult(
            scenario_type=scenario_type,
            scenario_center=center,
            severity=intensity,
            escape_paths=escape_paths,
            total_evacuation_time=round(total_evacuation, 1),
            affected_areas=affected_areas,
            sensor_alerts=alerts,
            recommendations=recommendations,
            is_safe=total_evacuation < self.EVACUATION_TIME_LIMIT_SECONDS,
        )

        logger.info(
            f"[EmergencyManager] 推演完成: "
            f"疏散时间={total_evacuation:.1f}s, "
            f"安全={'✅' if result.is_safe else '❌'}, "
            f"受影响区域={len(affected_areas)}"
        )
        return result

    def _get_area_start_points(self) -> List[Tuple[Tuple[int, int], str]]:
        """
        获取各区域的代表起点坐标。

        Returns:
            [((x, y), area_name), ...]
        """
        # 使用各区域的中心点（避开柱子/障碍物）
        areas = [
            ((6, 8), "焊接车间"),       # 避开柱子 (7,7)
            ((18, 8), "冲压车间"),      # 避开柱子 (19,7)
            ((29, 7), "装配车间"),      # 避开柱子 (28,7)
            ((36, 5), "化学品库"),
            ((6, 18), "仓库区域"),      # 避开柱子 (7,18)
            ((18, 15), "办公区"),
            ((29, 18), "3号厂房"),     # 避开柱子 (28,18)
            ((36, 13), "设备维修区"),
        ]

        # 只保留可通行的起点
        valid_starts = []
        for pos, name in areas:
            if self.grid.is_passable(pos[0], pos[1]):
                valid_starts.append((pos, name))
            else:
                # 尝试找附近可通行的位置
                for dx in range(-2, 3):
                    for dy in range(-2, 3):
                        nx, ny = pos[0] + dx, pos[1] + dy
                        if self.grid.is_passable(nx, ny):
                            valid_starts.append(((nx, ny), name))
                            break
                    else:
                        continue
                    break

        return valid_starts

    def _identify_affected_areas(
        self, center: Tuple[int, int], radius: int
    ) -> List[str]:
        """识别受灾害影响的区域。"""
        affected = set()
        cx, cy = center

        for y in range(
            max(0, cy - radius),
            min(self.grid.height, cy + radius + 1),
        ):
            for x in range(
                max(0, cx - radius),
                min(self.grid.width, cx + radius + 1),
            ):
                if self.grid.manhattan((x, y), center) <= radius:
                    cell = self.grid.get_cell(x, y)
                    if cell and cell.area_name:
                        affected.add(cell.area_name)

        return sorted(affected)

    def _generate_recommendations(
        self,
        scenario_type: str,
        intensity: float,
        escape_paths: List[EscapePath],
        alerts: List[Dict[str, Any]],
        evacuation_time: float,
    ) -> List[str]:
        """生成应急建议。"""
        recs = []

        # 场景相关建议
        if scenario_type == "fire":
            recs.append(
                f"🔥 火灾推演（强度 {intensity:.0%}）："
                f"预计全厂疏散 {evacuation_time:.0f} 秒"
            )
            if evacuation_time > self.EVACUATION_TIME_LIMIT_SECONDS:
                recs.append(
                    "❌ 疏散时间超标！建议增加疏散通道或减少人员密度。"
                )
            else:
                recs.append("✅ 疏散时间在安全范围内。")

        elif scenario_type == "chemical_leak":
            recs.append(
                f"☣️ 化学品泄漏推演（严重度 {intensity:.0%}）："
                f"关注上风向区域的疏散引导。"
            )

        # 传感器告警建议
        critical_alerts = [a for a in alerts if a["status"] == "critical"]
        if critical_alerts:
            recs.append(
                f"🚨 {len(critical_alerts)} 个传感器超过危险阈值，"
                f"建议立即通知值班安全员和消防队。"
            )

        # 路径相关建议
        if escape_paths:
            slowest = max(escape_paths, key=lambda p: p.estimated_time_seconds)
            recs.append(
                f"最慢逃生路线: {slowest.start_area} → {slowest.exit_name} "
                f"({slowest.estimated_time_seconds}s, {len(slowest.path)} 步)"
            )

            # 针对慢速路径的建议
            if slowest.estimated_time_seconds > 60:
                recs.append(
                    f"⚠️ {slowest.start_area} 的逃生时间过长，建议增设紧急出口"
                    f"或在应急响应计划中将该区域设为优先搜救区域。"
                )

        # 消防设备建议
        hydrants = self.grid.hydrants
        low_pressure = [h for h in hydrants if h.get("status") == "low_pressure"]
        if low_pressure:
            recs.append(
                f"⚠️ {len(low_pressure)} 个消防栓水压偏低（{', '.join(h['id'] for h in low_pressure)}），"
                f"建议在推演前维修。"
            )

        # 通用建议
        recs.append("建议每季度进行一次全员消防疏散演练。")
        recs.append("确保所有安全出口指示灯和应急照明处于正常工作状态。")

        return recs
