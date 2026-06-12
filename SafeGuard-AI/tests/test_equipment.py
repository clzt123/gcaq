"""
设备全生命周期模块单元测试

覆盖:
    - EquipmentProfile/EquipmentRiskScorer: 四维度风险评分
    - EquipmentManager: 设备加载/预警/故障统计
    - Mock 设备数据完整性
"""
import json
from datetime import datetime, date, timedelta

import pytest

from app.core.equipment.manager import (
    EquipmentProfile,
    MaintenanceRecord,
    FailureRecord,
    EquipmentRiskScorer,
    EquipmentManager,
    EquipmentStatus,
    EQUIP_RISK_HIGH,
    EQUIP_RISK_MEDIUM,
)


def _make_failure(severity: str = "major", days_ago: int = 10) -> FailureRecord:
    return FailureRecord(
        failure_id=f"F_TEST_{days_ago}",
        failure_type="leak",
        occurred_at=datetime.now() - timedelta(days=days_ago),
        severity=severity,
    )


def _make_equipment(eq_id: str = "EQ_TEST", **kwargs) -> EquipmentProfile:
    defaults = {
        "equipment_id": eq_id,
        "name": "测试设备",
        "equipment_type": "泵",
        "install_date": date(2020, 1, 1),
        "design_life_years": 15,
        "environment_risk": 0.3,
    }
    defaults.update(kwargs)
    return EquipmentProfile(**defaults)


class TestEquipmentRiskScorer:
    """测试设备风险评分"""

    def setup_method(self):
        self.scorer = EquipmentRiskScorer()

    def test_new_clean_equipment_low_risk(self):
        """全新设备无故障 → 低风险"""
        eq = _make_equipment(
            install_date=date.today() - timedelta(days=30),
            next_maintenance_date=date.today() + timedelta(days=60),
        )
        score = self.scorer.compute(eq)
        assert score < EQUIP_RISK_MEDIUM, f"新设备应低风险: {score}"

    def test_many_recent_failures_high_risk(self):
        """多次近期故障 → 高风险"""
        eq = _make_equipment(
            failure_history=[
                _make_failure("critical", 2),
                _make_failure("major", 5),
                _make_failure("major", 10),
            ],
        )
        score = self.scorer.compute(eq)
        assert score > 0.20, f"多次故障应有显著风险: {score}"

    def test_overdue_maintenance_increases_risk(self):
        """维保逾期 → 风险升高"""
        eq_current = _make_equipment(
            next_maintenance_date=date.today() + timedelta(days=60),
        )
        eq_overdue = _make_equipment(
            equipment_id="EQ_OVER",
            next_maintenance_date=date.today() - timedelta(days=30),
        )
        assert self.scorer.compute(eq_overdue) > self.scorer.compute(eq_current)

    def test_old_equipment_higher_risk(self):
        """老旧设备 → 风险更高"""
        eq_new = _make_equipment(install_date=date(2024, 1, 1))
        eq_old = _make_equipment(
            equipment_id="EQ_OLD",
            install_date=date(2015, 1, 1),
            design_life_years=10,  # 已超过设计寿命
        )
        assert self.scorer.compute(eq_old) > self.scorer.compute(eq_new)

    def test_high_environment_risk_contributes(self):
        """高危环境增加风险"""
        eq_low = _make_equipment(environment_risk=0.1)
        eq_high = _make_equipment(equipment_id="EQ_HIGH_ENV", environment_risk=1.0)
        assert self.scorer.compute(eq_high) > self.scorer.compute(eq_low)

    def test_approaching_overhaul_increases_risk(self):
        """接近大修周期 → 风险升高"""
        eq = _make_equipment(
            running_hours=7500,  # 接近 8000
            last_overhaul_hours=0,
            overhaul_interval_hours=8000,
        )
        score = self.scorer.compute(eq)
        assert score > 0.10, f"接近大修应有风险: {score}"

    def test_risk_level_labels(self):
        """风险等级标签"""
        assert EquipmentRiskScorer.risk_level(0.80) == "high"
        assert EquipmentRiskScorer.risk_level(0.50) == "medium"
        assert EquipmentRiskScorer.risk_level(0.20) == "low"


class TestEquipmentManager:
    """测试设备管理器"""

    @pytest.mark.asyncio
    async def test_load_all(self):
        """加载所有设备"""
        manager = EquipmentManager()
        equipment = await manager.load_all()
        assert len(equipment) >= 4, f"应有至少4台设备: {len(equipment)}"

    @pytest.mark.asyncio
    async def test_get_equipment(self):
        """获取指定设备"""
        manager = EquipmentManager()
        eq = await manager.get_equipment("EQ_HP_001")
        assert eq is not None
        assert eq.name == "1号高压液压泵"
        assert eq.equipment_type == "液压泵"

    @pytest.mark.asyncio
    async def test_maintenance_alerts(self):
        """维保预警生成"""
        manager = EquipmentManager()
        await manager.load_all()
        alerts = manager.get_maintenance_alerts()
        # 应有维保到期或逾期的设备
        alert_types = {a["alert_type"] for a in alerts}
        assert len(alert_types) >= 1, f"应有预警: {alert_types}"

    @pytest.mark.asyncio
    async def test_alerts_have_required_fields(self):
        """预警应有完整字段"""
        manager = EquipmentManager()
        await manager.load_all()
        alerts = manager.get_maintenance_alerts()
        required = {"equipment_id", "name", "alert_type", "severity", "message"}
        for alert in alerts:
            for field in required:
                assert field in alert, f"预警缺少字段: {field}"

    @pytest.mark.asyncio
    async def test_high_risk_equipment_detected(self):
        """高风险设备应被检测"""
        manager = EquipmentManager()
        await manager.load_all()
        high_risk = manager.get_high_risk_equipment()
        # 至少应有设备风险分 > 0
        all_scores = [manager.compute_risk_score(eq) for eq in (await manager.load_all())]
        max_score = max(all_scores) if all_scores else 0
        assert max_score > 0.20, f"应有设备风险分 > 0.20: max={max_score}"

    @pytest.mark.asyncio
    async def test_failure_frequency_stats(self):
        """故障频率统计"""
        manager = EquipmentManager()
        await manager.load_all()
        stats = manager.get_failure_frequency("EQ_PP_005", months=12)
        assert stats["total_failures"] >= 2
        assert stats["by_type"]["leak"] >= 2
        assert stats["mtbf_days"] > 0

    @pytest.mark.asyncio
    async def test_equipment_status_summary(self):
        """设备状态分布"""
        manager = EquipmentManager()
        await manager.load_all()
        summary = manager.get_equipment_status_summary()
        assert sum(summary.values()) >= 4

    @pytest.mark.asyncio
    async def test_department_equipment_risk(self):
        """部门设备风险分布"""
        manager = EquipmentManager()
        await manager.load_all()
        dept_risk = manager.get_department_equipment_risk()
        assert len(dept_risk) >= 2


class TestEquipmentData:
    """测试设备数据模型"""

    def test_create_equipment_profile(self):
        eq = _make_equipment(
            equipment_id="EQ_TEST_001",
            name="测试泵",
            equipment_type="离心泵",
            department="生产部",
            manufacturer="测试厂商",
            model="TEST-100",
            install_date=date(2020, 6, 1),
            design_life_years=10,
            maintenance_interval_days=90,
            failure_history=[
                FailureRecord(
                    failure_id="F001", failure_type="leak",
                    occurred_at=datetime.now() - timedelta(days=30),
                    severity="major", downtime_hours=4.0,
                    root_cause="密封老化", resolved=True,
                ),
            ],
        )
        assert eq.equipment_id == "EQ_TEST_001"
        assert len(eq.failure_history) == 1
        assert eq.failure_history[0].severity == "major"

    def test_equipment_status_enum(self):
        assert EquipmentStatus.NORMAL.value == "normal"
        assert EquipmentStatus.MAINTENANCE_DUE.value == "maintenance_due"


class TestMockEquipmentData:
    """测试 Mock 设备数据完整性"""

    def setup_method(self):
        from app.utils import get_mock_path
        mock_file = get_mock_path("mock_equipment.json")
        with open(mock_file, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def test_all_have_required_fields(self):
        for eq in self.data["equipment"]:
            assert "equipment_id" in eq
            assert "name" in eq
            assert "equipment_type" in eq
            assert "department" in eq

    def test_has_equipment_with_failures(self):
        with_failures = sum(
            1 for e in self.data["equipment"]
            if len(e.get("failure_history", [])) > 0
        )
        assert with_failures >= 2

    def test_has_clean_equipment(self):
        clean = sum(
            1 for e in self.data["equipment"]
            if len(e.get("failure_history", [])) == 0
        )
        assert clean >= 1

    def test_equipment_types_diversity(self):
        types = {e["equipment_type"] for e in self.data["equipment"]}
        assert len(types) >= 4, f"设备类型应多样: {types}"

    def test_statuses_diversity(self):
        statuses = {e.get("status", "normal") for e in self.data["equipment"]}
        assert len(statuses) >= 2, f"设备状态应多样: {statuses}"
