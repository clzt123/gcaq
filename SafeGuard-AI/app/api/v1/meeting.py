"""
智能会议纪要 API 接口

提供会议音频分析、纪要生成、场景查询等 RESTful 接口。

接口清单:
    POST /api/v1/meeting/minutes     — 提交音频进行纪要生成
    POST /api/v1/meeting/minutes/text — 从文本直接生成纪要（跳过转录）
    GET  /api/v1/meeting/scenarios    — 查询可用 Mock 场景
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.meeting.meeting_manager import MeetingManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/meeting", tags=["智能会议纪要"])


# =========================
# Pydantic 请求/响应模型
# =========================


class MeetingMinutesRequest(BaseModel):
    """
    会议纪要生成请求体。
    """

    audio_path: str = Field(..., description="音频文件路径（Mock 模式下用于场景匹配）")
    title: str = Field("", description="会议标题（为空则从内容推断）")
    archive: bool = Field(True, description="是否归档到知识库")


class MeetingTextRequest(BaseModel):
    """
    从文本直接生成纪要的请求体。
    """

    transcript: str = Field(..., description="会议转录文本")
    title: str = Field("", description="会议标题（为空则从内容推断）")
    archive: bool = Field(True, description="是否归档到知识库")


class ActionItemResponse(BaseModel):
    """决议项响应。"""

    item: str = ""
    assignee: str = ""
    deadline: str = ""


class ExtractionResponse(BaseModel):
    """信息提取结果响应。"""

    title: str = ""
    attendees: list[str] = Field(default_factory=list)
    responsible_persons: list[str] = Field(default_factory=list)
    deadlines: list[str] = Field(default_factory=list)
    action_items: list[dict] = Field(default_factory=list)
    key_topics: list[str] = Field(default_factory=list)
    risk_mentions: list[str] = Field(default_factory=list)
    extraction_method: str = ""


class MeetingMinutesResponse(BaseModel):
    """
    会议纪要响应体。
    """

    meeting_id: str = Field("", description="会议唯一标识")
    title: str = Field("", description="会议标题")
    markdown_content: str = Field("", description="完整 Markdown 纪要")
    extraction: ExtractionResponse = Field(default_factory=ExtractionResponse)
    archived_to_kb: bool = Field(False, description="是否已归档")
    kb_chunk_count: int = Field(0, description="归档分块数")
    generated_at: str = Field("", description="生成时间")


# =========================
# 路由
# =========================


@router.post("/minutes", response_model=MeetingMinutesResponse)
async def generate_minutes(request: MeetingMinutesRequest) -> MeetingMinutesResponse:
    """
    提交音频文件生成会议纪要。

    完整链路:
        音频 → ASR 转录 → NER 提取 → Markdown 生成 → 知识库归档

    Mock 模式下，audio_path 用于场景匹配：
        - 含 'weekly'  → 周安全例会
        - 含 'accident' → 事故复盘会
        - 含 'drill'    → 应急演练总结
        - 其他 → 默认第一条

    Args:
        request: 包含音频路径和可选标题的请求体

    Returns:
        MeetingMinutesResponse: 完整纪要，含 Markdown 文本和提取结果
    """
    logger.info(f"[API/Meeting] 收到纪要生成请求: audio={request.audio_path[:80]}")

    try:
        manager = MeetingManager()
        minutes = await manager.process_meeting(
            audio_path=request.audio_path,
            meeting_title=request.title,
            archive_to_kb=request.archive,
        )

        extraction = ExtractionResponse(
            title=minutes.extraction.title,
            attendees=minutes.extraction.attendees,
            responsible_persons=minutes.extraction.responsible_persons,
            deadlines=minutes.extraction.deadlines,
            action_items=minutes.extraction.action_items,
            key_topics=minutes.extraction.key_topics,
            risk_mentions=minutes.extraction.risk_mentions,
            extraction_method=minutes.extraction.extraction_method,
        )

        response = MeetingMinutesResponse(
            meeting_id=minutes.meeting_id,
            title=minutes.title,
            markdown_content=minutes.markdown_content,
            extraction=extraction,
            archived_to_kb=minutes.archived_to_kb,
            kb_chunk_count=len(minutes.kb_chunk_ids),
            generated_at=minutes.generated_at,
        )

        logger.info(
            f"[API/Meeting] 纪要生成成功: meeting_id={minutes.meeting_id}, "
            f"extraction_method={extraction.extraction_method}"
        )
        return response

    except RuntimeError as e:
        logger.error(f"[API/Meeting] 转录失败: {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"[API/Meeting] 处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"会议纪要生成失败: {str(e)}")


@router.post("/minutes/text", response_model=MeetingMinutesResponse)
async def generate_minutes_from_text(
    request: MeetingTextRequest,
) -> MeetingMinutesResponse:
    """
    从文本直接生成会议纪要（跳过转录阶段）。

    适用于：
        - 已有手动输入的转录文本
        - 历史记录导入
        - 即时会议记录

    Args:
        request: 包含转录文本和可选标题的请求体

    Returns:
        MeetingMinutesResponse: 完整纪要
    """
    logger.info(f"[API/Meeting] 收到文本纪要生成请求: {len(request.transcript)} 字符")

    try:
        manager = MeetingManager()
        minutes = await manager.process_meeting_text(
            transcript=request.transcript,
            meeting_title=request.title,
            archive_to_kb=request.archive,
        )

        extraction = ExtractionResponse(
            title=minutes.extraction.title,
            attendees=minutes.extraction.attendees,
            responsible_persons=minutes.extraction.responsible_persons,
            deadlines=minutes.extraction.deadlines,
            action_items=minutes.extraction.action_items,
            key_topics=minutes.extraction.key_topics,
            risk_mentions=minutes.extraction.risk_mentions,
            extraction_method=minutes.extraction.extraction_method,
        )

        response = MeetingMinutesResponse(
            meeting_id=minutes.meeting_id,
            title=minutes.title,
            markdown_content=minutes.markdown_content,
            extraction=extraction,
            archived_to_kb=minutes.archived_to_kb,
            kb_chunk_count=len(minutes.kb_chunk_ids),
            generated_at=minutes.generated_at,
        )

        logger.info(
            f"[API/Meeting] 文本纪要生成成功: meeting_id={minutes.meeting_id}"
        )
        return response

    except Exception as e:
        logger.error(f"[API/Meeting] 处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"纪要生成失败: {str(e)}")


@router.get("/scenarios")
async def list_scenarios() -> dict:
    """
    查询可用的 Mock 会议场景。

    Returns:
        dict: 含 total 和 scenarios 列表
    """
    manager = MeetingManager()
    scenarios = manager.get_available_scenarios()
    return {
        "total": len(scenarios),
        "scenarios": scenarios,
    }
