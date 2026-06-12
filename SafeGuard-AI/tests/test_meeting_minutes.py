"""
智能会议纪要模块测试

测试范围:
    - Mock 转录器：场景加载与匹配
    - 正则兜底提取器：中文 NER 提取
    - 纪要生成器：Markdown 渲染 + 归档
    - 全流程管理器：端到端流程

设计原则：
    - 不依赖外部服务（LLM API、Milvus 等）
    - Mock 模式优先，测试核心逻辑
    - 遵循项目现有 pytest + pytest-asyncio 模式
"""
import pytest

from app.core.meeting.transcriber import (
    MockTranscriber,
    BaseTranscriber,
    create_transcriber,
)
from app.core.meeting.extractor import (
    MeetingExtractor,
    MeetingExtractionResult,
    _RegexExtractor,
)
from app.core.meeting.minutes_generator import (
    MinutesGenerator,
    MeetingMinutes,
    MINUTES_TEMPLATE,
)
from app.core.meeting.meeting_manager import MeetingManager


# =========================
# 测试数据
# =========================

SAMPLE_TRANSCRIPT = """张建国（安全总监）：今天开周安全例会，通报上周检查情况。
上周排查出3处隐患：焊接车间通风系统滤网堵塞，化学品库温湿度传感器离线，3号货梯紧急按钮无响应。

李明辉（设备主管）：通风系统滤网清洗今天下午安排，截止6月10日完成。
货梯紧急按钮今天联系维保单位，最迟周三前修好。

王芳（化学品库管理员）：温湿度传感器已报修，厂家明天来更换。

张建国：好，决议如下：
第一，通风系统滤网清洗——李明辉负责，截止6月10日；
第二，货梯紧急按钮检修——李明辉负责，截止6月12日；
第三，温湿度传感器更换——王芳跟进。
散会。"""


# =========================
# 1. MockTranscriber 测试
# =========================


class TestMockTranscriber:
    """Mock 转录器测试"""

    def test_load_transcripts(self):
        """测试加载预置转录文本"""
        transcriber = MockTranscriber()
        scenarios = transcriber.list_scenarios()
        assert len(scenarios) == 3, f"应有 3 个场景，实际加载 {len(scenarios)}"

    @pytest.mark.asyncio
    async def test_transcribe_weekly(self):
        """测试匹配周安全例会场景"""
        transcriber = MockTranscriber()
        text = await transcriber.transcribe("weekly_safety.mp3")
        assert "周安全例会" in text or "焊接车间" in text
        assert len(text) > 100

    @pytest.mark.asyncio
    async def test_transcribe_accident(self):
        """测试匹配事故复盘会场景"""
        transcriber = MockTranscriber()
        text = await transcriber.transcribe("accident_review.mp3")
        assert "液压油管" in text
        assert len(text) > 100

    @pytest.mark.asyncio
    async def test_transcribe_drill(self):
        """测试匹配应急演练总结场景"""
        transcriber = MockTranscriber()
        text = await transcriber.transcribe("drill_summary.mp3")
        assert "消防疏散" in text
        assert len(text) > 100

    @pytest.mark.asyncio
    async def test_transcribe_default_fallback(self):
        """测试无匹配时返回默认场景"""
        transcriber = MockTranscriber()
        text = await transcriber.transcribe("unknown_meeting.mp3")
        assert len(text) > 100  # 应该有内容

    @pytest.mark.asyncio
    async def test_transcribe_empty_store_raises(self):
        """测试无预置文本时抛出 RuntimeError"""
        transcriber = MockTranscriber()
        transcriber._transcripts = []
        transcriber._by_id = {}
        with pytest.raises(RuntimeError, match="无预置转录文本"):
            await transcriber.transcribe("test.mp3")

    def test_list_scenarios_structure(self):
        """测试场景列表结构完整性"""
        transcriber = MockTranscriber()
        scenarios = transcriber.list_scenarios()
        for s in scenarios:
            assert "meeting_id" in s
            assert "title" in s
            assert "date" in s
            assert "duration_minutes" in s


# =========================
# 2. 工厂函数测试
# =========================


class TestTranscriberFactory:
    """转录器工厂函数测试"""

    def test_create_mock(self):
        """测试创建 Mock 转录器"""
        t = create_transcriber("mock")
        assert isinstance(t, MockTranscriber)

    def test_create_whisper_falls_back_to_mock(self):
        """测试 whisper_api 模式降级为 Mock"""
        t = create_transcriber("whisper_api")
        assert isinstance(t, MockTranscriber)  # 当前降级

    def test_create_invalid_mode_raises(self):
        """测试无效模式抛出 ValueError"""
        with pytest.raises(ValueError, match="不支持的转录模式"):
            create_transcriber("invalid_mode")


# =========================
# 3. RegexExtractor 正则提取测试
# =========================


class TestRegexExtractor:
    """正则兜底提取器测试"""

    def test_extract_attendees(self):
        """测试提取参会人员"""
        extractor = _RegexExtractor()
        result = extractor.extract(SAMPLE_TRANSCRIPT)
        assert len(result.attendees) >= 2
        names_found = any("张建国" in a or "李明辉" in a for a in result.attendees)
        assert names_found

    def test_extract_responsible_persons(self):
        """测试提取责任人"""
        extractor = _RegexExtractor()
        result = extractor.extract(SAMPLE_TRANSCRIPT)
        responsible = result.responsible_persons
        assert len(responsible) >= 1, f"应至少有1个责任人: {responsible}"

    def test_extract_action_items(self):
        """测试提取决议项"""
        extractor = _RegexExtractor()
        result = extractor.extract(SAMPLE_TRANSCRIPT)
        assert len(result.action_items) >= 1, f"应至少有1个决议项: {result.action_items}"

    def test_extract_risk_mentions(self):
        """测试提取风险提及"""
        extractor = _RegexExtractor()
        result = extractor.extract(SAMPLE_TRANSCRIPT)
        assert len(result.risk_mentions) >= 1, f"应至少有1条风险提及: {result.risk_mentions}"

    def test_extraction_method_is_regex(self):
        """测试提取方式标记为 regex_fallback"""
        extractor = _RegexExtractor()
        result = extractor.extract(SAMPLE_TRANSCRIPT)
        assert result.extraction_method == "regex_fallback"

    def test_empty_transcript(self):
        """测试空文本处理"""
        extractor = _RegexExtractor()
        result = extractor.extract("")
        assert result.title == ""
        assert result.attendees == []
        assert result.action_items == []

    def test_extract_deadlines(self):
        """测试提取截止时间"""
        extractor = _RegexExtractor()
        result = extractor.extract(SAMPLE_TRANSCRIPT)
        assert len(result.deadlines) >= 1, f"应至少有1个截止时间: {result.deadlines}"

    def test_infer_title(self):
        """测试标题推断"""
        extractor = _RegexExtractor()
        title = extractor._infer_title(SAMPLE_TRANSCRIPT)
        assert "例会" in title


# =========================
# 4. MeetingExtractor 测试（含降级）
# =========================


class TestMeetingExtractor:
    """LLM + 正则组合提取器测试"""

    @pytest.mark.asyncio
    async def test_extract_returns_result(self):
        """测试提取返回有效结果"""
        extractor = MeetingExtractor()
        result = await extractor.extract(SAMPLE_TRANSCRIPT)
        assert isinstance(result, MeetingExtractionResult)
        assert result.raw_transcript == SAMPLE_TRANSCRIPT

    @pytest.mark.asyncio
    async def test_extract_empty_transcript(self):
        """测试空转录文本"""
        extractor = MeetingExtractor()
        result = await extractor.extract("")
        assert isinstance(result, MeetingExtractionResult)

    @pytest.mark.asyncio
    async def test_extract_with_long_transcript(self):
        """测试长文本提取"""
        extractor = MeetingExtractor()
        long_text = "张工负责检查。" * 300  # ~3000 chars
        result = await extractor.extract(long_text)
        assert isinstance(result, MeetingExtractionResult)


# =========================
# 5. MinutesGenerator 纪要生成测试
# =========================


class TestMinutesGenerator:
    """纪要生成器测试"""

    @pytest.mark.asyncio
    async def test_generate_markdown(self):
        """测试生成 Markdown 纪要"""
        generator = MinutesGenerator()
        extraction = _RegexExtractor().extract(SAMPLE_TRANSCRIPT)

        minutes = await generator.generate(
            extraction,
            title="周安全例会测试",
            meeting_id="MEET-TEST-001",
        )

        assert isinstance(minutes, MeetingMinutes)
        assert minutes.meeting_id == "MEET-TEST-001"
        assert minutes.title == "周安全例会测试"
        assert "# 周安全例会测试" in minutes.markdown_content
        assert "参会人员" in minutes.markdown_content
        assert "决议事项" in minutes.markdown_content

    @pytest.mark.asyncio
    async def test_generate_auto_meeting_id(self):
        """测试自动生成 meeting_id"""
        generator = MinutesGenerator()
        extraction = _RegexExtractor().extract(SAMPLE_TRANSCRIPT)

        minutes = await generator.generate(extraction, title="测试会议")
        assert minutes.meeting_id.startswith("MEET-")
        assert len(minutes.meeting_id) > 10

    @pytest.mark.asyncio
    async def test_generate_without_title(self):
        """测试无标题时从提取结果推断"""
        generator = MinutesGenerator()
        extraction = _RegexExtractor().extract(SAMPLE_TRANSCRIPT)

        minutes = await generator.generate(extraction)
        assert minutes.title  # 应有标题
        assert len(minutes.markdown_content) > 100

    @pytest.mark.asyncio
    async def test_generate_and_archive(self):
        """测试生成并归档到知识库"""
        generator = MinutesGenerator()
        extraction = _RegexExtractor().extract(SAMPLE_TRANSCRIPT)

        minutes = await generator.generate_and_archive(
            extraction,
            title="归档测试会议",
        )

        assert isinstance(minutes, MeetingMinutes)
        assert minutes.archived_to_kb is True
        assert len(minutes.kb_chunk_ids) > 0

    @pytest.mark.asyncio
    async def test_markdown_has_required_sections(self):
        """测试 Markdown 包含所有必需章节"""
        generator = MinutesGenerator()
        extraction = _RegexExtractor().extract(SAMPLE_TRANSCRIPT)
        minutes = await generator.generate(extraction, title="测试")

        required_sections = [
            "参会人员",
            "关键议题",
            "风险",
            "决议事项",
            "责任人",
            "截止时间",
        ]
        for section in required_sections:
            assert section in minutes.markdown_content, f"缺少章节: {section}"

    @pytest.mark.asyncio
    async def test_fallback_render_without_jinja2(self):
        """测试 Jinja2 不可用时的纯文本兜底"""
        generator = MinutesGenerator()
        generator._template = None  # 模拟 Jinja2 不可用
        extraction = _RegexExtractor().extract(SAMPLE_TRANSCRIPT)

        minutes = await generator.generate(extraction, title="兜底测试")
        assert len(minutes.markdown_content) > 100
        assert "# 兜底测试" in minutes.markdown_content


# =========================
# 6. MeetingManager 全流程测试
# =========================


class TestMeetingManager:
    """全流程管理器测试"""

    @pytest.mark.asyncio
    async def test_process_meeting_weekly(self):
        """测试处理周安全例会音频"""
        manager = MeetingManager()
        minutes = await manager.process_meeting(
            audio_path="weekly_safety.mp3",
            meeting_title="第23周安全例会",
            archive_to_kb=False,
        )
        assert isinstance(minutes, MeetingMinutes)
        assert "周安全例会" in minutes.title or "第23周" in minutes.title
        assert len(minutes.markdown_content) > 200
        assert minutes.extraction is not None

    @pytest.mark.asyncio
    async def test_process_meeting_accident(self):
        """测试处理事故复盘会音频"""
        manager = MeetingManager()
        minutes = await manager.process_meeting(
            audio_path="accident_review.mp3",
            archive_to_kb=False,
        )
        assert isinstance(minutes, MeetingMinutes)
        assert len(minutes.markdown_content) > 200

    @pytest.mark.asyncio
    async def test_process_meeting_drill(self):
        """测试处理应急演练总结音频"""
        manager = MeetingManager()
        minutes = await manager.process_meeting(
            audio_path="drill_summary.mp3",
            archive_to_kb=False,
        )
        assert isinstance(minutes, MeetingMinutes)
        assert len(minutes.markdown_content) > 200

    @pytest.mark.asyncio
    async def test_process_meeting_with_archive(self):
        """测试处理会议并归档"""
        manager = MeetingManager()
        minutes = await manager.process_meeting(
            audio_path="weekly_safety.mp3",
            archive_to_kb=True,
        )
        assert minutes.archived_to_kb is True
        assert len(minutes.kb_chunk_ids) > 0

    @pytest.mark.asyncio
    async def test_process_meeting_text(self):
        """测试从文本直接处理"""
        manager = MeetingManager()
        minutes = await manager.process_meeting_text(
            transcript=SAMPLE_TRANSCRIPT,
            meeting_title="直接文本测试",
            archive_to_kb=False,
        )
        assert isinstance(minutes, MeetingMinutes)
        assert len(minutes.markdown_content) > 100

    @pytest.mark.asyncio
    async def test_process_meeting_default_title(self):
        """测试无标题时的自动推断"""
        manager = MeetingManager()
        minutes = await manager.process_meeting(
            audio_path="weekly_safety.mp3",
            meeting_title="",
            archive_to_kb=False,
        )
        assert minutes.title

    def test_get_scenarios(self):
        """测试获取可用场景列表"""
        manager = MeetingManager()
        scenarios = manager.get_available_scenarios()
        assert len(scenarios) == 3

    @pytest.mark.asyncio
    async def test_process_meeting_runtime_error(self):
        """测试转录失败时抛出 RuntimeError"""
        manager = MeetingManager()
        if isinstance(manager._transcriber, MockTranscriber):
            manager._transcriber._transcripts = []
            manager._transcriber._by_id = {}
        with pytest.raises(RuntimeError, match="转录失败"):
            await manager.process_meeting("test.mp3")


# =========================
# 7. MeetingExtractionResult 数据模型测试
# =========================


class TestMeetingExtractionResult:
    """数据模型测试"""

    def test_default_values(self):
        """测试默认值"""
        result = MeetingExtractionResult()
        assert result.title == ""
        assert result.attendees == []
        assert result.action_items == []
        assert result.extraction_method == "regex_fallback"

    def test_full_construction(self):
        """测试完整构造"""
        result = MeetingExtractionResult(
            title="测试会议",
            attendees=["张三", "李四"],
            responsible_persons=["张三"],
            deadlines=["6月10日"],
            action_items=[{"item": "修设备", "assignee": "张三", "deadline": "6月10日"}],
            key_topics=["安全生产"],
            risk_mentions=["设备故障"],
            raw_transcript="...",
            extraction_method="llm",
        )
        assert result.title == "测试会议"
        assert len(result.attendees) == 2
        assert result.extraction_method == "llm"


# =========================
# 8. MeetingMinutes 数据模型测试
# =========================


class TestMeetingMinutes:
    """纪要数据模型测试"""

    def test_default_values(self):
        """测试默认值"""
        extraction = MeetingExtractionResult()
        minutes = MeetingMinutes(
            meeting_id="M-001",
            title="测试",
            markdown_content="...",
            extraction=extraction,
        )
        assert minutes.archived_to_kb is False
        assert minutes.kb_chunk_ids == []
        assert minutes.generated_at == ""


# =========================
# 9. MINUTES_TEMPLATE 模板测试
# =========================


class TestMinutesTemplate:
    """模板完整性测试"""

    def test_template_contains_key_sections(self):
        """测试模板包含所有关键章节"""
        assert "参会人员" in MINUTES_TEMPLATE
        assert "关键议题" in MINUTES_TEMPLATE
        assert "风险" in MINUTES_TEMPLATE
        assert "决议事项" in MINUTES_TEMPLATE
        assert "责任人" in MINUTES_TEMPLATE
        assert "截止时间" in MINUTES_TEMPLATE
        assert "原始转录" in MINUTES_TEMPLATE
