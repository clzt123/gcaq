"""
员工安全画像引擎

实现技术方案功能 9：
    - 员工安全档案数据模型 (t_employee_profile 表结构)
    - 风险评分算法（综合违章记录、资质状态、培训完成度）
    - 员工-违章关系图构建（用于 GraphSAGE 等图学习算法）

风险评分维度（权重）:
    1. 违章历史 (40%): 违章次数、严重程度、时间衰减
    2. 资质状态 (30%): 证书过期、资质缺失
    3. 培训完成度 (20%): 安全培训完成率
    4. 岗位风险 (10%): 所在岗位的固有风险等级

使用方式:
    manager = ProfileManager()
    profile = await manager.get_profile("EMP_001")
    score = manager.compute_risk_score(profile)
    if score > 0.7:
        # 高风险员工 → 重点关注
"""
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils import get_mock_path

logger = logging.getLogger(__name__)

# =========================
# 常量
# =========================

# 风险等级阈值
RISK_HIGH_THRESHOLD = 0.70     # 高风险
RISK_MEDIUM_THRESHOLD = 0.40   # 中风险
# < RISK_MEDIUM_THRESHOLD → 低风险

# 评分权重
WEIGHT_VIOLATION = 0.40    # 违章历史
WEIGHT_CERTIFICATION = 0.30  # 资质状态
WEIGHT_TRAINING = 0.20     # 培训完成度
WEIGHT_POSITION = 0.10     # 岗位风险

# 时间衰减参数
VIOLATION_DECAY_DAYS = 180  # 违章记录半衰期（天）
CERT_EXPIRY_WARN_DAYS = 30  # 证书即将过期预警天数


class RiskLevel(str, Enum):
    """员工风险等级"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CertStatus(str, Enum):
    """资质状态"""
    VALID = "valid"
    EXPIRING = "expiring"      # 即将过期
    EXPIRED = "expired"
    MISSING = "missing"        # 未取得


# =========================
# 数据模型
# =========================


@dataclass
class ViolationRecord:
    """
    违章记录。

    参考: 技术方案文档 t_employee_violation 表
    """
    violation_id: str
    violation_type: str          # e.g., "no_hardhat", "smoking", "unauthorized_entry"
    severity: str                # "high" / "medium" / "low"
    occurred_at: datetime        # 违章时间
    description: str = ""
    hazard_report_id: str = ""   # 关联的隐患报告 ID
    penalty: str = ""            # 处罚措施
    resolved: bool = False


@dataclass
class Certification:
    """
    资质/证书。

    参考: 技术方案文档 t_employee_certification 表
    """
    cert_id: str
    cert_type: str               # e.g., "特种作业操作证", "电工证", "焊工证"
    issue_date: date
    expiry_date: date
    issuing_authority: str = ""
    status: CertStatus = CertStatus.VALID


@dataclass
class TrainingRecord:
    """
    培训记录。
    """
    training_id: str
    training_name: str           # e.g., "动火作业安全培训", "化学品防护培训"
    completed_at: Optional[datetime] = None
    required: bool = True
    valid_until: Optional[date] = None


@dataclass
class EmployeeProfile:
    """
    员工安全档案。

    参考: 技术方案文档附录 A t_employee_profile 表结构

    Attributes:
        employee_id: 员工工号
        name: 姓名
        department: 部门
        position: 岗位
        position_risk: 岗位固有风险等级 (0.0-1.0)
        hire_date: 入职日期
        violations: 违章记录列表
        certifications: 资质/证书列表
        trainings: 培训记录列表
        metadata: 扩展元数据
    """
    employee_id: str
    name: str
    department: str = ""
    position: str = ""
    position_risk: float = 0.3    # 岗位固有风险 (0.0-1.0)
    hire_date: Optional[date] = None
    violations: List[ViolationRecord] = field(default_factory=list)
    certifications: List[Certification] = field(default_factory=list)
    trainings: List[TrainingRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# =========================
# 风险评分引擎
# =========================


class RiskScorer:
    """
    员工风险评分引擎。

    综合四个维度计算 0.0-1.0 的风险评分:
        1. 违章历史 (40%): 时间加权违章频率
        2. 资质状态 (30%): 证书过期/缺失比例
        3. 培训完成度 (20%): 必训项目完成率
        4. 岗位风险 (10%): 岗位固有风险等级

    使用方式:
        scorer = RiskScorer()
        score = scorer.compute(profile)
        level = scorer.risk_level(score)
    """

    def __init__(
        self,
        w_violation: float = WEIGHT_VIOLATION,
        w_cert: float = WEIGHT_CERTIFICATION,
        w_training: float = WEIGHT_TRAINING,
        w_position: float = WEIGHT_POSITION,
    ):
        self.w_violation = w_violation
        self.w_cert = w_cert
        self.w_training = w_training
        self.w_position = w_position

    def compute(self, profile: EmployeeProfile) -> float:
        """
        计算员工综合风险评分。

        Args:
            profile: 员工安全档案

        Returns:
            风险评分 0.0-1.0（越高越危险）
        """
        now = datetime.now()

        # 维度 1: 违章历史 (时间衰减加权)
        violation_score = self._score_violations(profile.violations, now)

        # 维度 2: 资质状态
        cert_score = self._score_certifications(profile.certifications, now)

        # 维度 3: 培训完成度
        training_score = self._score_trainings(profile.trainings, now)

        # 维度 4: 岗位风险
        position_score = profile.position_risk

        # 加权综合
        total = (
            violation_score * self.w_violation
            + cert_score * self.w_cert
            + training_score * self.w_training
            + position_score * self.w_position
        )

        logger.debug(
            f"[RiskScorer] {profile.employee_id}: "
            f"violation={violation_score:.2f}, cert={cert_score:.2f}, "
            f"training={training_score:.2f}, position={position_score:.2f} "
            f"→ total={total:.4f}"
        )

        return round(total, 4)

    def _score_violations(
        self, violations: List[ViolationRecord], now: datetime
    ) -> float:
        """
        违章历史评分（时间衰减加权）。

        越近的违章权重越高，严重的违章权重更高。
        使用指数衰减: weight = severity_weight × exp(-days / DECAY_DAYS)

        Args:
            violations: 违章记录列表
            now: 当前时间

        Returns:
            违章评分 0.0-1.0
        """
        if not violations:
            return 0.0

        severity_weights = {"high": 1.0, "medium": 0.6, "low": 0.3}

        total_weight = 0.0
        for v in violations:
            days_ago = (now - v.occurred_at).days
            # 时间衰减
            time_factor = math.exp(-days_ago / VIOLATION_DECAY_DAYS)
            # 严重程度
            sev_factor = severity_weights.get(v.severity, 0.5)
            total_weight += sev_factor * time_factor

        # 归一化：最多 5 次严重违章在 0 天时达到 1.0
        max_score = 5.0
        return min(total_weight / max_score, 1.0)

    def _score_certifications(
        self, certs: List[Certification], now: datetime
    ) -> float:
        """
        资质状态评分。

        规则:
            - 有过期证书 → 高分（高风险）
            - 有即将过期证书 → 中分
            - 全部有效 → 0 分
            - 缺少必要资质 → 高分（高风险）

        Args:
            certs: 资质列表
            now: 当前时间

        Returns:
            资质风险评分 0.0-1.0
        """
        if not certs:
            return 0.8  # 无任何资质记录 → 高风险

        today = now.date()
        total = len(certs)
        expired = 0
        expiring = 0

        for c in certs:
            if c.expiry_date < today:
                expired += 1
            elif (c.expiry_date - today).days <= CERT_EXPIRY_WARN_DAYS:
                expiring += 1

        # 计算过期/即将过期比例
        expired_ratio = expired / total
        expiring_ratio = expiring / total

        # 过期严重于即将过期
        score = expired_ratio * 1.0 + expiring_ratio * 0.5
        return min(score, 1.0)

    def _score_trainings(
        self, trainings: List[TrainingRecord], now: datetime
    ) -> float:
        """
        培训完成度评分。

        规则:
            - 必训项目全部完成 → 0 分
            - 存在未完成的必训项目 → 按比例计分

        Args:
            trainings: 培训记录列表
            now: 当前时间

        Returns:
            培训缺失评分 0.0-1.0
        """
        required = [t for t in trainings if t.required]
        if not required:
            return 0.0

        completed = sum(1 for t in required if t.completed_at is not None)
        incomplete_ratio = 1.0 - (completed / len(required))
        return incomplete_ratio

    @staticmethod
    def risk_level(score: float) -> RiskLevel:
        """
        根据评分确定风险等级。

        Args:
            score: 风险评分 0.0-1.0

        Returns:
            RiskLevel 枚举值
        """
        if score >= RISK_HIGH_THRESHOLD:
            return RiskLevel.HIGH
        elif score >= RISK_MEDIUM_THRESHOLD:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

    @staticmethod
    def risk_label(score: float) -> str:
        """获取风险等级中文标签。"""
        level = RiskScorer.risk_level(score)
        labels = {
            RiskLevel.HIGH: f"高风险 ({score:.0%})",
            RiskLevel.MEDIUM: f"中风险 ({score:.0%})",
            RiskLevel.LOW: f"低风险 ({score:.0%})",
        }
        return labels[level]


# =========================
# 员工画像管理器
# =========================


class ProfileManager:
    """
    员工安全画像管理器。

    管理员工档案的加载、评分和关系图构建。
    支持 Mock 数据和真实 HR 系统对接。

    使用方式:
        manager = ProfileManager()
        profiles = await manager.load_all()
        for p in profiles:
            score = manager.compute_risk_score(p)
            if score > 0.7:
                print(f"高风险员工: {p.name}")
    """

    def __init__(self):
        self._scorer = RiskScorer()
        self._profiles: Dict[str, EmployeeProfile] = {}
        self._loaded = False

    # ---- 数据加载 ----

    async def load_all(self) -> List[EmployeeProfile]:
        """
        加载所有员工档案。

        优先从 Mock 数据加载，后续可扩展 HR 系统对接。

        Returns:
            EmployeeProfile 列表
        """
        if self._loaded:
            return list(self._profiles.values())

        profiles = self._load_mock_profiles()
        for p in profiles:
            self._profiles[p.employee_id] = p

        self._loaded = True
        logger.info(
            f"[ProfileManager] 加载 {len(profiles)} 份员工档案"
        )
        return profiles

    async def get_profile(self, employee_id: str) -> Optional[EmployeeProfile]:
        """
        获取指定员工档案。

        Args:
            employee_id: 员工工号

        Returns:
            EmployeeProfile 或 None
        """
        if not self._loaded:
            await self.load_all()
        return self._profiles.get(employee_id)

    def _load_mock_profiles(self) -> List[EmployeeProfile]:
        """从 mock_employees.json 加载 Mock 员工数据。"""
        mock_file = get_mock_path("mock_employees.json")
        if not mock_file.exists():
            logger.warning(f"Mock 员工数据文件不存在: {mock_file}")
            return []

        with open(mock_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        profiles = []
        for emp in data.get("employees", []):
            # 解析违章记录
            violations = []
            for v in emp.get("violations", []):
                violations.append(ViolationRecord(
                    violation_id=v["violation_id"],
                    violation_type=v["violation_type"],
                    severity=v["severity"],
                    occurred_at=datetime.fromisoformat(v["occurred_at"]),
                    description=v.get("description", ""),
                    hazard_report_id=v.get("hazard_report_id", ""),
                    penalty=v.get("penalty", ""),
                    resolved=v.get("resolved", False),
                ))

            # 解析资质
            certs = []
            for c in emp.get("certifications", []):
                certs.append(Certification(
                    cert_id=c["cert_id"],
                    cert_type=c["cert_type"],
                    issue_date=date.fromisoformat(c["issue_date"]),
                    expiry_date=date.fromisoformat(c["expiry_date"]),
                    issuing_authority=c.get("issuing_authority", ""),
                    status=CertStatus(c.get("status", "valid")),
                ))

            # 解析培训记录
            trainings = []
            for t in emp.get("trainings", []):
                completed = t.get("completed_at")
                valid_until = t.get("valid_until")
                trainings.append(TrainingRecord(
                    training_id=t["training_id"],
                    training_name=t["training_name"],
                    completed_at=(
                        datetime.fromisoformat(completed)
                        if completed else None
                    ),
                    required=t.get("required", True),
                    valid_until=(
                        date.fromisoformat(valid_until)
                        if valid_until else None
                    ),
                ))

            profiles.append(EmployeeProfile(
                employee_id=emp["employee_id"],
                name=emp["name"],
                department=emp.get("department", ""),
                position=emp.get("position", ""),
                position_risk=emp.get("position_risk", 0.3),
                hire_date=(
                    date.fromisoformat(emp["hire_date"])
                    if emp.get("hire_date") else None
                ),
                violations=violations,
                certifications=certs,
                trainings=trainings,
            ))

        return profiles

    # ---- 风险评分 ----

    def compute_risk_score(self, profile: EmployeeProfile) -> float:
        """计算员工风险评分。"""
        return self._scorer.compute(profile)

    def get_risk_level(self, profile: EmployeeProfile) -> RiskLevel:
        """获取员工风险等级。"""
        score = self.compute_risk_score(profile)
        return RiskScorer.risk_level(score)

    # ---- 批量分析 ----

    def get_high_risk_employees(self) -> List[EmployeeProfile]:
        """获取所有高风险员工。"""
        return [
            p for p in self._profiles.values()
            if self.get_risk_level(p) == RiskLevel.HIGH
        ]

    def get_department_risk_summary(self) -> Dict[str, Dict[str, Any]]:
        """
        按部门统计风险分布。

        Returns:
            {department: {"high": N, "medium": N, "low": N, "avg_score": float}}
        """
        depts: Dict[str, Dict[str, Any]] = {}
        for p in self._profiles.values():
            dept = p.department or "未分配"
            if dept not in depts:
                depts[dept] = {
                    "high": 0, "medium": 0, "low": 0,
                    "total": 0, "scores": [],
                }
            depts[dept]["total"] += 1
            level = self.get_risk_level(p)
            depts[dept][level.value] += 1
            depts[dept]["scores"].append(self.compute_risk_score(p))

        # 计算平均分
        for dept in depts.values():
            scores = dept.pop("scores")
            dept["avg_score"] = round(sum(scores) / len(scores), 4) if scores else 0.0

        return depts

    def get_violation_stats(self) -> Dict[str, int]:
        """
        违章类型统计。

        Returns:
            {violation_type: count}
        """
        stats: Dict[str, int] = {}
        for p in self._profiles.values():
            for v in p.violations:
                stats[v.violation_type] = stats.get(v.violation_type, 0) + 1
        return dict(sorted(stats.items(), key=lambda x: x[1], reverse=True))

    # ---- 资质检查 ----

    def get_expiring_certs(self, days: int = CERT_EXPIRY_WARN_DAYS) -> List[Dict[str, Any]]:
        """获取即将过期的证书列表。"""
        today = date.today()
        expiring = []
        for p in self._profiles.values():
            for c in p.certifications:
                remaining = (c.expiry_date - today).days
                if 0 <= remaining <= days:
                    expiring.append({
                        "employee_id": p.employee_id,
                        "name": p.name,
                        "cert_type": c.cert_type,
                        "expiry_date": c.expiry_date.isoformat(),
                        "days_remaining": remaining,
                    })
        return sorted(expiring, key=lambda x: x["days_remaining"])
