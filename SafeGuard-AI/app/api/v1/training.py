"""
个性化培训 API 接口

提供培训案例推荐、题目生成、培训计划创建等 RESTful 接口。

接口清单:
    POST /api/v1/training/plan/{employee_id}     — 创建个性化培训计划
    GET  /api/v1/training/plan/{employee_id}      — 查询培训计划
    GET  /api/v1/training/cases/categories         — 查询案例类别
    GET  /api/v1/training/cases/{case_id}          — 查询案例详情
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.training.training_manager import TrainingManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/training", tags=["个性化培训"])


# =========================
# Pydantic 模型
# =========================


class PlanRequest(BaseModel):
    """培训计划创建请求。"""

    cases_per_employee: int = Field(3, ge=1, le=10, description="推荐的案例数量")
    questions_per_case: int = Field(2, ge=1, le=5, description="每个案例的题目数量")


class QuestionResponse(BaseModel):
    """题目响应。"""

    question_type: str = ""
    question: str = ""
    options: List[str] = Field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""
    source_case_id: str = ""
    difficulty: str = ""


class CaseBrief(BaseModel):
    """案例简要信息。"""

    case_id: str = ""
    title: str = ""
    category: str = ""
    risk_level: str = ""
    department: str = ""
    difficulty: str = ""
    summary: str = ""
    match_score: float = 0.0


class TrainingPlanResponse(BaseModel):
    """培训计划响应。"""

    employee_id: str = ""
    employee_name: str = ""
    risk_level: str = ""
    recommendation_reason: str = ""
    recommended_cases: List[CaseBrief] = Field(default_factory=list)
    questions: List[QuestionResponse] = Field(default_factory=list)
    total_questions: int = 0
    estimated_minutes: int = 0
    total_cases_available: int = 0


# =========================
# 路由
# =========================


@router.post("/plan/{employee_id}", response_model=TrainingPlanResponse)
async def create_training_plan(
    employee_id: str,
    request: PlanRequest = PlanRequest(),
) -> TrainingPlanResponse:
    """
    为指定员工创建个性化培训计划。

    包含案例推荐和自动生成的培训题目。

    Args:
        employee_id: 员工工号 (e.g., 'EMP_001')
        request: 可选参数（案例数和题目数）

    Returns:
        TrainingPlanResponse: 完整培训计划
    """
    logger.info(f"[API/Training] 创建培训计划: emp={employee_id}")

    try:
        mgr = TrainingManager()
        plan = await mgr.create_training_plan(
            employee_id=employee_id,
            cases_per_employee=request.cases_per_employee,
            questions_per_case=request.questions_per_case,
        )

        # 组装响应
        cases = [
            CaseBrief(**case) for case in plan.recommendation.recommended_cases
        ]
        questions = [
            QuestionResponse(
                question_type=q.question_type,
                question=q.question,
                options=q.options,
                correct_answer=q.correct_answer,
                explanation=q.explanation,
                source_case_id=q.source_case_id,
                difficulty=q.difficulty,
            )
            for q in plan.questions
        ]

        response = TrainingPlanResponse(
            employee_id=plan.employee_id,
            employee_name=plan.employee_name,
            risk_level=plan.recommendation.risk_level,
            recommendation_reason=plan.recommendation.recommendation_reason,
            recommended_cases=cases,
            questions=questions,
            total_questions=plan.total_questions,
            estimated_minutes=plan.estimated_minutes,
            total_cases_available=plan.recommendation.total_cases_available,
        )

        logger.info(
            f"[API/Training] 培训计划创建成功: {plan.employee_name} "
            f"({plan.total_questions} 题)"
        )
        return response

    except Exception as e:
        logger.error(f"[API/Training] 创建失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"培训计划创建失败: {str(e)}")


@router.get("/cases/categories")
async def list_case_categories() -> dict:
    """
    查询所有事故案例类别。

    Returns:
        dict: 类别列表
    """
    mgr = TrainingManager()
    categories = mgr._recommend_engine.list_categories()
    return {"total": len(categories), "categories": categories}


@router.get("/cases/{case_id}")
async def get_case_detail(case_id: str) -> dict:
    """
    查询事故案例详情。

    Args:
        case_id: 案例 ID

    Returns:
        dict: 案例完整数据

    Raises:
        HTTPException 404: 案例不存在
    """
    mgr = TrainingManager()
    case = mgr._recommend_engine.get_case_by_id(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"案例 {case_id} 不存在")
    return case
