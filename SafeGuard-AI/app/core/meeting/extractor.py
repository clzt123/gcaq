"""
NER 信息提取层

实现技术方案功能 14 — 智能会议纪要从转录文本中提取结构化信息：
    - LLM 结构化提取（主策略）：使用 ChatOpenAI 调用 Qwen/DeepSeek 提取 JSON
    - 正则兜底（降级策略）：中文正则模式匹配日期、责任人、决议项

设计模式: 遵循项目 LLM 调用模式（langchain_openai.ChatOpenAI + async）。
"""
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# =========================
# 常量
# =========================

# LLM 提取专用 Prompt 模板
EXTRACTION_SYSTEM_PROMPT = """你是一个专业的会议纪要分析助手。你的任务是从会议转录文本中提取关键信息。

请严格按以下 JSON 格式输出，不要包含任何其他文字：

{
  "title": "会议标题（从内容推断）",
  "attendees": ["参会人员1", "参会人员2"],
  "responsible_persons": ["责任人1", "责任人2"],
  "deadlines": ["任务1: 截止时间", "任务2: 截止时间"],
  "action_items": [
    {"item": "决议事项描述", "assignee": "负责人", "deadline": "截止时间"}
  ],
  "key_topics": ["议题1", "议题2"],
  "risk_mentions": ["提及的安全隐患或风险"]
}

提取规则：
1. 责任人：关注"XXX负责"、"由XXX...执行"、"XXX牵头"等表述
2. 截止时间：识别日期（X月X日、下周X、X月X日前）+ 关联任务
3. 决议项：会议中明确做出的决定和分配的任务
4. 风险提及：安全相关的风险、隐患、事故描述
5. 如果没有对应信息，返回空数组 []
"""

# LLM 提取最大字符数（超过此值先行截断）
MAX_EXTRACT_CHARS = 6000


# =========================
# 数据模型
# =========================


@dataclass
class MeetingExtractionResult:
    """
    会议信息提取结果。

    Attributes:
        title: 会议标题
        attendees: 参会人员列表
        responsible_persons: 责任人列表
        deadlines: 截止时间描述列表
        action_items: 决议项列表 [{item, assignee, deadline}]
        key_topics: 关键议题列表
        risk_mentions: 风险/隐患提及列表
        raw_transcript: 原始转录文本（截断前）
        extraction_method: 提取方式: "llm" / "regex_fallback"
    """

    title: str = ""
    attendees: List[str] = field(default_factory=list)
    responsible_persons: List[str] = field(default_factory=list)
    deadlines: List[str] = field(default_factory=list)
    action_items: List[Dict[str, str]] = field(default_factory=list)
    key_topics: List[str] = field(default_factory=list)
    risk_mentions: List[str] = field(default_factory=list)
    raw_transcript: str = ""
    extraction_method: str = "regex_fallback"


# =========================
# 正则兜底提取器
# =========================


class _RegexExtractor:
    """
    中文会议文本正则提取器。

    作为 LLM 不可用时的降级策略，覆盖：
        - 日期匹配（XXXX年X月X日、下周一~日、X月X日前）
        - 责任人匹配（XXX负责、由XXX...执行）
        - 决议项匹配（决议...、决定...）
        - 风险关键词匹配
    """

    # 中文日期模式
    DATE_PATTERNS = [
        (r"(\d{4}年\d{1,2}月\d{1,2}日)", "absolute"),      # 2024年6月10日
        (r"(\d{1,2}月\d{1,2}日)", "month_day"),             # 6月10日
        (r"(下周[一二三四五六七日天])", "next_week"),         # 下周三
        (r"(周[一二三四五六日天])", "this_week"),             # 周三
        (r"(明天|后天|今天)", "relative"),                    # 明天
        (r"截止[:：]?\s*(\S+?)(?:[，。,\.\s]|$)", "deadline"),  # 截止: XXX
    ]

    # 责任人匹配模式
    PERSON_PATTERNS = [
        r"(\S{2,4})(?:负责|牵头|主管|跟进|执行|协调)",
        r"由(\S{2,4})(?:负责|执行|跟进)",
    ]

    # 决议项触发词
    ACTION_TRIGGERS = ["决议", "决定", "责令", "要求", "安排", "下达"]

    # 风险关键词
    RISK_KEYWORDS = [
        "隐患", "事故", "泄漏", "火灾", "爆炸", "中毒", "触电", "坍塌",
        "违章", "违规", "故障", "失效", "老化", "损坏", "缺失", "堵塞",
        "不亮", "无响应", "偏高", "偏低", "超标", "未达标", "未执行",
    ]

    def extract(self, transcript: str) -> MeetingExtractionResult:
        """
        使用正则表达式从转录文本中提取会议信息。

        Args:
            transcript: 会议转录文本

        Returns:
            MeetingExtractionResult 数据对象
        """
        result = MeetingExtractionResult(
            raw_transcript=transcript[:MAX_EXTRACT_CHARS],
            extraction_method="regex_fallback",
        )

        # ---- 提取参会人员 ----
        result.attendees = self._extract_attendees(transcript)

        # ---- 提取责任人 ----
        result.responsible_persons = self._extract_responsible_persons(transcript)

        # ---- 提取截止时间 ----
        result.deadlines = self._extract_deadlines(transcript)

        # ---- 提取决议项 ----
        result.action_items = self._extract_action_items(transcript)

        # ---- 提取关键议题 ----
        result.key_topics = self._extract_key_topics(transcript)

        # ---- 提取风险提及 ----
        result.risk_mentions = self._extract_risk_mentions(transcript)

        # ---- 推断标题 ----
        result.title = self._infer_title(transcript)

        logger.info(
            f"[RegexExtractor] 提取完成: "
            f"attendees={len(result.attendees)}, "
            f"responsible={len(result.responsible_persons)}, "
            f"deadlines={len(result.deadlines)}, "
            f"action_items={len(result.action_items)}"
        )
        return result

    def _extract_attendees(self, text: str) -> List[str]:
        """提取参会人员（中文名+括号角色标注的模式）。"""
        pattern = r"(\S{2,4})[（(][^)）]*[)）]"
        matches = re.findall(pattern, text)
        # 去重保持顺序
        seen = set()
        attendees = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                attendees.append(m)
        return attendees

    def _extract_responsible_persons(self, text: str) -> List[str]:
        """提取被分配任务的责任人。"""
        persons = set()
        for pattern in self.PERSON_PATTERNS:
            for match in re.finditer(pattern, text):
                name = match.group(1)
                if len(name) >= 2:  # 过滤误匹配
                    persons.add(name)
        return list(persons)

    def _extract_deadlines(self, text: str) -> List[str]:
        """提取截止时间描述。"""
        deadlines = []
        for pattern, _ in self.DATE_PATTERNS:
            for match in re.finditer(pattern, text):
                deadlines.append(match.group(0))
        return list(set(deadlines))  # 去重

    def _extract_action_items(self, text: str) -> List[Dict[str, str]]:
        """提取决议项列表。"""
        items = []

        # 按行分割，查找含触发词的行
        lines = text.replace("。", "。\n").replace("；", "；\n").split("\n")
        for line in lines:
            has_trigger = any(trigger in line for trigger in self.ACTION_TRIGGERS)
            if not has_trigger:
                continue

            # 尝试提取负责人
            assignee = ""
            deadline = ""
            for pattern in self.PERSON_PATTERNS:
                m = re.search(pattern, line)
                if m:
                    assignee = m.group(1)
                    break

            # 尝试提取截止时间
            for date_pattern, _ in self.DATE_PATTERNS:
                m = re.search(date_pattern, line)
                if m:
                    deadline = m.group(0)
                    break

            item_text = line.strip()
            if len(item_text) > 200:
                item_text = item_text[:200] + "..."

            items.append({
                "item": item_text,
                "assignee": assignee,
                "deadline": deadline,
            })

        return items

    def _extract_key_topics(self, text: str) -> List[str]:
        """提取关键议题。"""
        topics = []
        # 匹配"讨论XX"、"XX问题"、"XX情况"、"通报XX"
        topic_patterns = [
            r"(?:讨论|审议|评估)(\S{2,10}(?:问题|情况|方案|计划))",
            r"(?:通报|汇报)(\S{2,10}(?:情况|数据|结果))",
        ]
        for pattern in topic_patterns:
            for match in re.finditer(pattern, text):
                topics.append(match.group(0))

        # 也检查"第一"、"第二"等序号引导的条款
        numbered = re.findall(r"(?:第[一二三四五六七八九十]+)[，,\.\s]*(\S{2,15})", text)
        topics.extend(numbered[:5])

        return list(set(topics))

    def _extract_risk_mentions(self, text: str) -> List[str]:
        """提取风险/隐患相关描述。"""
        mentions = []
        sentences = re.split(r"[。！；\n]", text)
        for sentence in sentences:
            for keyword in self.RISK_KEYWORDS:
                if keyword in sentence:
                    clean = sentence.strip()
                    if len(clean) > 100:
                        clean = clean[:100] + "..."
                    mentions.append(clean)
                    break  # 每句只记录一次
        return mentions[:20]  # 最多 20 条

    def _infer_title(self, text: str) -> str:
        """从文本开头推断会议标题。"""
        # 取前 200 字符寻找会议主题
        head = text[:200]
        # 常见会议类型关键词
        for keyword in ["例会", "复盘会", "总结会", "评审会", "培训会"]:
            if keyword in head:
                m = re.search(rf"(\S{{2,20}}{keyword})", head)
                if m:
                    return m.group(1)

        # 兜底：第一行
        first_line = text.split("\n")[0]
        return first_line[:60] if len(first_line) > 60 else first_line


# =========================
# LLM 提取器
# =========================


class MeetingExtractor:
    """
    会议信息提取器。

    主策略: LLM 结构化提取（精提取）
    降级策略: 正则兜底（粗提取）

    使用方式:
        extractor = MeetingExtractor()
        result = await extractor.extract(transcript_text)
    """

    def __init__(self):
        """初始化提取器，准备 LLM 客户端和正则兜底。"""
        self._regex = _RegexExtractor()
        self._llm: Optional[Any] = None
        self._llm_available: Optional[bool] = None

    def _ensure_llm(self) -> bool:
        """
        懒加载 LLM 客户端（单次检测，结果缓存）。

        Returns:
            True 如果 LLM 客户端可用
        """
        if self._llm_available is not None:
            return self._llm_available

        try:
            # 在导入时先设置好可观测性
            from app.config import get_settings
            settings = get_settings()
            if not settings.langsmith.api_key:
                import os
                langsmith_key = os.environ.get("LANGSMITH_API_KEY")
                if langsmith_key and langsmith_key.strip():
                    os.environ["LANGCHAIN_TRACING_V2"] = "true"
                    os.environ["LANGCHAIN_API_KEY"] = langsmith_key.strip()
                    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith.project
                    os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith.endpoint

            from langchain_openai import ChatOpenAI

            self._llm = ChatOpenAI(
                base_url=settings.llm.base_url,
                api_key=settings.llm.api_key,
                model=settings.llm.model_name,
                temperature=0.1,  # 低温度，提高提取稳定性
                timeout=settings.llm.timeout,
            )
            self._llm_available = True
            logger.info(f"[MeetingExtractor] LLM 客户端就绪: {settings.llm.model_name}")
            return True
        except Exception as e:
            logger.warning(f"[MeetingExtractor] LLM 不可用 ({e})，降级为正则提取")
            self._llm_available = False
            return False

    async def extract(self, transcript: str) -> MeetingExtractionResult:
        """
        从转录文本中提取结构化会议信息。

        自动选择 LLM 或正则兜底策略。

        Args:
            transcript: 会议转录文本

        Returns:
            MeetingExtractionResult 数据对象
        """
        if not transcript or not transcript.strip():
            logger.warning("[MeetingExtractor] 转录文本为空")
            return MeetingExtractionResult(raw_transcript=transcript or "")

        # 尝试 LLM 提取
        if self._ensure_llm():
            try:
                return await self._llm_extract(transcript)
            except Exception as e:
                logger.warning(
                    f"[MeetingExtractor] LLM 提取失败 ({e})，降级为正则提取"
                )

        # 正则兜底
        logger.info("[MeetingExtractor] 使用正则兜底提取")
        return self._regex.extract(transcript)

    async def _llm_extract(self, transcript: str) -> MeetingExtractionResult:
        """
        使用 LLM 进行结构化信息提取。

        Args:
            transcript: 转录文本

        Returns:
            MeetingExtractionResult
        """
        # 截断过长的文本
        if len(transcript) > MAX_EXTRACT_CHARS:
            logger.info(
                f"[MeetingExtractor] 转录文本过长 ({len(transcript)} chars)，"
                f"截断至 {MAX_EXTRACT_CHARS} chars"
            )
            transcript = transcript[:MAX_EXTRACT_CHARS]

        # 构建消息
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=EXTRACTION_SYSTEM_PROMPT),
            HumanMessage(content=f"请分析以下会议转录文本并提取关键信息：\n\n{transcript}"),
        ]

        # 调用 LLM
        response = await self._llm.ainvoke(messages)
        response_text = response.content

        logger.debug(f"[MeetingExtractor] LLM 原始响应: {response_text[:300]}...")

        # 解析 JSON
        result = self._parse_llm_response(response_text, transcript)
        return result

    def _parse_llm_response(
        self, response_text: str, transcript: str
    ) -> MeetingExtractionResult:
        """
        解析 LLM 返回的 JSON 响应。

        带容错性：处理 ```json 代码块包裹、JSON 解析失败等情况。

        Args:
            response_text: LLM 原始响应文本
            transcript: 原始转录文本

        Returns:
            MeetingExtractionResult
        """
        try:
            # 清理可能的代码块包裹
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                # 移除 ```json ... ``` 包裹
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)

            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning(f"[MeetingExtractor] LLM JSON 解析失败 ({e})，尝试正则兜底")
            return self._regex.extract(transcript)

        # 构建结果
        result = MeetingExtractionResult(
            title=data.get("title", ""),
            attendees=data.get("attendees", []),
            responsible_persons=data.get("responsible_persons", []),
            deadlines=data.get("deadlines", []),
            action_items=data.get("action_items", []),
            key_topics=data.get("key_topics", []),
            risk_mentions=data.get("risk_mentions", []),
            raw_transcript=transcript[:MAX_EXTRACT_CHARS],
            extraction_method="llm",
        )

        logger.info(
            f"[MeetingExtractor] LLM 提取完成: "
            f"attendees={len(result.attendees)}, "
            f"responsible={len(result.responsible_persons)}, "
            f"deadlines={len(result.deadlines)}, "
            f"action_items={len(result.action_items)}"
        )
        return result
