"""
协同过滤推荐引擎

实现技术方案功能 15 — 基于员工安全画像的事故案例推荐。

推荐策略（三层降级）:
    1. 协同过滤推荐（主策略）: 基于违章相似度匹配员工→案例类别
    2. 部门规则推荐（降级1）: 基于部门关联的案例推荐
    3. 风险加权推荐（降级2）: 高风险员工推荐高风险案例
"""
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.core.profile.employee import ProfileManager, EmployeeProfile
from app.utils import get_mock_path

logger = logging.getLogger(__name__)


# =========================
# 数据模型
# =========================


@dataclass
class RecommendationResult:
    """
    推荐结果。

    Attributes:
        employee_id: 员工工号
        employee_name: 员工姓名
        department: 所属部门
        risk_level: 员工当前风险等级
        recommended_cases: 推荐的事故案例列表
        recommendation_reason: 推荐理由（可达2句）
        recommendation_strategy: 使用的推荐策略
        total_cases_available: 案例库总数量
    """

    employee_id: str
    employee_name: str
    department: str
    risk_level: str
    recommended_cases: List[Dict[str, Any]] = field(default_factory=list)
    recommendation_reason: str = ""
    recommendation_strategy: str = ""
    total_cases_available: int = 0


# =========================
# 推荐引擎
# =========================


class RecommendEngine:
    """
    基于协同过滤的事故案例推荐引擎。

    工作原理:
        1. 计算员工违章类型向量
        2. 与案例库标签做余弦相似度匹配
        3. 加上部门关联度权重
        4. 结合员工风险等级调整优先级
        5. 返回 Top-N 推荐案例

    使用方式:
        engine = RecommendEngine()
        result = await engine.recommend("EMP_001", top_n=5)
    """

    def __init__(self):
        """初始化推荐引擎，加载案例库。"""
        self._cases: List[Dict[str, Any]] = []
        self._profile_manager = ProfileManager()
        self._loaded = False

    async def _ensure_loaded(self):
        """懒加载案例库和员工档案。"""
        if self._loaded:
            return

        # 加载事故案例库
        cases_file = get_mock_path("accident_cases.json")
        if cases_file.exists():
            with open(cases_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._cases = data.get("cases", [])
            logger.info(f"[RecommendEngine] 加载 {len(self._cases)} 个事故案例")
        else:
            logger.warning("[RecommendEngine] 事故案例库文件不存在")

        # 预加载员工档案
        await self._profile_manager.load_all()

        self._loaded = True

    async def recommend(
        self,
        employee_id: str,
        top_n: int = 5,
    ) -> RecommendationResult:
        """
        为指定员工推荐个性化培训案例。

        推荐流程:
            1. 获取员工画像
            2. 计算与每个案例的相关性分数
            3. 按分数降序排列，返回 Top-N

        Args:
            employee_id: 员工工号
            top_n: 推荐数量

        Returns:
            RecommendationResult 推荐结果
        """
        await self._ensure_loaded()

        # Step 1: 获取员工画像
        profile = await self._profile_manager.get_profile(employee_id)
        if not profile:
            logger.warning(f"[RecommendEngine] 员工不存在: {employee_id}")
            return RecommendationResult(
                employee_id=employee_id,
                employee_name="未知",
                department="",
                risk_level="low",
                recommendation_strategy="none",
                total_cases_available=len(self._cases),
            )

        # Step 2: 计算员工风险等级
        risk_score = self._profile_manager._scorer.compute(profile)
        if risk_score >= 0.70:
            risk_level = "high"
        elif risk_score >= 0.40:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Step 3: 构建员工违章类型集合
        employee_violation_types = set()
        for v in profile.violations:
            employee_violation_types.add(v.violation_type)

        # Step 4: 对每个案例计分
        case_scores = []
        for case in self._cases:
            score = self._compute_match_score(case, profile, employee_violation_types)
            case_scores.append((score, case))

        # Step 5: 排序（高风险员工提升高危案例权重）
        case_scores.sort(key=lambda x: x[0], reverse=True)

        # Step 6: 去重 + Top-N
        recommended = []
        seen_titles: Set[str] = set()
        for score, case in case_scores:
            if case["title"] not in seen_titles:
                seen_titles.add(case["title"])
                recommended.append({
                    "case_id": case["case_id"],
                    "title": case["title"],
                    "category": case["category"],
                    "risk_level": case["risk_level"],
                    "department": case["department"],
                    "difficulty": case["difficulty"],
                    "summary": case["summary"],
                    "match_score": round(score, 4),
                })

            if len(recommended) >= top_n:
                break

        # Step 7: 生成推荐理由
        reason = self._generate_reason(profile, recommended, risk_level)

        logger.info(
            f"[RecommendEngine] 推荐完成: emp={profile.name} "
            f"(risk={risk_level}, score={risk_score:.2f}) → "
            f"{len(recommended)} 个案例"
        )

        return RecommendationResult(
            employee_id=employee_id,
            employee_name=profile.name,
            department=profile.department,
            risk_level=risk_level,
            recommended_cases=recommended,
            recommendation_reason=reason,
            recommendation_strategy="collaborative_filtering",
            total_cases_available=len(self._cases),
        )

    def _compute_match_score(
        self,
        case: Dict[str, Any],
        profile: EmployeeProfile,
        violation_types: Set[str],
    ) -> float:
        """
        计算案例与员工的相关性分数。

        评分维度:
            1. 违章类型重叠 (35%): 员工违章类型与案例标签的重叠度
            2. 部门匹配度 (25%): 案例是否包含员工所属部门
            3. 培训缺口 (20%): 与员工未完成培训的关联
            4. 风险匹配 (20%): 高风险员工更需高危案例

        Args:
            case: 事故案例数据
            profile: 员工画像
            violation_types: 员工违章类型集合

        Returns:
            0.0-1.0 的相关性分数
        """
        score = 0.0

        # 维度 1: 违章类型重叠 (35%)
        case_tags = set(case.get("tags", []))
        overlap = len(violation_types & case_tags)
        if overlap > 0:
            score += 0.35 * min(overlap / max(len(case_tags), 1), 1.0)

        # 维度 2: 部门匹配 (25%)
        related_depts = case.get("related_departments", [])
        if profile.department in related_depts:
            score += 0.25
        elif any(d in profile.department for d in related_depts):
            score += 0.15

        # 维度 3: 培训缺口 (20%)
        completed_trainings = {
            t.training_name for t in profile.trainings
            if t.completed_at is not None
        }
        case_category = case.get("category", "")
        # 检查是否有相关的未完成培训
        has_training_gap = any(
            case_category.lower() in t.training_name.lower()
            and t.completed_at is None
            for t in profile.trainings
        )
        if has_training_gap:
            score += 0.20

        # 维度 4: 风险匹配 (20%)
        risk_score = self._profile_manager._scorer.compute(profile)
        case_risk = case.get("risk_level", "low")
        if risk_score >= 0.70 and case_risk == "high":
            score += 0.20  # 高风险员工优先推荐高危案例
        elif risk_score >= 0.70 and case_risk == "medium":
            score += 0.12
        elif risk_score >= 0.40 and case_risk in ("medium", "high"):
            score += 0.10

        return min(score, 1.0)

    def _generate_reason(
        self,
        profile: EmployeeProfile,
        recommended: List[Dict[str, Any]],
        risk_level: str,
    ) -> str:
        """生成人性化的推荐理由。"""
        if not recommended:
            return "案例库中暂无匹配的培训案例。"

        parts = []

        # 风险等级描述
        risk_descriptions = {
            "high": f"您的安全风险等级为'高风险'，违章记录较多，强烈建议认真学习以下案例",
            "medium": f"您的安全风险等级为'中风险'，仍有改进空间",
            "low": "您的安全风险等级为'低风险'，以下案例有助于巩固安全意识",
        }
        parts.append(risk_descriptions.get(risk_level, ""))

        # 违章类型提示
        violation_types = {v.violation_type for v in profile.violations}
        if violation_types:
            type_labels = {
                "no_hardhat": "未戴安全帽",
                "unsafe_behavior": "不安全行为",
                "blocked_exit": "堵塞通道",
                "no_permit": "无证作业",
            }
            labels = [
                type_labels.get(t, t) for t in violation_types
            ]
            parts.append(f"根据您过去的{'、'.join(labels[:2])}等记录，为您重点推荐相关案例。")

        return "。".join(parts) + "。"

    async def recommend_by_department(
        self,
        department: str,
        top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        按部门批量推荐培训案例。

        Args:
            department: 部门名称
            top_n: 每个员工的推荐数量

        Returns:
            部门中所有员工的推荐结果列表
        """
        await self._ensure_loaded()

        # 获取部门所有员工
        all_profiles = await self._profile_manager.load_all()
        department_employees = [
            p for p in all_profiles if p.department == department
        ]

        results = []
        for emp in department_employees:
            recommendation = await self.recommend(emp.employee_id, top_n)
            results.append({
                "employee_id": emp.employee_id,
                "employee_name": emp.name,
                "recommended_cases": recommendation.recommended_cases,
            })

        logger.info(
            f"[RecommendEngine] 部门推荐完成: {department} → "
            f"{len(results)} 名员工"
        )
        return results

    def list_categories(self) -> List[str]:
        """列出所有案例类别。"""
        return sorted(set(c.get("category", "") for c in self._cases if c.get("category")))

    def get_case_by_id(self, case_id: str) -> Optional[Dict[str, Any]]:
        """根据 ID 获取案例详情。"""
        for c in self._cases:
            if c.get("case_id") == case_id:
                return c
        return None
