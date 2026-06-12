"""
个性化培训管理器

实现技术方案功能 15 — 个性化培训的统一入口。

流程:
    1. 推荐引擎 → 获取个性化案例推荐
    2. 题目生成器 → 为每个案例生成培训题目
    3. 组装完整培训计划
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.training.recommend_engine import RecommendEngine, RecommendationResult
from app.core.training.question_generator import QuestionGenerator, TrainingQuestion

logger = logging.getLogger(__name__)


@dataclass
class TrainingPlan:
    """
    个性化培训计划。

    Attributes:
        employee_id: 员工工号
        employee_name: 员工姓名
        recommendation: 推荐结果
        questions: 所有生成的培训题目
        total_questions: 题目总数
        estimated_minutes: 预估完成时间（分钟）
    """

    employee_id: str
    employee_name: str
    recommendation: RecommendationResult
    questions: List[TrainingQuestion] = field(default_factory=list)
    total_questions: int = 0
    estimated_minutes: int = 0


class TrainingManager:
    """
    个性化培训管理器。

    协调案例推荐和题目生成，输出完整的培训计划。

    使用方式:
        mgr = TrainingManager()
        plan = await mgr.create_training_plan("EMP_001", cases_per_employee=3)
    """

    def __init__(self):
        """初始化管理器。"""
        self._recommend_engine = RecommendEngine()
        self._question_generator = QuestionGenerator()

    async def create_training_plan(
        self,
        employee_id: str,
        cases_per_employee: int = 3,
        questions_per_case: int = 2,
    ) -> TrainingPlan:
        """
        为指定员工创建个性化培训计划。

        流程:
            1. 推荐引擎推荐事故案例
            2. 为每个案例生成考题
            3. 组装完整培训计划

        Args:
            employee_id: 员工工号
            cases_per_employee: 推荐的案例数量
            questions_per_case: 每个案例生成的题目数量

        Returns:
            TrainingPlan 完整培训计划
        """
        logger.info(f"[TrainingManager] 为员工 {employee_id} 创建培训计划")

        # Step 1: 推荐案例
        recommendation = await self._recommend_engine.recommend(
            employee_id,
            top_n=cases_per_employee,
        )

        # Step 2: 为每个案例生成题目
        all_questions: List[TrainingQuestion] = []
        for case in recommendation.recommended_cases:
            # 获取完整案例数据
            full_case = self._recommend_engine.get_case_by_id(case["case_id"])
            if not full_case:
                continue

            questions = await self._question_generator.generate_questions(
                full_case,
                count=questions_per_case,
            )
            all_questions.extend(questions)

        # Step 3: 组装培训计划
        # 预估时间: 选择题 2 min, 判断题 1 min
        estimated = sum(
            2 if q.question_type == "multiple_choice" else 1
            for q in all_questions
        )

        plan = TrainingPlan(
            employee_id=employee_id,
            employee_name=recommendation.employee_name,
            recommendation=recommendation,
            questions=all_questions,
            total_questions=len(all_questions),
            estimated_minutes=estimated,
        )

        logger.info(
            f"[TrainingManager] 培训计划创建完成: "
            f"{plan.employee_name} → {len(recommendation.recommended_cases)} 案例, "
            f"{plan.total_questions} 道题, 预估 {plan.estimated_minutes} min"
        )
        return plan

    async def create_department_training_plans(
        self,
        department: str,
        cases_per_employee: int = 3,
        questions_per_case: int = 2,
    ) -> List[TrainingPlan]:
        """
        为整个部门创建培训计划。

        Args:
            department: 部门名称
            cases_per_employee: 每名员工的案例数
            questions_per_case: 每个案例的题目数

        Returns:
            TrainingPlan 列表
        """
        logger.info(f"[TrainingManager] 为部门 '{department}' 创建批量培训计划")

        dept_results = await self._recommend_engine.recommend_by_department(
            department,
            top_n=cases_per_employee,
        )

        plans: List[TrainingPlan] = []
        for result in dept_results:
            plan = await self.create_training_plan(
                result["employee_id"],
                cases_per_employee=cases_per_employee,
                questions_per_case=questions_per_case,
            )
            plans.append(plan)

        return plans
