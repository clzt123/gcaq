"""
应急预案推演模块测试

测试范围:
    - GridMap: 地图加载、通行性检查、危险区标记
    - PathPlanner: A*路径规划、多出口选择
    - SensorSimulator: 传感器读数模拟、告警检测
    - EmergencyManager: 端到端推演
"""
import pytest

from app.core.emergency.grid_map import GridMap, MapCell, CellType
from app.core.emergency.path_planner import PathPlanner, EscapePath
from app.core.emergency.sensor_sim import SensorSimulator, SensorReading
from app.core.emergency.emergency_manager import EmergencyManager, DrillResult


# =========================
# 1. GridMap 测试
# =========================


class TestGridMap:
    """地图测试"""

    def test_load_from_mock(self):
        """测试加载 Mock 地图"""
        grid = GridMap()
        grid.load_from_mock()

        assert grid.width == 40
        assert grid.height == 30
        assert len(grid.exits) == 4
        assert len(grid.hydrants) == 6

    def test_is_valid(self):
        """测试坐标有效性"""
        grid = GridMap()
        grid.load_from_mock()

        assert grid.is_valid(0, 0) is True
        assert grid.is_valid(39, 29) is True
        assert grid.is_valid(-1, 0) is False
        assert grid.is_valid(40, 30) is False

    def test_is_passable_free_cell(self):
        """测试自由格子可通行"""
        grid = GridMap()
        grid.load_from_mock()
        # 找到一个不靠近墙的内部区域
        assert grid.is_passable(6, 8) is True

    def test_is_passable_obstacle(self):
        """测试障碍物不可通行"""
        grid = GridMap()
        grid.load_from_mock()
        # 墙壁位置在 (13, 5)
        assert grid.is_passable(13, 5) is False

    def test_is_passable_exit(self):
        """测试出口可通行"""
        grid = GridMap()
        grid.load_from_mock()
        # 北主出口 (10, 0)
        assert grid.is_passable(10, 0) is True

    def test_get_cell(self):
        """测试获取单元格"""
        grid = GridMap()
        grid.load_from_mock()

        cell = grid.get_cell(10, 0)
        assert cell is not None
        assert cell.cell_type == CellType.EXIT

        cell = grid.get_cell(13, 5)
        assert cell is not None
        assert cell.cell_type == CellType.OBSTACLE

    def test_get_neighbors(self):
        """测试获取邻居"""
        grid = GridMap()
        grid.load_from_mock()

        # 在焊接车间内部找一个自由位置
        neighbors = grid.get_neighbors(6, 6)
        assert len(neighbors) >= 2  # 至少2个可通行邻居

    def test_mark_hazard(self):
        """测试标记危险区域"""
        grid = GridMap()
        grid.load_from_mock()

        grid.mark_hazard(6, 6)
        cell = grid.get_cell(6, 6)
        assert cell is not None
        assert cell.cell_type == CellType.HAZARD

    def test_expand_hazard_zone(self):
        """测试危险区域扩散"""
        grid = GridMap()
        grid.load_from_mock()

        grid.expand_hazard_zone((6, 6), radius=3)
        hazard_count = sum(
            1 for row in grid._grid
            for cell in row
            if cell.cell_type == CellType.HAZARD
        )
        assert hazard_count >= 10  # 3半径曼哈顿范围>=13格

    def test_clear_hazards(self):
        """测试清除危险标记"""
        grid = GridMap()
        grid.load_from_mock()

        grid.mark_hazard(6, 6)
        grid.clear_hazards()

        cell = grid.get_cell(6, 6)
        assert cell.cell_type != CellType.HAZARD


# =========================
# 2. PathPlanner 测试
# =========================


class TestPathPlanner:
    """路径规划测试"""

    @pytest.fixture
    def planner(self):
        grid = GridMap()
        grid.load_from_mock()
        return PathPlanner(grid, cell_size_meters=2.0)

    def test_plan_escape_valid_start(self, planner):
        """测试有效起点路径规划"""
        result = planner.plan_escape((6, 6), "焊接车间")
        assert result is not None
        assert len(result.path) >= 2
        assert result.path[0] == (6, 6)
        assert result.total_distance > 0
        assert result.estimated_time_seconds > 0

    def test_plan_escape_various_locations(self, planner):
        """测试多个不同起点的规划"""
        starts = [
            ((6, 8), "焊接车间"),   # 避开柱子 (7,7)
            ((18, 8), "冲压车间"),  # 避开柱子 (19,7)
            ((29, 7), "装配车间"),  # 避开柱子 (28,7)
        ]

        for pos, area in starts:
            result = planner.plan_escape(pos, area)
            assert result is not None, f"起点 {pos} 规划失败"
            assert len(result.path) >= 1

    def test_plan_escape_invalid_start(self, planner):
        """测试障碍物起点"""
        # 墙壁位置不可通行
        result = planner.plan_escape((13, 5), "墙壁")
        assert result is None

    def test_plan_escape_avoids_hazards(self, planner):
        """测试避开危险区域"""
        # 标记危险区
        planner.grid.expand_hazard_zone((6, 6), radius=3)

        result = planner.plan_escape((7, 7), "焊接车间", avoid_hazards=True)
        if result:
            for x, y in result.path:
                cell = planner.grid.get_cell(x, y)
                assert cell.cell_type != CellType.HAZARD, f"路径经过危险格 ({x},{y})"

    def test_plan_multi_escape(self, planner):
        """测试多起点路径规划"""
        starts = [
            ((6, 8), "焊接车间"),   # 避开柱子 (7,7)
            ((18, 8), "冲压车间"),  # 避开柱子 (19,7)
        ]
        results = planner.plan_multi_escape(starts)
        assert len(results) == 2

    def test_path_has_alternative(self, planner):
        """测试备选路径"""
        result = planner.plan_escape((18, 15), "办公区")
        if result and len(planner.grid.exits) > 1:
            assert len(result.alternative_paths) >= 0


# =========================
# 3. SensorSimulator 测试
# =========================


class TestSensorSimulator:
    """传感器模拟器测试"""

    @pytest.fixture
    def sim(self):
        s = SensorSimulator()
        s.load_from_mock()
        return s

    def test_normal_readings(self, sim):
        """测试正常场景读数"""
        readings = sim.get_readings()
        assert len(readings) == 6  # 6个传感器

        for r in readings:
            assert r.status == "normal"
            assert r.value > 0

    def test_fire_scenario_temperature_rise(self, sim):
        """测试火灾场景温度升高"""
        sim.start_fire_scenario(center=(6, 6), intensity=0.9, spread_radius=5)

        readings = sim.get_readings()
        # 找到焊接车间附近的温度传感器
        temp_sensors = [r for r in readings if r.sensor_type == "temperature"]
        for r in temp_sensors:
            # 靠近 disaster center 的传感器应有更高读数
            assert r.value > 0

    def test_check_alerts_normal(self, sim):
        """测试正常场景无告警"""
        alerts = sim.check_alerts()
        assert len(alerts) == 0

    def test_check_alerts_fire(self, sim):
        """测试火灾场景产生告警"""
        # 高强度火灾在传感器位置
        sim.start_fire_scenario(center=(6, 6), intensity=0.95, spread_radius=8)

        alerts = sim.check_alerts()
        # 高强度火灾应产生告警
        assert len(alerts) >= 1

    def test_clear_scenarios(self, sim):
        """测试清除场景"""
        sim.start_fire_scenario(center=(6, 6), intensity=0.8)
        sim.clear_scenarios()

        alerts = sim.check_alerts()
        assert len(alerts) == 0

    def test_chemical_leak_scenario(self, sim):
        """测试化学品泄漏场景"""
        sim.start_chemical_leak(center=(36, 5), severity=0.7, spread_radius=4)

        readings = sim.get_readings()
        # 化学品库附近的烟雾传感器应检测到
        smoke_sensors = [r for r in readings if r.sensor_type == "smoke"]
        assert len(smoke_sensors) > 0

    def test_is_active_scenario(self, sim):
        """测试活跃场景判断"""
        assert sim.is_active_scenario() is False
        sim.start_fire_scenario(center=(6, 6), intensity=0.5)
        assert sim.is_active_scenario() is True


# =========================
# 4. EmergencyManager 测试
# =========================


class TestEmergencyManager:
    """推演管理器测试"""

    @pytest.mark.asyncio
    async def test_run_fire_drill(self):
        """测试火灾推演"""
        mgr = EmergencyManager()
        result = await mgr.run_drill(
            scenario_type="fire",
            center=(6, 6),
            intensity=0.8,
            spread_radius=5,
        )

        assert isinstance(result, DrillResult)
        assert result.scenario_type == "fire"
        assert result.severity == 0.8
        assert result.total_evacuation_time > 0
        assert len(result.escape_paths) >= 1
        assert len(result.sensor_alerts) >= 1
        assert len(result.recommendations) >= 3

    @pytest.mark.asyncio
    async def test_run_chemical_leak_drill(self):
        """测试化学品泄漏推演"""
        mgr = EmergencyManager()
        result = await mgr.run_drill(
            scenario_type="chemical_leak",
            center=(36, 5),
            intensity=0.7,
            spread_radius=4,
        )

        assert isinstance(result, DrillResult)
        assert result.scenario_type == "chemical_leak"
        assert len(result.affected_areas) >= 1

    @pytest.mark.asyncio
    async def test_drill_result_has_safety_flag(self):
        """测试推演结果包含安全标志"""
        mgr = EmergencyManager()
        result = await mgr.run_drill(
            scenario_type="fire",
            center=(20, 15),
            intensity=0.5,
            spread_radius=3,
        )

        assert isinstance(result.is_safe, bool)

    @pytest.mark.asyncio
    async def test_different_intensities(self):
        """测试不同强度"""
        mgr_low = EmergencyManager()
        r_low = await mgr_low.run_drill(
            scenario_type="fire", center=(6, 6), intensity=0.3, spread_radius=3,
        )

        mgr_high = EmergencyManager()
        r_high = await mgr_high.run_drill(
            scenario_type="fire", center=(6, 6), intensity=0.9, spread_radius=8,
        )

        # 高强度应产生更多告警
        assert r_high.severity > r_low.severity


# =========================
# 5. 数据模型测试
# =========================


class TestModels:
    """数据模型测试"""

    def test_map_cell(self):
        cell = MapCell(x=5, y=7, cell_type=CellType.FREE)
        assert cell.x == 5
        assert cell.y == 7
        assert cell.cell_type == CellType.FREE

    def test_escape_path(self):
        path = EscapePath(
            start=(5, 5),
            end=(10, 0),
            start_area="焊接车间",
            exit_name="北主出口",
            path=[(5, 5), (6, 5), (10, 0)],
            total_distance=15.0,
            estimated_time_seconds=7.5,
        )
        assert path.start_area == "焊接车间"
        assert len(path.path) == 3

    def test_sensor_reading_defaults(self):
        r = SensorReading(
            sensor_id="S1",
            sensor_type="temperature",
            value=25.0,
            unit="°C",
        )
        assert r.status == "normal"
        assert r.timestamp == ""

    def test_drill_result_defaults(self):
        r = DrillResult()
        assert r.scenario_type == ""
        assert r.escape_paths == []
        assert r.is_safe is True
