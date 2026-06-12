"""
Markdown 纪要生成与知识库归档

实现技术方案功能 14 — 智能会议纪要从提取结果生成 Markdown 纪要并归档到知识库。

组件:
    - MinutesGenerator: Jinja2 模板渲染 + 知识库归档
    - MeetingMinutes: 纪要数据模型
"""
import logging
import uuid
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.meeting.extractor import MeetingExtractionResult

logger = logging.getLogger(__name__)

# =========================
# Jinja2 Markdown 模板
# =========================

MINUTES_TEMPLATE = """# {{ title }}

> **会议编号**: {{ meeting_id }}
> **生成时间**: {{ generated_at }}
> **提取方式**: {{ extraction_method }}

---

## 📋 参会人员

{% for person in attendees %}
- {{ person }}
{%- else %}
- *(未提取到参会人员信息)*
{% endfor %}

---

## 📌 关键议题

{% for topic in key_topics %}
1. {{ topic }}
{%- else %}
- *(未提取到关键议题)*
{% endfor %}

---

## 🔴 风险/隐患提及

{% for risk in risk_mentions %}
- {{ risk }}
{%- else %}
- *(未提取到风险信息)*
{% endfor %}

---

## ✅ 决议事项

| # | 决议内容 | 责任人 | 截止时间 |
|---|---------|--------|---------|
{% for item in action_items %}
| {{ loop.index }} | {{ item.get('item', '') | truncate(100) }} | {{ item.get('assignee', '待定') }} | {{ item.get('deadline', '待定') }} |
{%- else %}
| - | *(未提取到决议事项)* | - | - |
{% endfor %}

---

## 👤 责任人汇总

{% for person in responsible_persons %}
- {{ person }}
{%- else %}
- *(未提取到责任人)*
{% endfor %}

---

## 📅 截止时间节点

{% for deadline in deadlines %}
- {{ deadline }}
{%- else %}
- *(未提取到截止时间)*
{% endfor %}

---

## 📝 原始转录（部分）

```
{{ transcript_preview }}
```

---

> 🤖 本纪要由 SafeGuard-AI 智能会议纪要模块自动生成
> 如有疑义，请以原始录音或书面纪要为准
"""


# =========================
# 数据模型
# =========================


@dataclass
class MeetingMinutes:
    """
    会议纪要完整数据。

    Attributes:
        meeting_id: 唯一会议标识
        title: 会议标题
        markdown_content: 完整的 Markdown 纪要文本
        extraction: 提取的结构化数据
        archived_to_kb: 是否已归档到知识库
        kb_chunk_ids: 知识库归档的分块 ID 列表
        generated_at: 生成时间
    """

    meeting_id: str
    title: str
    markdown_content: str
    extraction: MeetingExtractionResult
    archived_to_kb: bool = False
    kb_chunk_ids: List[str] = field(default_factory=list)
    generated_at: str = ""


# =========================
# 纪要生成器
# =========================


class MinutesGenerator:
    """
    会议纪要生成器。

    功能:
        1. 基于 Jinja2 模板渲染 Markdown 纪要
        2. 可选归档到知识库（通过 KnowledgeIngestion）

    使用方式:
        gen = MinutesGenerator()
        minutes = await gen.generate(extraction_result, title="周安全例会")
        # 归档到知识库
        minutes = await gen.generate_and_archive(extraction_result, title="周安全例会")
    """

    def __init__(self):
        """初始化纪要生成器。"""
        self._jinja = None
        self._template = None

    def _ensure_template(self):
        """懒加载 Jinja2 模板。"""
        if self._template is None:
            try:
                from jinja2 import Template
                self._template = Template(MINUTES_TEMPLATE)
                logger.debug("[MinutesGenerator] Jinja2 模板初始化完成")
            except ImportError:
                # Jinja2 不可用时用纯字符串格式化兜底
                logger.warning("[MinutesGenerator] Jinja2 不可用，使用纯文本兜底")
                self._template = None

    async def generate(
        self,
        extraction: MeetingExtractionResult,
        title: str = "",
        meeting_id: str = "",
    ) -> MeetingMinutes:
        """
        生成会议 Markdown 纪要。

        Args:
            extraction: 会议信息提取结果
            title: 会议标题（为空则使用提取结果中的标题）
            meeting_id: 会议 ID（为空则自动生成）

        Returns:
            MeetingMinutes 完整纪要对象
        """
        self._ensure_template()

        if not meeting_id:
            meeting_id = f"MEET-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        if not title:
            title = extraction.title or "未命名会议"

        generated_at = datetime.now().isoformat()

        # 转录预览（前 500 字符）
        transcript_preview = extraction.raw_transcript[:500]
        if len(extraction.raw_transcript) > 500:
            transcript_preview += "\n\n... (转录文本共 {} 字符，已截断) ...".format(
                len(extraction.raw_transcript)
            )

        # 渲染 Markdown
        if self._template:
            markdown = self._template.render(
                title=title,
                meeting_id=meeting_id,
                generated_at=generated_at,
                extraction_method=extraction.extraction_method,
                attendees=extraction.attendees,
                key_topics=extraction.key_topics,
                risk_mentions=extraction.risk_mentions,
                action_items=extraction.action_items,
                responsible_persons=extraction.responsible_persons,
                deadlines=extraction.deadlines,
                transcript_preview=transcript_preview,
            )
        else:
            markdown = self._render_fallback(
                title, meeting_id, generated_at, extraction, transcript_preview
            )

        logger.info(
            f"[MinutesGenerator] 纪要生成完成: {meeting_id} "
            f"(提取方式: {extraction.extraction_method})"
        )

        return MeetingMinutes(
            meeting_id=meeting_id,
            title=title,
            markdown_content=markdown,
            extraction=extraction,
            generated_at=generated_at,
        )

    async def generate_and_archive(
        self,
        extraction: MeetingExtractionResult,
        title: str = "",
        meeting_id: str = "",
    ) -> MeetingMinutes:
        """
        生成纪要并归档到知识库。

        Args:
            extraction: 会议信息提取结果
            title: 会议标题
            meeting_id: 会议 ID

        Returns:
            MeetingMinutes 完整纪要对象（含归档状态）
        """
        minutes = await self.generate(extraction, title, meeting_id)

        # 尝试归档到知识库
        try:
            chunk_ids = await self._archive_to_knowledge_base(minutes)
            minutes.archived_to_kb = True
            minutes.kb_chunk_ids = chunk_ids
            logger.info(
                f"[MinutesGenerator] 归档成功: {minutes.meeting_id} → "
                f"{len(chunk_ids)} 个分块"
            )
        except Exception as e:
            logger.warning(
                f"[MinutesGenerator] 归档失败 ({e})，纪要仍正常生成"
            )
            minutes.archived_to_kb = False

        return minutes

    async def _archive_to_knowledge_base(
        self, minutes: MeetingMinutes
    ) -> List[str]:
        """
        将纪要通过 KnowledgeIngestion 管道归档到知识库。

        Args:
            minutes: 会议纪要

        Returns:
            归档的 chunk_id 列表
        """
        from app.core.knowledge.ingestion import KnowledgeIngestion

        ingestion = KnowledgeIngestion()
        chunk_ids = await ingestion.ingest_text(
            text=minutes.markdown_content,
            title=minutes.title,
            doc_type="meeting_minutes",
        )
        return chunk_ids

    def _render_fallback(
        self,
        title: str,
        meeting_id: str,
        generated_at: str,
        extraction: MeetingExtractionResult,
        transcript_preview: str,
    ) -> str:
        """
        纯字符串格式化兜底（Jinja2 不可用时）。

        Args:
            title: 会议标题
            meeting_id: 会议 ID
            generated_at: 生成时间
            extraction: 提取结果
            transcript_preview: 转录预览

        Returns:
            Markdown 文本
        """
        lines = [
            f"# {title}",
            "",
            f"> **会议编号**: {meeting_id}",
            f"> **生成时间**: {generated_at}",
            f"> **提取方式**: {extraction.extraction_method}",
            "",
            "---",
            "",
            "## 📋 参会人员",
            "",
        ]

        if extraction.attendees:
            for p in extraction.attendees:
                lines.append(f"- {p}")
        else:
            lines.append("- *(未提取到参会人员信息)*")

        lines.extend(["", "---", "", "## 📌 关键议题", ""])
        if extraction.key_topics:
            for i, topic in enumerate(extraction.key_topics, 1):
                lines.append(f"{i}. {topic}")
        else:
            lines.append("- *(未提取到关键议题)*")

        lines.extend(["", "---", "", "## 🔴 风险/隐患提及", ""])
        if extraction.risk_mentions:
            for risk in extraction.risk_mentions:
                lines.append(f"- {risk}")
        else:
            lines.append("- *(未提取到风险信息)*")

        lines.extend(["", "---", "", "## ✅ 决议事项", ""])
        if extraction.action_items:
            lines.append("| # | 决议内容 | 责任人 | 截止时间 |")
            lines.append("|---|---------|--------|---------|")
            for i, item in enumerate(extraction.action_items, 1):
                ai_text = item.get("item", "")[:100]
                ai_assignee = item.get("assignee", "待定")
                ai_deadline = item.get("deadline", "待定")
                lines.append(f"| {i} | {ai_text} | {ai_assignee} | {ai_deadline} |")
        else:
            lines.append("- *(未提取到决议事项)*")

        lines.extend(["", "---", "", "## 👤 责任人汇总", ""])
        if extraction.responsible_persons:
            for p in extraction.responsible_persons:
                lines.append(f"- {p}")
        else:
            lines.append("- *(未提取到责任人)*")

        lines.extend(["", "---", "", "## 📅 截止时间节点", ""])
        if extraction.deadlines:
            for d in extraction.deadlines:
                lines.append(f"- {d}")
        else:
            lines.append("- *(未提取到截止时间)*")

        lines.extend(["", "---", "", "## 📝 原始转录（部分）", "", "```", transcript_preview, "```"])
        lines.extend(["", "> 🤖 本纪要由 SafeGuard-AI 智能会议纪要模块自动生成"])

        return "\n".join(lines)
