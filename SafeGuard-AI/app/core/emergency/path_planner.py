"""
A* 逃生路径规划器

实现技术方案功能 16 — A* 算法计算最优逃生路径。

算法: A* (A-Star) 启发式搜索
    - g(n): 从起点到节点 n 的实际代价
    - h(n): 从节点 n 到最近出口的启发式距离（曼哈顿距离）
    - f(n) = g(n) + h(n)

特性:
    - 自动选择最近出口
    - 避开危险区域动态重规划
    - 多出口场景的最优选择
"""
import heapq
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.emergency.grid_map import GridMap, CellType

logger = logging.getLogger(__name__)


@dataclass
class EscapePath:
    """
    逃生路径。

    Attributes:
        start: 起点 (x, y)
        end: 终点 (exit_name, x, y)
        start_area: 起点区域名称
        exit_name: 出口名称
        path: 路径坐标列表 [(x1,y1), (x2,y2), ...]
        total_distance: 总距离（网格单位）
        estimated_time_seconds: 预计逃生时间（秒）
        is_safe: 路径是否安全（不经过危险区）
        alternative_paths: 备选路径列表
    """

    start: Tuple[int, int]
    end: Tuple[int, int]
    start_area: str = ""
    exit_name: str = ""
    path: List[Tuple[int, int]] = field(default_factory=list)
    total_distance: float = 0.0
    estimated_time_seconds: float = 0.0
    is_safe: bool = True
    alternative_paths: List[List[Tuple[int, int]]] = field(default_factory=list)


class PathPlanner:
    """
    A* 路径规划器。

    计算从起点到最近安全出口的最优路径，
    支持避开危险区域的动态重规划。

    使用方式:
        planner = PathPlanner(grid_map)
        result = planner.plan_escape(start_pos=(5, 10))
        print(f"最近出口: {result.exit_name}, 预计 {result.estimated_time_seconds}s")
    """

    # 行走速度常量
    WALK_SPEED_MPS = 1.4       # 正常步行速度 m/s
    EVACUATION_SPEED_MPS = 2.0 # 紧急疏散速度 m/s

    def __init__(self, grid_map: GridMap, cell_size_meters: float = 2.0):
        """
        初始化路径规划器。

        Args:
            grid_map: 工厂网格地图
            cell_size_meters: 每格代表的实际米数
        """
        self.grid = grid_map
        self.cell_size_m = cell_size_meters

    def plan_escape(
        self,
        start_pos: Tuple[int, int],
        start_area: str = "",
        avoid_hazards: bool = True,
    ) -> Optional[EscapePath]:
        """
        规划从起点到最近安全出口的逃生路径。

        Args:
            start_pos: 起点坐标 (x, y)
            start_area: 起点区域名称
            avoid_hazards: 是否避开危险区域

        Returns:
            EscapePath 或 None（无可行路径时）
        """
        sx, sy = start_pos

        if not self.grid.is_passable(sx, sy):
            logger.warning(f"[PathPlanner] 起点不可通行: ({sx}, {sy})")
            return None

        exits = self.grid.exits
        if not exits:
            logger.error("[PathPlanner] 地图无安全出口")
            return None

        # 寻找最近出口
        best_path: Optional[EscapePath] = None
        best_distance = float("inf")

        for exit_pos in exits:
            ex, ey = exit_pos
            if not self.grid.is_passable(ex, ey):
                continue

            path = self._a_star(start_pos, exit_pos, avoid_hazards)
            if path is None:
                continue

            distance = self.grid.distance(start_pos, exit_pos)
            if distance < best_distance:
                best_distance = distance
                best_path = EscapePath(
                    start=start_pos,
                    start_area=start_area,
                    end=exit_pos,
                    exit_name=self.grid.get_cell(ex, ey).area_name if self.grid.get_cell(ex, ey) else f"出口({ex},{ey})",
                    path=path,
                    total_distance=round(len(path) * self.cell_size_m, 1),
                    estimated_time_seconds=round(len(path) * self.cell_size_m / self.EVACUATION_SPEED_MPS, 1),
                    is_safe=True,
                )

        if best_path is None:
            logger.warning(f"[PathPlanner] 无可行逃生路径: ({sx}, {sy})")
            return None

        # 寻找备选路径（次近出口）
        for exit_pos in exits:
            if exit_pos == best_path.end:
                continue

            alt_path = self._a_star(start_pos, exit_pos, avoid_hazards)
            if alt_path and len(alt_path) < len(best_path.path) * 1.5:
                best_path.alternative_paths.append(alt_path)

        logger.info(
            f"[PathPlanner] 逃生路径: {start_area or start_pos} → "
            f"{best_path.exit_name}, {len(best_path.path)} 步, "
            f"{best_path.estimated_time_seconds}s"
        )
        return best_path

    def plan_multi_escape(
        self,
        start_positions: List[Tuple[Tuple[int, int], str]],
        avoid_hazards: bool = True,
    ) -> List[EscapePath]:
        """
        为多个起点批量规划逃生路径。

        Args:
            start_positions: [(起点坐标, 区域名), ...]
            avoid_hazards: 是否避开危险

        Returns:
            EscapePath 列表
        """
        results = []
        for pos, area in start_positions:
            path = self.plan_escape(pos, area, avoid_hazards)
            if path:
                results.append(path)
        return results

    # ---- A* 算法实现 ----

    def _a_star(
        self,
        start: Tuple[int, int],
        goal: Tuple[int, int],
        avoid_hazards: bool = True,
    ) -> Optional[List[Tuple[int, int]]]:
        """
        A* 寻路算法。

        Args:
            start: 起点
            goal: 终点
            avoid_hazards: 是否避开危险区

        Returns:
            路径坐标列表（含起点和终点），无路径时返回 None
        """
        if start == goal:
            return [start]

        # 优先队列: (f_score, counter, node)
        # counter 用于打破 f_score 相等时的比较
        open_set: List[Tuple[float, int, Tuple[int, int]]] = []
        heapq.heappush(open_set, (0, 0, start))
        counter = 1

        came_from: Dict[Tuple[int, int], Optional[Tuple[int, int]]] = {start: None}
        g_score: Dict[Tuple[int, int], float] = {start: 0.0}

        while open_set:
            _, _, current = heapq.heappop(open_set)

            if current == goal:
                return self._reconstruct_path(came_from, current)

            for neighbor in self.grid.get_neighbors(current[0], current[1]):
                # 如果避开危险区，检查邻居是否危险
                if avoid_hazards:
                    cell = self.grid.get_cell(neighbor[0], neighbor[1])
                    if cell and cell.cell_type == CellType.HAZARD:
                        continue

                # g(n) 增量: 相邻格距离 = 1
                tentative_g = g_score[current] + 1.0

                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    g_score[neighbor] = tentative_g
                    # f(n) = g(n) + h(n), h = 曼哈顿距离到目标
                    h = self.grid.manhattan(neighbor, goal)
                    f = tentative_g + h

                    came_from[neighbor] = current
                    heapq.heappush(open_set, (f, counter, neighbor))
                    counter += 1

        # 无路径
        return None

    def _reconstruct_path(
        self,
        came_from: Dict[Tuple[int, int], Optional[Tuple[int, int]]],
        current: Tuple[int, int],
    ) -> List[Tuple[int, int]]:
        """从 came_from 字典重建路径。"""
        path = [current]
        while came_from.get(current) is not None:
            current = came_from[current]
            path.append(current)
        path.reverse()
        return path
