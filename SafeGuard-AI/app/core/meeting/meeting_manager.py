"""
会议纪要全流程编排器

实现技术方案功能 14 — 智能会议纪要的端到端执行：
    音频 → 转录 → NER提取 → Markdown生成 → 知识库归档

MeetingManager 作为统一入口，协调四个子模块完成全流程。
支持优雅降级：每阶段失败时返回明确的错误状态，不影响已完成的阶段。
"""
import logging
from typing import Any, Dict, Optional

from app.config import get_settings
from app.core.meeting.transcriber import BaseTranscriber, MockTranscriber, create_transcriber
from app.core.meeting.extractor import MeetingExtractor, MeetingExtractionResult
from app.core.meeting.minutes_generator import MinutesGenerator, MeetingMinutes

logger = logging.getLogger(__name__)


class MeetingManager:
    """
    会议纪要全流程管理器。

    协调 ASR 转录 → NER 提取 → 纪要生成 → 知识库归档 的完整流程。

    使用方式:
        manager = MeetingManager()
        minutes = await manager.process_meeting("weekly_safety.mp3")
        print(minutes.markdown_content)
    """

    def __init__(self):
        """初始化管理器，从配置读取转录模式。"""
        settings = get_settings()
        asr_mode = getattr(settings, 'meeting', None)
        if asr_mode is not None:
            asr_mode = getattr(asr_mode, 'asr_mode', 'mock')
        else:
            asr_mode = 'mock'

        self._transcriber: BaseTranscriber = create_transcriber(mode=asr_mode)
        self._extractor = MeetingExtractor()
        self._generator = MinutesGenerator()

    async def process_meeting(
        self,
        audio_path: str,
        meeting_title: str = "",
        archive_to_kb: bool = True,
    ) -> MeetingMinutes:
        """
        处理一次会议：从音频到归档的完整流程。

        流程:
            1. ASR 音频转录
            2. NER 结构化信息提取
            3. Markdown 纪要生成
            4. 知识库归档（可选）

        Args:
            audio_path: 音频文件路径或标识（Mock模式下用于场景匹配）
            meeting_title: 会议标题（为空则从内容推断）
            archive_to_kb: 是否归档到知识库

        Returns:
            MeetingMinutes 完整纪要

        Raises:
            RuntimeError: 转录阶段失败（上游错误，无法继续）
        """
        logger.info(f"[MeetingManager] 开始处理会议: audio={audio_path[:80]}")

        # ---- 阶段 1: 转录 ----
        try:
            transcript = await self._transcriber.transcribe(audio_path)
            logger.info(f"[MeetingManager] 转录完成: {len(transcript)} 字符")
        except Exception as e:
            logger.error(f"[MeetingManager] 转录失败: {e}", exc_info=True)
            raise RuntimeError(f"音频转录失败: {e}") from e

        # ---- 阶段 2: 信息提取 ----
        extraction = await self._extractor.extract(transcript)

        # ---- 阶段 3: 纪要生成 ----
        if archive_to_kb:
            minutes = await self._generator.generate_and_archive(
                extraction,
                title=meeting_title,
            )
        else:
            minutes = await self._generator.generate(
                extraction,
                title=meeting_title,
            )

        logger.info(
            f"[MeetingManager] 处理完成: meeting_id={minutes.meeting_id}, "
            f"提取方式={extraction.extraction_method}, "
            f"归档={'✅' if minutes.archived_to_kb else '❌'}"
        )
        return minutes

    async def process_meeting_text(
        self,
        transcript: str,
        meeting_title: str = "",
        archive_to_kb: bool = True,
    ) -> MeetingMinutes:
        """
        直接从文本处理（跳过转录阶段）。

        适用于已有转录文本的场景（如手动输入、历史记录导入）。

        Args:
            transcript: 会议转录文本
            meeting_title: 会议标题
            archive_to_kb: 是否归档到知识库

        Returns:
            MeetingMinutes 完整纪要
        """
        logger.info(f"[MeetingManager] 从文本处理: {len(transcript)} 字符")

        extraction = await self._extractor.extract(transcript)

        if archive_to_kb:
            minutes = await self._generator.generate_and_archive(
                extraction,
                title=meeting_title,
            )
        else:
            minutes = await self._generator.generate(
                extraction,
                title=meeting_title,
            )

        logger.info(
            f"[MeetingManager] 文本处理完成: meeting_id={minutes.meeting_id}"
        )
        return minutes

    def get_available_scenarios(self) -> list:
        """
        列出可用的 Mock 会议场景。

        Returns:
            场景列表 [{meeting_id, title, date}]
        """
        if isinstance(self._transcriber, MockTranscriber):
            return self._transcriber.list_scenarios()
        return []
