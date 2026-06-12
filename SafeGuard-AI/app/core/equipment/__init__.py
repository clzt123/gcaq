"""
设备全生命周期管理模块 (Equipment Lifecycle Management)

实现技术方案功能 10 — 设备全生命周期：
    1. 设备档案与状态追踪
    2. 基于故障频率的设备风险指数算法
    3. 维保到期/大修阈值预警
    4. MES 系统对接接口（Mock）

核心类:
    EquipmentProfile  — 设备档案数据模型
    EquipmentRiskScorer — 设备风险评分引擎
    EquipmentManager   — 设备全生命周期管理器
"""

from app.core.equipment.manager import (
    EquipmentProfile,
    MaintenanceRecord,
    EquipmentRiskScorer,
    EquipmentManager,
    EquipmentStatus,
)

__all__ = [
    "EquipmentProfile",
    "MaintenanceRecord",
    "EquipmentRiskScorer",
    "EquipmentManager",
    "EquipmentStatus",
]
