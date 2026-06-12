"""
LLM 题目生成器

实现技术方案功能 15 — 将事故案例自动转化为选择题/判断题。

生成策略:
    1. LLM 生成（主策略）: 使用 Qwen/DeepSeek 根据案例生成结构化题目
    2. 模板兜底（降级策略）: 基于预定义模板填充案例关键信息

输出格式:
    - 选择题: 4选项，含正确答案和解析
    - 判断题: 对/错，含解析
"""
import json
import logging
import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# =========================
# 常量
# =========================

# LLM 题目生成 Prompt
QUESTION_GEN_PROMPT = """你是一个安全生产培训专家。请根据以下事故案例生成培训题目。

案例标题: {title}
案例简述: {summary}
事故原因: {causes}
经验教训: {lessons}

请生成以下题目，以 JSON 格式输出（不要包含其他文字）：

```json
{{
  "questions": [
    {{
      "type": "multiple_choice",
      "question": "题目内容",
      "options": ["A. 选项A", "B. 选项B", "C. 选项C", "D. 选项D"],
      "correct_answer": "A",
      "explanation": "解析说明"
    }},
    {{
      "type": "true_false",
      "question": "题目内容（答案为：正确/错误）",
      "correct_answer": "正确",
      "explanation": "解析说明"
    }}
  ]
}}
```

要求:
1. 生成 1-2 道选择题（4个选项）和 1 道判断题
2. 单选题每次随机排列选项顺序
3. 题目应针对案例的关键知识点
4. 解析应引用案例中的具体数据和法规依据
5. 难度适中，适合工厂一线员工
"""

MAX_QUESTION_CHARS = 3000


# =========================
# 数据模型
# =========================


@dataclass
class TrainingQuestion:
    """
    培训题目。

    Attributes:
        question_type: 题型 (multiple_choice / true_false)
        question: 题目内容
        options: 选项列表（判断题为空）
        correct_answer: 正确答案
        explanation: 答案解析
        source_case_id: 来源案例 ID
        difficulty: 难度等级
    """

    question_type: str  # "multiple_choice" | "true_false"
    question: str
    options: List[str] = field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""
    source_case_id: str = ""
    difficulty: str = "basic"


# =========================
# 题目生成器
# =========================


class QuestionGenerator:
    """
    安全培训题目生成器。

    将事故案例转化为选择题和判断题，支持 LLM 生成和模板兜底。

    使用方式:
        gen = QuestionGenerator()
        questions = await gen.generate_questions(case, count=3)
    """

    def __init__(self):
        """初始化生成器。"""
        self._llm: Optional[Any] = None
        self._llm_available: Optional[bool] = None

    def _ensure_llm(self) -> bool:
        """懒加载 LLM 客户端。"""
        if self._llm_available is not None:
            return self._llm_available

        try:
            from app.config import get_settings
            from langchain_openai import ChatOpenAI

            settings = get_settings()
            self._llm = ChatOpenAI(
                base_url=settings.llm.base_url,
                api_key=settings.llm.api_key,
                model=settings.llm.model_name,
                temperature=0.3,
                timeout=settings.llm.timeout,
            )
            self._llm_available = True
            logger.info("[QuestionGenerator] LLM 客户端就绪")
            return True
        except Exception as e:
            logger.warning(f"[QuestionGenerator] LLM 不可用 ({e})，使用模板兜底")
            self._llm_available = False
            return False

    async def generate_questions(
        self,
        case: Dict[str, Any],
        count: int = 3,
    ) -> List[TrainingQuestion]:
        """
        为事故案例生成培训题目。

        优先使用 LLM 生成，失败时降级为模板生成。

        Args:
            case: 事故案例数据（含 title/summary/cause_analysis/lessons）
            count: 生成题目数量

        Returns:
            TrainingQuestion 列表
        """
        if not case:
            logger.warning("[QuestionGenerator] 案例数据为空")
            return []

        # 尝试 LLM 生成
        if self._ensure_llm():
            try:
                questions = await self._llm_generate(case, count)
                if questions:
                    return questions
            except Exception as e:
                logger.warning(f"[QuestionGenerator] LLM 生成失败 ({e})，降级模板")

        # 模板兜底
        logger.info("[QuestionGenerator] 使用模板生成题目")
        return self._template_generate(case, count)

    async def _llm_generate(
        self,
        case: Dict[str, Any],
        count: int,
    ) -> List[TrainingQuestion]:
        """LLM 生成题目。"""
        from langchain_core.messages import HumanMessage, SystemMessage

        # 构建 Prompt
        causes = case.get("cause_analysis", "")
        if len(causes) > 500:
            causes = causes[:500] + "..."

        lessons = case.get("lessons", "")
        if len(lessons) > 500:
            lessons = lessons[:500] + "..."

        user_prompt = QUESTION_GEN_PROMPT.format(
            title=case.get("title", ""),
            summary=case.get("summary", ""),
            causes=causes,
            lessons=lessons,
        )

        messages = [
            SystemMessage(content="你是一个专业的安全生产培训专家，擅长出题。"),
            HumanMessage(content=user_prompt),
        ]

        response = await self._llm.ainvoke(messages)
        response_text = response.content

        # 解析 JSON
        questions = self._parse_llm_response(response_text, case)
        return questions[:count]

    def _parse_llm_response(
        self,
        response_text: str,
        case: Dict[str, Any],
    ) -> List[TrainingQuestion]:
        """解析 LLM JSON 响应。"""
        try:
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)

            data = json.loads(cleaned)
            raw_questions = data.get("questions", [])

            questions = []
            for q in raw_questions:
                questions.append(TrainingQuestion(
                    question_type=q.get("type", "multiple_choice"),
                    question=q.get("question", ""),
                    options=q.get("options", []),
                    correct_answer=q.get("correct_answer", ""),
                    explanation=q.get("explanation", ""),
                    source_case_id=case.get("case_id", ""),
                    difficulty=case.get("difficulty", "basic"),
                ))

            logger.info(f"[QuestionGenerator] LLM 生成 {len(questions)} 道题目")
            return questions

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[QuestionGenerator] JSON 解析失败 ({e})")
            return []

    def _template_generate(
        self,
        case: Dict[str, Any],
        count: int,
    ) -> List[TrainingQuestion]:
        """
        模板兜底生成题目。

        基于案例关键信息填充预定义模板。

        Args:
            case: 事故案例数据
            count: 目标数量

        Returns:
            TrainingQuestion 列表
        """
        case_id = case.get("case_id", "")
        title = case.get("title", "")
        category = case.get("category", "")
        causes = case.get("cause_analysis", "")
        lessons = case.get("lessons", "")
        difficulty = case.get("difficulty", "basic")

        questions: List[TrainingQuestion] = []

        # ---- 模板 1: 事故类型判断题 ----
        if category:
            questions.append(TrainingQuestion(
                question_type="true_false",
                question=f"在'{title}'这起事故中，主要涉及的安全类别是'{category}'。",
                correct_answer="正确",
                explanation=f"该事故属于{category}类事故。{lessons[:100] if lessons else ''}",
                source_case_id=case_id,
                difficulty=difficulty,
            ))

        # ---- 模板 2: 关键措施选择题 ----
        cause_lines = [c.strip() for c in causes.split("\n") if c.strip()]
        if cause_lines and len(cause_lines) >= 2:
            correct_cause = cause_lines[0]
            wrong_causes = cause_lines[1:3] if len(cause_lines) > 2 else [
                "设备质量问题",
                "天气原因",
            ]
            # 格式化选项
            options = [
                f"A. {correct_cause[:60]}",
                f"B. {wrong_causes[0][:60] if wrong_causes else '操作失误'}",
                f"C. {wrong_causes[1][:60] if len(wrong_causes) > 1 else '管理缺失'}",
                f"D. 以上都是",
            ]
            random.shuffle(options)

            questions.append(TrainingQuestion(
                question_type="multiple_choice",
                question=f"关于'{title}'，最重要的直接原因是？",
                options=options,
                correct_answer=f"A. {correct_cause[:60]}",
                explanation=f"事故调查发现：{correct_cause}",
                source_case_id=case_id,
                difficulty=difficulty,
            ))

        # ---- 模板 3: 经验教训判断题 ----
        lesson_lines = [l.strip() for l in lessons.split("\n") if l.strip()]
        if lesson_lines:
            first_lesson = lesson_lines[0]
            # 生成一个改编的错误说法
            questions.append(TrainingQuestion(
                question_type="true_false",
                question=f"从'{title}'中可以得出以下经验：{first_lesson[:100]}",
                correct_answer="正确",
                explanation=f"这是该事故的核心经验教训之一。{first_lesson}",
                source_case_id=case_id,
                difficulty=difficulty,
            ))

        # ---- 模板 4: 预防措施选择题 ----
        if lesson_lines and len(lesson_lines) >= 3:
            correct_lesson = lesson_lines[0]
            wrong_lesson = lesson_lines[2] if len(lesson_lines) > 2 else (
                "增加生产速度以弥补损失" if "增加" not in lesson_lines[0]
                else "减少安全投入降低成本"
            )
            options = [
                f"A. {correct_lesson[:60]}",
                f"B. {wrong_lesson[:60]}",
                f"C. 事后处理即可，无需预防",
                f"D. 以上都不对",
            ]
            random.shuffle(options)

            questions.append(TrainingQuestion(
                question_type="multiple_choice",
                question=f"为防止类似'{title}'再次发生，最有效的预防措施是？",
                options=options,
                correct_answer=f"A. {correct_lesson[:60]}",
                explanation=f"基于事故教训：{correct_lesson}",
                source_case_id=case_id,
                difficulty=difficulty,
            ))

        logger.info(
            f"[QuestionGenerator] 模板生成 {len(questions)} 道题目 "
            f"(目标 {count})"
        )
        return questions[:count]
