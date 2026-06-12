"""
设备全生命周期管理器

实现技术方案功能 10：
    - 设备档案管理与状态追踪
    - 基于故障频率/维保记录的风险评分
    - 维保到期/大修阈值预警
    - MES 系统对接抽象（Mock 实现）

风险评分维度:
    1. 故障频率 (40%): 近12个月故障次数 + 严重程度
    2. 维保状态 (30%): 逾期未保养/大修到期
    3. 设备役龄 (20%): 服役年限 vs 设计寿命
    4. 运行环境 (10%): 高危环境（高温/高压/腐蚀）附加风险

预警类型:
    - 维保到期预警: 距离下次保养 ≤ 7天
    - 大修阈值预警: 累计运行时间 ≥ 大修周期 × 80%
    - 高风险设备预警: 风险评分 ≥ 0.70

使用方式:
    manager = EquipmentManager()
    await manager.load_all()
    risky = manager.get_high_risk_equipment()
    alerts = manager.get_maintenance_alerts()
"""
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from app.utils import get_mock_path

logger = logging.getLogger(__name__)

# =========================
# 常量
# =========================

# 风险阈值
EQUIP_RISK_HIGH = 0.70
EQUIP_RISK_MEDIUM = 0.40

# 评分权重
W_EQ_FAILURE = 0.40      # 故障频率
W_EQ_MAINTENANCE = 0.30   # 维保状态
W_EQ_AGE = 0.20          # 设备役龄
W_EQ_ENV = 0.10           # 运行环境

# 预警提前天数
MAINTENANCE_WARN_DAYS = 7    # 维保到期预警
OVERHAUL_RATIO_WARN = 0.80   # 大修阈值预警比例


class EquipmentStatus(str, Enum):
    """设备状态"""
    NORMAL = "normal"
    WARNING = "warning"      # 需关注
    MAINTENANCE_DUE = "maintenance_due"  # 维保到期
    OVERHAUL_DUE = "overhaul_due"        # 大修到期
    FAULT = "fault"          # 故障停机
    DECOMMISSIONED = "decommissioned"    # 已报废


@dataclass
class MaintenanceRecord:
    """
    维保/维修记录。
    """
    record_id: str
    record_type: str            # "routine_maintenance" / "repair" / "overhaul" / "inspection"
    performed_at: datetime
    description: str = ""
    cost: float = 0.0
    downtime_hours: float = 0.0
    technician: str = ""
    parts_replaced: List[str] = field(default_factory=list)


@dataclass
class FailureRecord:
    """
    故障记录。
    """
    failure_id: str
    failure_type: str           # e.g., "leak", "mechanical", "electrical", "overheat"
    occurred_at: datetime
    severity: str               # "critical" / "major" / "minor"
    description: str = ""
    downtime_hours: float = 0.0
    root_cause: str = ""
    resolved: bool = True


@dataclass
class EquipmentProfile:
    """
    设备档案。

    Attributes:
        equipment_id: 设备编号
        name: 设备名称
        equipment_type: 设备类型（泵/压缩机/压力容器/管道/电气等）
        department: 所属部门
        location: 安装位置
        manufacturer: 制造商
        model: 型号
        install_date: 安装日期
        design_life_years: 设计寿命（年）
        last_maintenance_date: 上次维保日期
        maintenance_interval_days: 维保周期（天）
        next_maintenance_date: 下次维保日期
        overhaul_interval_hours: 大修周期（运行小时）
        running_hours: 累计运行小时
        last_overhaul_hours: 上次大修时的运行小时
        environment_risk: 运行环境风险 (0.0-1.0)
        status: 当前状态
        maintenance_history: 维保历史
        failure_history: 故障历史
    """
    equipment_id: str
    name: str
    equipment_type: str = ""
    department: str = ""
    location: str = ""
    manufacturer: str = ""
    model: str = ""
    install_date: Optional[date] = None
    design_life_years: int = 15
    last_maintenance_date: Optional[date] = None
    maintenance_interval_days: int = 90
    next_maintenance_date: Optional[date] = None
    overhaul_interval_hours: int = 8000
    running_hours: float = 0.0
    last_overhaul_hours: float = 0.0
    environment_risk: float = 0.3
    status: EquipmentStatus = EquipmentStatus.NORMAL
    maintenance_history: List[MaintenanceRecord] = field(default_factory=list)
    failure_history: List[FailureRecord] = field(default_factory=list)


# =========================
# 设备风险评分引擎
# =========================


class EquipmentRiskScorer:
    """
    设备风险评分引擎。

    综合四个维度计算 0.0-1.0 的风险评分。

    使用方式:
        scorer = EquipmentRiskScorer()
        score = scorer.compute(equipment)
    """

    def __init__(self):
        pass

    def compute(self, eq: EquipmentProfile) -> float:
        """
        计算设备综合风险评分。

        Args:
            eq: 设备档案

        Returns:
            风险评分 0.0-1.0
        """
        now = datetime.now()

        failure_score = self._score_failures(eq.failure_history, now)
        maint_score = self._score_maintenance(eq, now)
        age_score = self._score_age(eq)
        env_score = eq.environment_risk

        total = (
            failure_score * W_EQ_FAILURE
            + maint_score * W_EQ_MAINTENANCE
            + age_score * W_EQ_AGE
            + env_score * W_EQ_ENV
        )

        logger.debug(
            f"[EquipRisk] {eq.equipment_id}: "
            f"failure={failure_score:.2f}, maint={maint_score:.2f}, "
            f"age={age_score:.2f}, env={env_score:.2f} → {total:.4f}"
        )

        return round(total, 4)

    def _score_failures(
        self, failures: List[FailureRecord], now: datetime
    ) -> float:
        """
        故障频率评分（指数衰减加权）。

        近期的严重故障权重最高。
        """
        if not failures:
            return 0.0

        severity_weights = {"critical": 1.0, "major": 0.7, "minor": 0.4}
        total_weight = 0.0

        for f in failures:
            days_ago = max((now - f.occurred_at).days, 0)
            # 90天半衰期
            time_factor = math.exp(-days_ago / 90.0)
            sev_factor = severity_weights.get(f.severity, 0.5)
            total_weight += sev_factor * time_factor

        # 归一化（3次 critical 在 0 天 = 1.0）
        return min(total_weight / 3.0, 1.0)

    def _score_maintenance(self, eq: EquipmentProfile, now: datetime) -> float:
        """
        维保状态评分。

        逾期维保/临近大修 → 高分（高风险）。
        """
        score = 0.0
        today = now.date()

        # 检查维保逾期
        if eq.next_maintenance_date:
            days_until = (eq.next_maintenance_date - today).days
            if days_until < 0:
                # 已逾期
                overdue_days = abs(days_until)
                score += min(overdue_days / eq.maintenance_interval_days, 1.0) * 0.6
            elif days_until <= MAINTENANCE_WARN_DAYS:
                score += 0.3

        # 检查大修阈值
        if eq.overhaul_interval_hours > 0:
            hours_since_overhaul = eq.running_hours - eq.last_overhaul_hours
            overhaul_ratio = hours_since_overhaul / eq.overhaul_interval_hours
            if overhaul_ratio >= OVERHAUL_RATIO_WARN:
                # 超过 80% 大修周期
                score += min((overhaul_ratio - 0.5) * 2.0, 1.0) * 0.4

        return min(score, 1.0)

    def _score_age(self, eq: EquipmentProfile) -> float:
        """
        设备役龄评分。

        服役年限 / 设计寿命 → 0.0-1.0。
        """
        if not eq.install_date or eq.design_life_years <= 0:
            return 0.0

        years_in_service = (date.today() - eq.install_date).days / 365.25
        age_ratio = years_in_service / eq.design_life_years

        # 前 50% 寿命风险很低，之后指数增长
        if age_ratio <= 0.5:
            return 0.0
        elif age_ratio >= 1.0:
            return 1.0
        else:
            # 0.5-1.0 之间线性增长
            return (age_ratio - 0.5) * 2.0

    @staticmethod
    def risk_level(score: float) -> str:
        """风险等级。"""
        if score >= EQUIP_RISK_HIGH:
            return "high"
        elif score >= EQUIP_RISK_MEDIUM:
            return "medium"
        return "low"


# =========================
# 设备管理器
# =========================


class EquipmentManager:
    """
    设备全生命周期管理器。

    使用方式:
        manager = EquipmentManager()
        await manager.load_all()
        alerts = manager.get_maintenance_alerts()
    """

    def __init__(self):
        self._scorer = EquipmentRiskScorer()
        self._equipment: Dict[str, EquipmentProfile] = {}
        self._loaded = False

    # ---- 数据加载 ----

    async def load_all(self) -> List[EquipmentProfile]:
        """加载所有设备档案。"""
        if self._loaded:
            return list(self._equipment.values())

        equipment = self._load_mock()
        for eq in equipment:
            self._equipment[eq.equipment_id] = eq

        self._loaded = True
        logger.info(f"[EquipManager] 加载 {len(equipment)} 台设备")
        return equipment

    async def get_equipment(self, equipment_id: str) -> Optional[EquipmentProfile]:
        """获取指定设备。"""
        if not self._loaded:
            await self.load_all()
        return self._equipment.get(equipment_id)

    def _load_mock(self) -> List[EquipmentProfile]:
        """从 mock_equipment.json 加载 Mock 数据。"""
        mock_file = get_mock_path("mock_equipment.json")
        if not mock_file.exists():
            logger.warning(f"Mock 设备数据文件不存在: {mock_file}")
            return []

        with open(mock_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        equipment = []
        for eq_data in data.get("equipment", []):
            # 解析维保历史
            maint_history = []
            for m in eq_data.get("maintenance_history", []):
                maint_history.append(MaintenanceRecord(
                    record_id=m["record_id"],
                    record_type=m["record_type"],
                    performed_at=datetime.fromisoformat(m["performed_at"]),
                    description=m.get("description", ""),
                    cost=m.get("cost", 0.0),
                    downtime_hours=m.get("downtime_hours", 0.0),
                    technician=m.get("technician", ""),
                    parts_replaced=m.get("parts_replaced", []),
                ))

            # 解析故障历史
            failure_history = []
            for f in eq_data.get("failure_history", []):
                failure_history.append(FailureRecord(
                    failure_id=f["failure_id"],
                    failure_type=f["failure_type"],
                    occurred_at=datetime.fromisoformat(f["occurred_at"]),
                    severity=f["severity"],
                    description=f.get("description", ""),
                    downtime_hours=f.get("downtime_hours", 0.0),
                    root_cause=f.get("root_cause", ""),
                    resolved=f.get("resolved", True),
                ))

            equipment.append(EquipmentProfile(
                equipment_id=eq_data["equipment_id"],
                name=eq_data["name"],
                equipment_type=eq_data.get("equipment_type", ""),
                department=eq_data.get("department", ""),
                location=eq_data.get("location", ""),
                manufacturer=eq_data.get("manufacturer", ""),
                model=eq_data.get("model", ""),
                install_date=(
                    date.fromisoformat(eq_data["install_date"])
                    if eq_data.get("install_date") else None
                ),
                design_life_years=eq_data.get("design_life_years", 15),
                last_maintenance_date=(
                    date.fromisoformat(eq_data["last_maintenance_date"])
                    if eq_data.get("last_maintenance_date") else None
                ),
                maintenance_interval_days=eq_data.get("maintenance_interval_days", 90),
                next_maintenance_date=(
                    date.fromisoformat(eq_data["next_maintenance_date"])
                    if eq_data.get("next_maintenance_date") else None
                ),
                overhaul_interval_hours=eq_data.get("overhaul_interval_hours", 8000),
                running_hours=eq_data.get("running_hours", 0.0),
                last_overhaul_hours=eq_data.get("last_overhaul_hours", 0.0),
                environment_risk=eq_data.get("environment_risk", 0.3),
                status=EquipmentStatus(eq_data.get("status", "normal")),
                maintenance_history=maint_history,
                failure_history=failure_history,
            ))

        return equipment

    # ---- 风险评分 ----

    def compute_risk_score(self, eq: EquipmentProfile) -> float:
        """计算设备风险评分。"""
        return self._scorer.compute(eq)

    def get_high_risk_equipment(self) -> List[EquipmentProfile]:
        """获取高风险设备。"""
        return [
            eq for eq in self._equipment.values()
            if self.compute_risk_score(eq) >= EQUIP_RISK_HIGH
        ]

    # ---- 预警管理 ----

    def get_maintenance_alerts(self) -> List[Dict[str, Any]]:
        """
        获取维保预警列表。

        预警类型:
            - maintenance_due: 维保到期（7天内）
            - maintenance_overdue: 维保已逾期
            - overhaul_due: 大修到期
            - high_risk: 高风险设备

        Returns:
            预警列表
        """
        today = date.today()
        alerts = []

        for eq in self._equipment.values():
            # 维保到期预警
            if eq.next_maintenance_date:
                days_until = (eq.next_maintenance_date - today).days
                if days_until < 0:
                    alerts.append({
                        "equipment_id": eq.equipment_id,
                        "name": eq.name,
                        "alert_type": "maintenance_overdue",
                        "severity": "high",
                        "message": (
                            f"设备 {eq.name} 维保已逾期 {abs(days_until)} 天"
                        ),
                        "days_overdue": abs(days_until),
                    })
                elif days_until <= MAINTENANCE_WARN_DAYS:
                    alerts.append({
                        "equipment_id": eq.equipment_id,
                        "name": eq.name,
                        "alert_type": "maintenance_due",
                        "severity": "medium",
                        "message": (
                            f"设备 {eq.name} 维保将于 {days_until} 天后到期"
                        ),
                        "days_until": days_until,
                    })

            # 大修预警
            if eq.overhaul_interval_hours > 0:
                hours_since = eq.running_hours - eq.last_overhaul_hours
                overhaul_ratio = hours_since / eq.overhaul_interval_hours
                if overhaul_ratio >= OVERHAUL_RATIO_WARN:
                    alerts.append({
                        "equipment_id": eq.equipment_id,
                        "name": eq.name,
                        "alert_type": "overhaul_due",
                        "severity": "high" if overhaul_ratio >= 0.95 else "medium",
                        "message": (
                            f"设备 {eq.name} 大修周期已完成 "
                            f"{overhaul_ratio:.0%}"
                        ),
                        "overhaul_ratio": round(overhaul_ratio, 4),
                    })

            # 高风险设备预警
            risk_score = self.compute_risk_score(eq)
            if risk_score >= EQUIP_RISK_HIGH:
                alerts.append({
                    "equipment_id": eq.equipment_id,
                    "name": eq.name,
                    "alert_type": "high_risk",
                    "severity": "high",
                    "message": (
                        f"设备 {eq.name} 综合风险评分 {risk_score:.0%}，"
                        f"建议重点关注"
                    ),
                    "risk_score": risk_score,
                })

        # 按严重程度排序
        severity_order = {"high": 0, "medium": 1, "low": 2}
        alerts.sort(key=lambda a: severity_order.get(a["severity"], 99))

        return alerts

    def get_failure_frequency(
        self, equipment_id: str, months: int = 12
    ) -> Dict[str, Any]:
        """
        获取设备故障频率统计。

        Args:
            equipment_id: 设备编号
            months: 统计月数

        Returns:
            故障统计信息
        """
        eq = self._equipment.get(equipment_id)
        if not eq:
            return {"error": f"设备不存在: {equipment_id}"}

        cutoff = datetime.now() - timedelta(days=months * 30)
        recent = [f for f in eq.failure_history if f.occurred_at >= cutoff]

        by_type: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}
        total_downtime = 0.0

        for f in recent:
            by_type[f.failure_type] = by_type.get(f.failure_type, 0) + 1
            by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
            total_downtime += f.downtime_hours

        return {
            "equipment_id": equipment_id,
            "period_months": months,
            "total_failures": len(recent),
            "by_type": by_type,
            "by_severity": by_severity,
            "total_downtime_hours": round(total_downtime, 1),
            "mtbf_days": round(
                (months * 30) / max(len(recent), 1), 1
            ),  # 平均故障间隔
        }

    def get_equipment_status_summary(self) -> Dict[str, int]:
        """按状态统计设备数量。"""
        summary: Dict[str, int] = {}
        for eq in self._equipment.values():
            status = eq.status.value
            summary[status] = summary.get(status, 0) + 1
        return summary

    def get_department_equipment_risk(self) -> Dict[str, Any]:
        """按部门统计设备风险分布。"""
        depts: Dict[str, Dict[str, Any]] = {}
        for eq in self._equipment.values():
            dept = eq.department or "未分配"
            if dept not in depts:
                depts[dept] = {
                    "total": 0, "high_risk": 0, "medium_risk": 0,
                    "low_risk": 0, "avg_score": 0.0, "scores": [],
                }
            depts[dept]["total"] += 1
            score = self.compute_risk_score(eq)
            depts[dept]["scores"].append(score)

        for dept in depts.values():
            scores = dept.pop("scores")
            dept["avg_score"] = round(sum(scores) / len(scores), 4)
            for s in scores:
                if s >= EQUIP_RISK_HIGH:
                    dept["high_risk"] += 1
                elif s >= EQUIP_RISK_MEDIUM:
                    dept["medium_risk"] += 1
                else:
                    dept["low_risk"] += 1

        return depts
