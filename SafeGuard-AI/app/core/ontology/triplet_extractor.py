"""
LLM 三元组抽取器

实现技术方案功能 3 — 从中文文本中提取 (实体)-[关系]->(实体) 三元组。

抽取策略:
    1. LLM 抽取（主策略）: 专用 Prompt 驱动，输出结构化 JSON
    2. 正则兜底（降级策略）: 模式匹配常见 EHS 关系描述

三元组类型覆盖:
    - (设备:Equipment)-[HAS_HAZARD]->(隐患:Hazard)
    - (隐患:Hazard)-[GOVERNED_BY]->(法规:Regulation)
    - (隐患:Hazard)-[MITIGATED_BY]->(SOP:SOP)
    - (设备:Equipment)-[INSPECTED_BY]->(SOP:SOP)
    - (法规:Regulation)-[APPLIES_TO]->(设备:Equipment)
"""
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# =========================
# 三元组抽取 Prompt
# =========================

TRIPLET_EXTRACTION_PROMPT = """你是一个工业安全知识图谱构建专家。请从以下文本中提取所有的 (实体)-[关系]->(实体) 三元组。

支持的实体类型:
- Equipment: 设备/设施 (如：灭火器、叉车、配电箱、通风系统)
- Hazard: 隐患/风险 (如：未戴安全帽、泄漏、堵塞、火灾)
- Regulation: 法规/标准 (如：安全生产法、GB30871)
- SOP: 标准操作规程 (如：动火作业SOP、巡检流程)

支持的关系类型:
- HAS_HAZARD: 设备存在的隐患
- GOVERNED_BY: 隐患受某法规/标准约束
- MITIGATED_BY: 隐患由某SOP防范
- INSPECTED_BY: 设备由某SOP规定的流程检查
- APPLIES_TO: 法规适用于某设备/活动
- RELATED_TO: 通用关联

请严格按以下 JSON 格式输出（不要包含任何其他文字）：

```json
{
  "triplets": [
    {
      "subject": "实体名称",
      "subject_type": "Equipment|Hazard|Regulation|SOP",
      "relation": "HAS_HAZARD|GOVERNED_BY|MITIGATED_BY|INSPECTED_BY|APPLIES_TO|RELATED_TO",
      "object": "实体名称",
      "object_type": "Equipment|Hazard|Regulation|SOP",
      "confidence": 0.90,
      "evidence": "原文中支持该三元组的片段"
    }
  ]
}
```

要求:
1. 仅提取文本中明确出现的实体和关系，不要编造
2. 置信度 (confidence) 0-1：明确表述≥0.9，推断≥0.7，不确定≥0.5
3. 实体名称使用原文中的表述
4. 如果文本中没有可提取的三元组，返回 {"triplets": []}
"""

MAX_EXTRACTION_CHARS = 4000


# =========================
# 数据模型
# =========================


@dataclass
class Triplet:
    """
    知识图谱三元组。

    Attributes:
        subject: 主体实体名称
        subject_type: 主体类型 (Equipment/Hazard/Regulation/SOP)
        relation: 关系类型
        object: 客体实体名称
        object_type: 客体类型
        confidence: 置信度 0.0-1.0
        evidence: 原始文本证据
        source_text: 来源文本摘要
    """

    subject: str
    subject_type: str
    relation: str
    object: str
    object_type: str
    confidence: float = 0.5
    evidence: str = ""
    source_text: str = ""


@dataclass
class ExtractionResult:
    """
    三元组抽取结果。

    Attributes:
        triplets: 抽取的三元组列表
        extraction_method: 抽取方式 (llm / regex)
        total_extracted: 抽取总数
        source_length: 源文本长度
    """

    triplets: List[Triplet] = field(default_factory=list)
    extraction_method: str = "regex"
    total_extracted: int = 0
    source_length: int = 0


# =========================
# 正则兜底抽取
# =========================


class _RegexTripletExtractor:
    """
    正则三元组抽取器（LLM 不可用时的降级策略）。

    基于中文 EHS 文本常见关系模式进行匹配。
    """

    # 关系模式: (主体)-[关系词]->(客体)
    RELATION_PATTERNS = [
        # HAS_HAZARD: "XX存在XX隐患/问题/风险"
        (
            r"(\S{2,10}(?:设备|系统|机器|工位|车间|仓库|库房|管道|线路))"
            r"(?:存在|出现|发现|发生)\s*(\S{2,15}(?:隐患|问题|风险|故障|泄漏|火灾|爆炸|事故|异常))",
            "HAS_HAZARD",
        ),
        # GOVERNED_BY: "根据/依据XX法规/标准"
        (
            r"根据\s*[《〈](\S{2,30}[》〉])",
            "GOVERNED_BY",
        ),
        # MITIGATED_BY: "按照XXSOP/流程处置"
        (
            r"(?:按照|依照|参照)\s*(\S{2,20}(?:SOP|规程|流程|方案|预案))",
            "MITIGATED_BY",
        ),
        # RELATED_TO: "XX与XX相关/关联"
        (
            r"(\S{2,10}(?:检查|检测|监测|巡检))\S*(\S{2,10}(?:设备|系统|仪器))",
            "RELATED_TO",
        ),
    ]

    # 实体类型推断
    EQUIPMENT_KEYWORDS = [
        "设备", "机器", "系统", "工位", "车间", "仓库", "库房", "管道", "线路",
        "配电", "叉车", "灭火器", "消防栓", "通风", "传感器", "阀门", "泵",
    ]
    HAZARD_KEYWORDS = [
        "隐患", "问题", "风险", "故障", "泄漏", "火灾", "爆炸", "事故", "异常",
        "堵塞", "违章", "违规", "超期", "失效", "损坏", "缺失",
    ]
    REGULATION_KEYWORDS = [
        "法", "规", "标准", "规范", "条例", "规程", "GB", "规定",
    ]
    SOP_KEYWORDS = [
        "SOP", "流程", "方案", "预案", "措施", "制度", "办法", "指南",
    ]

    def extract(self, text: str) -> ExtractionResult:
        """
        使用正则从文本中抽取三元组。

        Args:
            text: 输入文本

        Returns:
            ExtractionResult
        """
        triplets: List[Triplet] = []

        for pattern, relation in self.RELATION_PATTERNS:
            for match in re.finditer(pattern, text):
                if len(match.groups()) >= 2:
                    subj = match.group(1)
                    obj = match.group(2)
                elif len(match.groups()) == 1:
                    # 单捕获组：从上下文中推断主体
                    subj = self._infer_subject(text, match.start())
                    obj = match.group(1)
                else:
                    continue

                subject_type = self._classify_entity(subj)
                object_type = self._classify_entity(obj)

                triplets.append(Triplet(
                    subject=subj.strip(),
                    subject_type=subject_type,
                    relation=relation,
                    object=obj.strip(),
                    object_type=object_type,
                    confidence=0.6,  # 正则提取置信度较低
                    evidence=match.group(0),
                    source_text=text[:200],
                ))

        result = ExtractionResult(
            triplets=triplets,
            extraction_method="regex",
            total_extracted=len(triplets),
            source_length=len(text),
        )

        logger.info(
            f"[RegexTriplet] 抽取 {len(triplets)} 个三元组 "
            f"(来自 {len(text)} 字符文本)"
        )
        return result

    def _classify_entity(self, name: str) -> str:
        """根据关键词推断实体类型。"""
        for kw in self.EQUIPMENT_KEYWORDS:
            if kw in name:
                return "Equipment"
        for kw in self.REGULATION_KEYWORDS:
            if kw in name:
                return "Regulation"
        for kw in self.HAZARD_KEYWORDS:
            if kw in name:
                return "Hazard"
        for kw in self.SOP_KEYWORDS:
            if kw in name:
                return "SOP"
        return "Equipment"  # 默认

    def _infer_subject(self, text: str, match_pos: int) -> str:
        """从匹配位置前的文本推断主体。"""
        # 取匹配位置前的 50 个字符
        prefix = text[max(0, match_pos - 50):match_pos]
        # 尝试找常见的实体模式
        for pattern in [r"(\S{2,10}(?:设备|系统|工位|车间|仓库))"]:
            matches = re.findall(pattern, prefix)
            if matches:
                return matches[-1]  # 最近的一个
        return "未知设备"


# =========================
# LLM 三元组抽取器
# =========================


class TripletExtractor:
    """
    知识图谱三元组抽取器。

    从中文 EHS 文本中提取结构化三元组，用于构建/扩充 Neo4j 图谱。

    使用方式:
        extractor = TripletExtractor()
        result = await extractor.extract("灭火器需要每月检查一次...")
        for triplet in result.triplets:
            print(f"({triplet.subject})-[{triplet.relation}]->({triplet.object})")
    """

    def __init__(self):
        """初始化抽取器。"""
        self._regex = _RegexTripletExtractor()
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
                temperature=0.1,
                timeout=settings.llm.timeout,
            )
            self._llm_available = True
            logger.info("[TripletExtractor] LLM 客户端就绪")
            return True
        except Exception as e:
            logger.warning(f"[TripletExtractor] LLM 不可用 ({e})，降级为正则提取")
            self._llm_available = False
            return False

    async def extract(self, text: str) -> ExtractionResult:
        """
        从文本中提取三元组。

        优先 LLM，失败降级为正则。

        Args:
            text: 输入文本

        Returns:
            ExtractionResult
        """
        if not text or not text.strip():
            return ExtractionResult(source_length=0)

        # 尝试 LLM 提取
        if self._ensure_llm():
            try:
                return await self._llm_extract(text)
            except Exception as e:
                logger.warning(f"[TripletExtractor] LLM 提取失败 ({e})，降级正则")

        # 正则兜底
        return self._regex.extract(text)

    async def _llm_extract(self, text: str) -> ExtractionResult:
        """LLM 三元组抽取。"""
        from langchain_core.messages import HumanMessage, SystemMessage

        if len(text) > MAX_EXTRACTION_CHARS:
            text = text[:MAX_EXTRACTION_CHARS]

        messages = [
            SystemMessage(content=TRIPLET_EXTRACTION_PROMPT),
            HumanMessage(content=f"请分析以下文本并提取三元组：\n\n{text}"),
        ]

        response = await self._llm.ainvoke(messages)
        return self._parse_llm_response(response.content, text)

    def _parse_llm_response(self, response_text: str, source: str) -> ExtractionResult:
        """解析 LLM JSON 响应。"""
        try:
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)

            data = json.loads(cleaned)
            raw_triplets = data.get("triplets", [])

            triplets = []
            for t in raw_triplets:
                triplets.append(Triplet(
                    subject=t.get("subject", ""),
                    subject_type=t.get("subject_type", "Equipment"),
                    relation=t.get("relation", "RELATED_TO"),
                    object=t.get("object", ""),
                    object_type=t.get("object_type", "Equipment"),
                    confidence=float(t.get("confidence", 0.7)),
                    evidence=t.get("evidence", ""),
                    source_text=source[:200],
                ))

            # 过滤低置信度三元组
            high_confidence = [t for t in triplets if t.confidence >= 0.5]

            logger.info(
                f"[TripletExtractor] LLM 抽取 {len(high_confidence)}/{len(triplets)} "
                f"个三元组 (置信度≥0.5)"
            )

            return ExtractionResult(
                triplets=high_confidence,
                extraction_method="llm",
                total_extracted=len(high_confidence),
                source_length=len(source),
            )

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[TripletExtractor] JSON 解析失败 ({e})")
            return self._regex.extract(source)
