"""
音频转录层

实现技术方案功能 14 — ASR 音频转录：
    - BaseTranscriber: 抽象基类
    - MockTranscriber: 从 mock_data/meeting_transcripts.json 加载预置文本
    - WhisperTranscriber: OpenAI Whisper API 转录（预留接口）

所有转录器均返回 str 类型的转录文本。
"""
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from app.utils import get_mock_path

logger = logging.getLogger(__name__)


class BaseTranscriber(ABC):
    """
    音频转录抽象基类。

    所有转录器实现必须继承此类并实现 transcribe 方法。
    """

    @abstractmethod
    async def transcribe(self, audio_path: str) -> str:
        """
        将音频文件转录为文本。

        Args:
            audio_path: 音频文件路径或 URL

        Returns:
            转录文本

        Raises:
            FileNotFoundError: 文件不存在
            RuntimeError: 转录失败
        """
        ...


class MockTranscriber(BaseTranscriber):
    """
    Mock 转录器。

    从 mock_data/meeting_transcripts.json 加载预置会议转录文本。
    通过 audio_path 中的文件名匹配对应场景：
        - 文件名含 "weekly" → 周安全例会
        - 文件名含 "accident" → 事故复盘会
        - 文件名含 "drill" → 应急演练总结
        - 否则返回第一条（默认）

    使用方式:
        transcriber = MockTranscriber()
        text = await transcriber.transcribe("weekly_safety.mp3")
    """

    def __init__(self):
        """初始化 Mock 转录器，加载预置转录文本。"""
        self._transcripts: list = []
        self._by_id: Dict[str, dict] = {}
        self._load_transcripts()

    def _load_transcripts(self):
        """从 JSON 文件加载预置会议转录文本。"""
        try:
            path = get_mock_path("meeting_transcripts.json")
            with open(path, "r", encoding="utf-8") as f:
                self._transcripts = json.load(f)

            for t in self._transcripts:
                self._by_id[t["meeting_id"]] = t

            logger.info(
                f"[MockTranscriber] 加载 {len(self._transcripts)} 份预置会议转录文本"
            )
        except Exception as e:
            logger.error(f"[MockTranscriber] 加载失败: {e}", exc_info=True)
            self._transcripts = []
            self._by_id = {}

    async def transcribe(self, audio_path: str) -> str:
        """
        Mock 转录：匹配文件名到预置场景。

        匹配规则:
            - 'weekly'  → 周安全例会
            - 'accident' → 事故复盘会
            - 'drill'    → 应急演练总结
            - 默认       → 第一条

        Args:
            audio_path: 音频文件名（用于场景匹配）

        Returns:
            预置会议转录文本

        Raises:
            RuntimeError: 无预置转录文本可用
        """
        if not self._transcripts:
            raise RuntimeError("无预置转录文本可用，请检查 mock_data/meeting_transcripts.json")

        audio_lower = audio_path.lower()
        matched = self._transcripts[0]  # 默认第一条

        if "weekly" in audio_lower:
            matched = self._by_id.get("MEET-20240603-001", self._transcripts[0])
            logger.info(f"[MockTranscriber] 匹配场景: 周安全例会 → {matched['meeting_id']}")
        elif "accident" in audio_lower:
            matched = self._by_id.get("MEET-20240605-001", self._transcripts[0])
            logger.info(f"[MockTranscriber] 匹配场景: 事故复盘会 → {matched['meeting_id']}")
        elif "drill" in audio_lower:
            matched = self._by_id.get("MEET-20240607-001", self._transcripts[0])
            logger.info(f"[MockTranscriber] 匹配场景: 应急演练总结 → {matched['meeting_id']}")
        else:
            logger.info(
                f"[MockTranscriber] 无匹配场景 ({audio_path})，使用默认: {matched['meeting_id']}"
            )

        return matched["transcript"]

    def list_scenarios(self) -> list:
        """
        列出所有可用场景。

        Returns:
            场景列表，每项含 meeting_id、title、date
        """
        return [
            {
                "meeting_id": t["meeting_id"],
                "title": t["title"],
                "date": t["date"],
                "duration_minutes": t.get("duration_minutes", 0),
            }
            for t in self._transcripts
        ]


class WhisperTranscriber(BaseTranscriber):
    """
    OpenAI Whisper API 转录器（预留接口）。

    通过配置中的 MEETING_ASR_API_KEY 切换。
    当前为占位实现，调用 transcribe 时返回未实现提示。

    使用方式:
        transcriber = WhisperTranscriber(api_key="sk-xxx")
        text = await transcriber.transcribe("/path/to/audio.mp3")
    """

    def __init__(self, api_key: str = "", model: str = "whisper-1"):
        """
        初始化 Whisper 转录器。

        Args:
            api_key: OpenAI API 密钥
            model: Whisper 模型名称
        """
        self.api_key = api_key
        self.model = model
        self._client: Optional[Any] = None

    async def transcribe(self, audio_path: str) -> str:
        """
        通过 OpenAI Whisper API 转录音频（预留接口）。

        TODO: 接入真实 Whisper API 调用。
              当前返回占位提示。

        Args:
            audio_path: 音频文件路径

        Returns:
            转录文本（当前为占位提示）
        """
        logger.warning(
            "[WhisperTranscriber] 真实 Whisper API 尚未接入，"
            "请使用 MockTranscriber 进行开发测试。"
        )
        raise NotImplementedError(
            "Whisper API 转录尚未实现。开发测试请使用 MockTranscriber。\n"
            "预计集成方式：\n"
            "  1. 通过 DashScope 语音识别 API\n"
            "  2. 或自部署 funasr/whisper 服务\n"
            "请在 app/config.py 中设置 MEETING_ASR_MODE=mock"
        )


# =========================
# 工厂函数
# =========================


def create_transcriber(mode: str = "mock", **kwargs) -> BaseTranscriber:
    """
    根据模式创建转录器实例。

    Args:
        mode: 转录模式 ("mock" / "whisper_api" / "dashscope_asr")
        **kwargs: 传递给具体转录器的参数

    Returns:
        BaseTranscriber 实例

    Raises:
        ValueError: 不支持的转录模式
    """
    if mode == "mock":
        return MockTranscriber()
    elif mode in ("whisper_api", "dashscope_asr"):
        logger.warning(
            f"[Transcriber] 模式 '{mode}' 尚未完全实现，降级为 MockTranscriber"
        )
        return MockTranscriber()
    else:
        raise ValueError(
            f"不支持的转录模式: '{mode}'。可选: mock, whisper_api, dashscope_asr"
        )
