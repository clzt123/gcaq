"""
智能会议纪要模块

实现技术方案功能 14 — 智能会议纪要：
    1. ASR 音频转录（Mock + Whisper API 预留）
    2. LLM 命名实体提取 + 正则兜底
    3. Markdown 纪要生成 + 知识库归档

独立模块，无功能依赖。
"""

from app.core.meeting.transcriber import BaseTranscriber, MockTranscriber
from app.core.meeting.extractor import MeetingExtractor, MeetingExtractionResult
from app.core.meeting.minutes_generator import MinutesGenerator, MeetingMinutes
from app.core.meeting.meeting_manager import MeetingManager

__all__ = [
    "BaseTranscriber",
    "MockTranscriber",
    "MeetingExtractor",
    "MeetingExtractionResult",
    "MinutesGenerator",
    "MeetingMinutes",
    "MeetingManager",
]
