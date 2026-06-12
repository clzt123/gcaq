"""
应急预案推演模块

实现技术方案功能 16 — 应急预案推演：
    1. 2D 网格地图（Mock 数字孪生）
    2. A* 算法最优逃生路径规划
    3. 传感器数据模拟（烟雾/温度）
    4. 预案生成与评估

备注: 生产环境需对接 Unity/UE 数字孪生或 GIS 地图 API
"""

from app.core.emergency.grid_map import GridMap, MapCell, CellType
from app.core.emergency.path_planner import PathPlanner, EscapePath
from app.core.emergency.sensor_sim import SensorSimulator, SensorReading
from app.core.emergency.emergency_manager import EmergencyManager, DrillResult

__all__ = [
    "GridMap",
    "MapCell",
    "CellType",
    "PathPlanner",
    "EscapePath",
    "SensorSimulator",
    "SensorReading",
    "EmergencyManager",
    "DrillResult",
]
