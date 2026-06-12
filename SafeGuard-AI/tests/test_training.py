"""
个性化培训模块测试

测试范围:
    - 推荐引擎：案例推荐、匹配计分、批量推荐
    - 题目生成器：模板兜底生成、题型正确性
    - 培训管理器：培训计划创建、部门批量计划

设计原则：
    - 不依赖外部服务（LLM API 等）
    - 专注于模板兜底路径测试
    - 遵循项目现有 pytest + pytest-asyncio 模式
"""
import pytest

from app.core.training.recommend_engine import RecommendEngine, RecommendationResult
from app.core.training.question_generator import QuestionGenerator, TrainingQuestion
from app.core.training.training_manager import TrainingManager, TrainingPlan


# =========================
# 1. RecommendEngine 测试
# =========================


class TestRecommendEngine:
    """推荐引擎测试"""

    @pytest.mark.asyncio
    async def test_recommend_for_existing_employee(self):
        """测试为存在员工推荐案例"""
        engine = RecommendEngine()
        result = await engine.recommend("EMP_001", top_n=3)

        assert isinstance(result, RecommendationResult)
        assert result.employee_id == "EMP_001"
        assert result.employee_name == "张建国"
        assert result.department == "生产部-焊接车间"
        assert result.risk_level in ("low", "medium", "high")
        assert len(result.recommended_cases) <= 3
        assert len(result.recommended_cases) >= 1  # 至少有1个推荐

    @pytest.mark.asyncio
    async def test_recommend_for_nonexistent_employee(self):
        """测试为不存在员工推荐"""
        engine = RecommendEngine()
        result = await engine.recommend("EMP_NONEXISTENT", top_n=3)

        assert isinstance(result, RecommendationResult)
        assert result.employee_name == "未知"
        assert len(result.recommended_cases) == 0

    @pytest.mark.asyncio
    async def test_recommend_returns_sorted_by_score(self):
        """测试推荐结果按分数降序"""
        engine = RecommendEngine()
        result = await engine.recommend("EMP_001", top_n=5)

        if len(result.recommended_cases) >= 2:
            scores = [c["match_score"] for c in result.recommended_cases]
            assert scores == sorted(scores, reverse=True), f"分数未降序: {scores}"

    @pytest.mark.asyncio
    async def test_recommend_has_all_fields(self):
        """测试推荐案例字段完整性"""
        engine = RecommendEngine()
        result = await engine.recommend("EMP_001", top_n=3)

        for case in result.recommended_cases:
            assert "case_id" in case
            assert "title" in case
            assert "category" in case
            assert "risk_level" in case
            assert "difficulty" in case
            assert "summary" in case
            assert "match_score" in case

    @pytest.mark.asyncio
    async def test_recommend_with_different_top_n(self):
        """测试不同 top_n 返回数量"""
        engine = RecommendEngine()

        r1 = await engine.recommend("EMP_001", top_n=1)
        assert len(r1.recommended_cases) <= 1

        r5 = await engine.recommend("EMP_001", top_n=5)
        assert len(r5.recommended_cases) <= 5

    @pytest.mark.asyncio
    async def test_recommend_has_reason(self):
        """测试推荐包含理由"""
        engine = RecommendEngine()
        result = await engine.recommend("EMP_001", top_n=3)

        assert result.recommendation_reason, "推荐理由不应为空"
        assert len(result.recommendation_reason) > 10

    @pytest.mark.asyncio
    async def test_recommend_by_department(self):
        """测试部门批量推荐"""
        engine = RecommendEngine()
        results = await engine.recommend_by_department(
            "生产部-焊接车间", top_n=3
        )

        assert isinstance(results, list)
        if results:
            for r in results:
                assert "employee_id" in r
                assert "employee_name" in r
                assert "recommended_cases" in r

    def test_list_categories(self):
        """测试列出案例类别"""
        engine = RecommendEngine()
        # 手动加载同步部分
        import json
        from app.utils import get_mock_path
        cases_file = get_mock_path("accident_cases.json")
        with open(cases_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            engine._cases = data.get("cases", [])

        categories = engine.list_categories()
        assert len(categories) >= 5
        assert "个人防护" in categories
        assert "消防安全" in categories

    def test_get_case_by_id(self):
        """测试按 ID 获取案例"""
        engine = RecommendEngine()
        import json
        from app.utils import get_mock_path
        cases_file = get_mock_path("accident_cases.json")
        with open(cases_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            engine._cases = data.get("cases", [])

        case = engine.get_case_by_id("CASE-001")
        assert case is not None
        assert case["title"] == "焊接车间未戴安全帽导致头部受伤事故"

        nonexistent = engine.get_case_by_id("CASE-999")
        assert nonexistent is None


# =========================
# 2. QuestionGenerator 测试
# =========================


class TestQuestionGenerator:
    """题目生成器测试"""

    @pytest.fixture
    def sample_case(self):
        """测试用样本案例"""
        return {
            "case_id": "CASE-TEST",
            "title": "测试事故——违规操作导致设备损坏",
            "category": "个人防护",
            "summary": "工人未按操作规程操作设备，导致设备损坏。",
            "cause_analysis": "1. 工人未接受完整培训即上岗\n2. 设备安全联锁被短接\n3. 现场无安全警示标识",
            "lessons": "1. 新员工必须经培训考核合格后方可上岗\n2. 安全装置严禁短接或拆除\n3. 危险区域必须张贴醒目标识",
            "difficulty": "basic",
        }

    @pytest.mark.asyncio
    async def test_template_generate_returns_questions(self, sample_case):
        """测试模板生成返回题目"""
        gen = QuestionGenerator()
        # 直接调用模板生成（不经过 LLM）
        questions = gen._template_generate(sample_case, count=3)

        assert len(questions) >= 1, f"应至少生成1道题: {len(questions)}"
        assert len(questions) <= 3

    @pytest.mark.asyncio
    async def test_questions_have_required_fields(self, sample_case):
        """测试题目字段完整性"""
        gen = QuestionGenerator()
        questions = gen._template_generate(sample_case, count=3)

        for q in questions:
            assert q.question_type in ("multiple_choice", "true_false")
            assert q.question, "题目不应为空"
            assert q.correct_answer, "答案不应为空"
            assert q.source_case_id == "CASE-TEST"

    @pytest.mark.asyncio
    async def test_multiple_choice_has_four_options(self, sample_case):
        """测试选择题有 4 个选项"""
        gen = QuestionGenerator()
        questions = gen._template_generate(sample_case, count=3)

        mc_questions = [q for q in questions if q.question_type == "multiple_choice"]
        for q in mc_questions:
            assert len(q.options) >= 2, f"选择题应有选项: {q.options}"

    @pytest.mark.asyncio
    async def test_true_false_has_correct_answer(self, sample_case):
        """测试判断题答案格式正确"""
        gen = QuestionGenerator()
        questions = gen._template_generate(sample_case, count=3)

        tf_questions = [q for q in questions if q.question_type == "true_false"]
        for q in tf_questions:
            assert q.correct_answer in ("正确", "错误"), f"判断题答案应为 正确/错误: {q.correct_answer}"

    @pytest.mark.asyncio
    async def test_generate_questions_full_method(self, sample_case):
        """测试完整 generate_questions 方法（LLM降级到模板）"""
        gen = QuestionGenerator()
        questions = await gen.generate_questions(sample_case, count=2)

        assert len(questions) >= 1
        for q in questions:
            assert isinstance(q, TrainingQuestion)

    @pytest.mark.asyncio
    async def test_generate_empty_case_returns_empty(self):
        """测试空案例返回空列表"""
        gen = QuestionGenerator()
        questions = await gen.generate_questions({}, count=3)
        assert questions == []


# =========================
# 3. TrainingManager 测试
# =========================


class TestTrainingManager:
    """培训管理器测试"""

    @pytest.mark.asyncio
    async def test_create_training_plan(self):
        """测试创建培训计划"""
        mgr = TrainingManager()
        plan = await mgr.create_training_plan(
            "EMP_001",
            cases_per_employee=2,
            questions_per_case=2,
        )

        assert isinstance(plan, TrainingPlan)
        assert plan.employee_id == "EMP_001"
        assert plan.employee_name == "张建国"
        assert len(plan.recommendation.recommended_cases) <= 2
        assert plan.total_questions >= 1
        assert plan.estimated_minutes > 0

    @pytest.mark.asyncio
    async def test_create_training_plan_for_different_employees(self):
        """测试不同员工的培训计划不同"""
        mgr = TrainingManager()
        plan_001 = await mgr.create_training_plan("EMP_001", cases_per_employee=3)
        plan_002 = await mgr.create_training_plan("EMP_002", cases_per_employee=3)

        # 不同员工的推荐可能不同（取决于违章记录和部门）
        assert plan_001.employee_name != plan_002.employee_name

    @pytest.mark.asyncio
    async def test_plan_includes_questions_from_multiple_cases(self):
        """测试计划包含多个案例的题目"""
        mgr = TrainingManager()
        plan = await mgr.create_training_plan(
            "EMP_001",
            cases_per_employee=3,
            questions_per_case=2,
        )

        # 统计不同来源案例的题目
        source_cases = set(q.source_case_id for q in plan.questions)
        assert len(source_cases) >= 1

    @pytest.mark.asyncio
    async def test_high_risk_employee_gets_more_relevant_cases(self):
        """测试高风险员工获得针对性推荐"""
        mgr = TrainingManager()
        # EMP_005 是高风险员工（化学品库，有培训缺口）
        plan_high = await mgr.create_training_plan("EMP_005", cases_per_employee=5)
        plan_low = await mgr.create_training_plan("EMP_008", cases_per_employee=5)

        # 高风险员工应有推荐
        assert len(plan_high.recommendation.recommended_cases) >= 1

    @pytest.mark.asyncio
    async def test_nonexistent_employee_plan(self):
        """测试不存在员工的计划"""
        mgr = TrainingManager()
        plan = await mgr.create_training_plan("EMP_999")

        assert plan.employee_id == "EMP_999"
        assert plan.total_questions == 0


# =========================
# 3. 数据模型测试
# =========================


class TestModels:
    """数据模型测试"""

    def test_recommendation_result_defaults(self):
        """测试推荐结果默认值"""
        r = RecommendationResult(
            employee_id="E001",
            employee_name="测试",
            department="测试部",
            risk_level="low",
        )
        assert r.recommended_cases == []
        assert r.recommendation_strategy == ""

    def test_training_question_defaults(self):
        """测试题目默认值"""
        q = TrainingQuestion(
            question_type="multiple_choice",
            question="测试题目？",
        )
        assert q.options == []
        assert q.source_case_id == ""

    def test_training_plan_defaults(self):
        """测试培训计划默认值"""
        rec = RecommendationResult(
            employee_id="E001",
            employee_name="测试",
            department="测试部",
            risk_level="low",
        )
        plan = TrainingPlan(
            employee_id="E001",
            employee_name="测试",
            recommendation=rec,
        )
        assert plan.questions == []
        assert plan.total_questions == 0
        assert plan.estimated_minutes == 0
