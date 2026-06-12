"""
2D 网格地图（Mock 数字孪生）

实现技术方案功能 16 — Mock 数字孪生：用 2D 网格模拟工厂平面图。

功能:
    1. 加载工厂布局数据（从 mock_data/factory_layout.json）
    2. 标记障碍物、安全出口、消防设备
    3. 查询相邻单元格和通行性
    4. 动态更新危险区域（根据传感器数据）
"""
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from app.utils import get_mock_path

logger = logging.getLogger(__name__)


class CellType(str, Enum):
    """单元格类型"""
    FREE = "free"           # 可通行
    OBSTACLE = "obstacle"   # 障碍物（设备/墙壁/柱子）
    EXIT = "exit"           # 安全出口
    HAZARD = "hazard"       # 危险区域（火灾/烟雾/泄漏）
    RESTRICTED = "restricted"  # 限制通行（被封锁或缓慢）


@dataclass
class MapCell:
    """
    地图单元格。

    Attributes:
        x: X 坐标
        y: Y 坐标
        cell_type: 单元格类型
        area_name: 所属区域名称
        risk_level: 该格风险等级
        temperature: 当前温度（若有传感器）
        smoke_level: 当前烟雾浓度（若有传感器）
    """

    x: int
    y: int
    cell_type: CellType = CellType.FREE
    area_name: str = ""
    risk_level: str = "low"
    temperature: float = 25.0
    smoke_level: float = 0.0


class GridMap:
    """
    2D 网格地图。

    表示工厂平面图的离散化网格，用于路径规划。

    使用方式:
        grid = GridMap()
        grid.load_from_mock()
        neighbors = grid.get_neighbors(5, 7)
        path = grid.find_path(start, goal)  # 通过 PathPlanner
    """

    def __init__(self):
        """初始化空地图。"""
        self._width: int = 0
        self._height: int = 0
        self._grid: List[List[MapCell]] = []
        self._exits: List[Tuple[int, int]] = []
        self._hazard_cells: Set[Tuple[int, int]] = set()
        self._hydrants: List[Dict[str, Any]] = []
        self._sensor_positions: Dict[str, Tuple[int, int]] = {}
        self._loaded = False

    # ---- 地图加载 ----

    def load_from_mock(self):
        """从 mock_data/factory_layout.json 加载工厂地图。"""
        layout_file = get_mock_path("factory_layout.json")
        if not layout_file.exists():
            logger.error(f"[GridMap] 布局文件不存在: {layout_file}")
            return

        with open(layout_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        map_data = data["map"]
        self._width = map_data["width"]
        self._height = map_data["height"]

        # 初始化网格（全 FREE）
        self._grid = []
        for y in range(self._height):
            row = []
            for x in range(self._width):
                row.append(MapCell(x=x, y=y, cell_type=CellType.FREE))
            self._grid.append(row)

        # 标记区域
        for area in data.get("areas", []):
            self._mark_area(area)

        # 标记出口
        for exit_def in data.get("exits", []):
            pos = exit_def["position"]
            self._exits.append((pos[0], pos[1]))
            self._grid[pos[1]][pos[0]].cell_type = CellType.EXIT
            self._grid[pos[1]][pos[0]].area_name = exit_def["name"]

        # 标记障碍物
        for obstacle in data.get("obstacles", []):
            for pos in obstacle.get("positions", []):
                if 0 <= pos[0] < self._width and 0 <= pos[1] < self._height:
                    self._grid[pos[1]][pos[0]].cell_type = CellType.OBSTACLE

        # 加载传感器位置
        for sensor in data.get("sensors", []):
            pos = sensor["position"]
            self._sensor_positions[sensor["id"]] = (pos[0], pos[1])

        # 加载消防栓
        self._hydrants = data.get("fire_hydrants", [])

        self._loaded = True
        logger.info(
            f"[GridMap] 地图加载完成: {self._width}x{self._height}, "
            f"障碍物: {sum(1 for r in self._grid for c in r if c.cell_type == CellType.OBSTACLE)}, "
            f"出口: {len(self._exits)}"
        )

    def _mark_area(self, area: Dict[str, Any]):
        """在网格上标记区域信息。"""
        bounds = area.get("bounds", [])
        if len(bounds) != 4:
            return

        x1, y1, x2, y2 = bounds
        name = area.get("name", "")
        risk = area.get("risk", "low")

        for y in range(max(0, y1), min(self._height, y2 + 1)):
            for x in range(max(0, x1), min(self._width, x2 + 1)):
                self._grid[y][x].area_name = name
                self._grid[y][x].risk_level = risk

    # ---- 网格查询 ----

    def is_valid(self, x: int, y: int) -> bool:
        """检查坐标是否在地图内。"""
        return 0 <= x < self._width and 0 <= y < self._height

    def is_passable(self, x: int, y: int) -> bool:
        """
        检查单元格是否可通行。

        障碍物和危险区域不可通行。
        """
        if not self.is_valid(x, y):
            return False

        cell = self._grid[y][x]
        return cell.cell_type in (CellType.FREE, CellType.EXIT)

    def get_cell(self, x: int, y: int) -> Optional[MapCell]:
        """获取指定坐标的单元格。"""
        if not self.is_valid(x, y):
            return None
        return self._grid[y][x]

    def get_neighbors(self, x: int, y: int) -> List[Tuple[int, int]]:
        """
        获取可通行的相邻单元格（4邻域）。

        Args:
            x: X 坐标
            y: Y 坐标

        Returns:
            可通行的邻居坐标列表
        """
        directions = [(0, -1), (1, 0), (0, 1), (-1, 0)]  # 上下左右
        neighbors = []

        for dx, dy in directions:
            nx, ny = x + dx, y + dy
            if self.is_passable(nx, ny):
                neighbors.append((nx, ny))

        return neighbors

    def distance(self, a: Tuple[int, int], b: Tuple[int, int]) -> float:
        """计算两点间的欧几里得距离。"""
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    def manhattan(self, a: Tuple[int, int], b: Tuple[int, int]) -> int:
        """计算两点间的曼哈顿距离。"""
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    # ---- 危险区域管理 ----

    def mark_hazard(self, x: int, y: int, hazard_type: str = "fire"):
        """
        标记单元格为危险区域。

        Args:
            x: X 坐标
            y: Y 坐标
            hazard_type: 危险类型
        """
        if not self.is_valid(x, y):
            return

        self._grid[y][x].cell_type = CellType.HAZARD
        self._hazard_cells.add((x, y))

    def clear_hazards(self):
        """清除所有危险标记（重置地图）。"""
        for x, y in self._hazard_cells:
            if self.is_valid(x, y):
                cell = self._grid[y][x]
                if cell.cell_type == CellType.HAZARD:
                    # 恢复为 FREE（除非是出口）
                    if (x, y) in self._exits:
                        cell.cell_type = CellType.EXIT
                    else:
                        cell.cell_type = CellType.FREE
        self._hazard_cells.clear()

    def expand_hazard_zone(self, center: Tuple[int, int], radius: int):
        """
        以某点为中心扩展危险区域。

        Args:
            center: 危险中心坐标
            radius: 半径（网格单位）
        """
        cx, cy = center
        for y in range(
            max(0, cy - radius),
            min(self._height, cy + radius + 1),
        ):
            for x in range(
                max(0, cx - radius),
                min(self._width, cx + radius + 1),
            ):
                if self.manhattan((x, y), center) <= radius:
                    if self._grid[y][x].cell_type == CellType.FREE:
                        self.mark_hazard(x, y)

    # ---- 属性 ----

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def exits(self) -> List[Tuple[int, int]]:
        return self._exits

    @property
    def hydrants(self) -> List[Dict[str, Any]]:
        return self._hydrants

    @property
    def sensor_positions(self) -> Dict[str, Tuple[int, int]]:
        return self._sensor_positions
