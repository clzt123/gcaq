"""
反思与进化模块测试

测试范围:
    - PositiveFeedbackCollector: 正反馈记录、检索、导出
    - NegativeSampleManager: 负样本添加、查找、清理
    - ModelRegistry: 版本注册、热加载、回滚
    - EvolutionManager: 端到端流程
"""
import json
import tempfile
import shutil
from pathlib import Path

import pytest

from app.core.evolution.positive_feedback import (
    PositiveFeedbackCollector,
    PositiveSample,
)
from app.core.evolution.negative_sample import (
    NegativeSampleManager,
    NegativeSampleEntry,
)
from app.core.evolution.model_registry import (
    ModelRegistry,
    ModelVersion,
    ModelStatus,
)
from app.core.evolution.evolution_manager import (
    EvolutionManager,
    EvolutionReport,
)


# =========================
# Helper: temp directory
# =========================

@pytest.fixture
def temp_dir():
    """创建临时目录用于测试存储。"""
    d = tempfile.mkdtemp(prefix="sg_test_evolution_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# =========================
# 1. PositiveFeedbackCollector 测试
# =========================


class TestPositiveFeedbackCollector:
    """正反馈收集器测试"""

    def test_record_positive(self, temp_dir):
        """测试记录正反馈"""
        coll = PositiveFeedbackCollector(storage_dir=temp_dir)
        sid = coll.record_positive(
            feedback_type="adopted",
            user_id="EMP_001",
            input_context={"alert_id": "ALT-001"},
            ai_response={"type": "oil_leak", "action": "create_ticket"},
            user_comment="判断准确，已采纳",
        )
        assert sid.startswith("POS-")
        assert len(coll._samples) == 1

    def test_record_invalid_type_raises(self, temp_dir):
        """测试无效反馈类型抛出异常"""
        coll = PositiveFeedbackCollector(storage_dir=temp_dir)
        with pytest.raises(ValueError, match="无效的正反馈类型"):
            coll.record_positive(
                feedback_type="invalid_type",
                user_id="EMP_001",
                input_context={},
                ai_response={},
            )

    def test_get_samples_filtered(self, temp_dir):
        """测试按类型过滤检索"""
        coll = PositiveFeedbackCollector(storage_dir=temp_dir)
        coll.record_positive("adopted", "EMP_001", {}, {})
        coll.record_positive("liked", "EMP_002", {}, {})
        coll.record_positive("adopted", "EMP_003", {}, {})

        adopted = coll.get_positive_samples(feedback_type="adopted", limit=10)
        assert len(adopted) == 2

    def test_get_samples_as_fewshot(self, temp_dir):
        """测试导出 Few-shot 格式"""
        coll = PositiveFeedbackCollector(storage_dir=temp_dir)
        coll.record_positive("adopted", "EMP_001", {"image": "test"}, {"result": "ok"})

        fewshot = coll.get_samples_as_fewshot(limit=5)
        assert len(fewshot) == 1
        assert "input" in fewshot[0]
        assert "output" in fewshot[0]

    def test_export_sft_data(self, temp_dir):
        """测试导出 SFT 训练数据"""
        coll = PositiveFeedbackCollector(storage_dir=temp_dir)
        for i in range(5):
            coll.record_positive(
                "adopted", f"EMP_{i:03d}",
                {"id": f"A{i}"}, {"result": f"R{i}"},
            )

        output = coll.export_sft_data()
        assert Path(output).exists()

        with open(output, "r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) == 5

            # 每条是有效 JSON
            for line in lines:
                record = json.loads(line)
                assert "messages" in record
                assert len(record["messages"]) == 2

    def test_record_batch(self, temp_dir):
        """测试批量记录"""
        coll = PositiveFeedbackCollector(storage_dir=temp_dir)
        feedbacks = [
            {"feedback_type": "adopted", "user_id": "U1", "input_context": {}, "ai_response": {}},
            {"feedback_type": "liked", "user_id": "U2", "input_context": {}, "ai_response": {}},
        ]
        ids = coll.record_batch(feedbacks)
        assert len(ids) == 2
        assert len(coll._samples) == 2

    def test_stats(self, temp_dir):
        """测试统计"""
        coll = PositiveFeedbackCollector(storage_dir=temp_dir)
        coll.record_positive("adopted", "EMP_001", {}, {})
        coll.record_positive("liked", "EMP_001", {}, {})

        stats = coll.stats()
        assert stats["total_samples"] == 2
        assert stats["by_type"]["adopted"] == 1


# =========================
# 2. NegativeSampleManager 测试
# =========================


class TestNegativeSampleManager:
    """负样本管理器测试"""

    def test_add_from_feedback(self, temp_dir):
        """测试从反馈添加负样本"""
        mgr = NegativeSampleManager(storage_dir=temp_dir)
        eid = mgr.add_from_feedback(
            image_id="IMG-001",
            image_hash="0xABCD1234",
            false_prediction={"type": "oil_leak", "confidence": 0.91},
            correct_label={"type": "water_spill"},
        )
        assert eid.startswith("NEG-")

        active = mgr.get_active_samples()
        assert len(active) == 1

    def test_add_duplicate_pattern_increments_count(self, temp_dir):
        """测试重复模式增加计数"""
        mgr = NegativeSampleManager(storage_dir=temp_dir)

        eid1 = mgr.add_from_feedback(
            "IMG-001", "hash1",
            {"type": "oil_leak", "confidence": 0.9},
            {"type": "water_spill"},
        )
        eid2 = mgr.add_from_feedback(
            "IMG-002", "hash2",
            {"type": "oil_leak", "confidence": 0.85},
            {"type": "water_spill"},
        )

        assert eid1 == eid2  # 同一模式，不新增
        entry = mgr._negative_samples.get(eid1)
        assert entry is not None
        assert entry.feedback_count == 2

    def test_find_similar(self, temp_dir):
        """测试相似查找"""
        mgr = NegativeSampleManager(storage_dir=temp_dir)
        mgr.add_from_feedback(
            "IMG-001", "0xAAA",
            {"type": "oil_leak"}, {"type": "water"},
        )

        # 搜索相同哈希
        similar = mgr.find_similar("0xAAA", max_distance=0)
        assert len(similar) == 1

        # 搜索不同哈希（距离 > 5）
        different = mgr.find_similar("0xBBB", max_distance=2)
        assert len(different) == 0

    def test_cleanup_expired(self, temp_dir):
        """测试过期清理"""
        mgr = NegativeSampleManager(storage_dir=temp_dir)
        mgr.add_from_feedback(
            "IMG-001", "hash1",
            {"type": "oil_leak"}, {"type": "water"},
        )

        # 模拟超过 180 天未出现
        entry = list(mgr._negative_samples.values())[0]
        entry.last_seen = "2020-01-01T00:00:00"

        archived = mgr.cleanup_expired()
        assert archived >= 1

        active = mgr.get_active_samples()
        assert len(active) == 0

    def test_stats(self, temp_dir):
        """测试统计"""
        mgr = NegativeSampleManager(storage_dir=temp_dir)
        mgr.add_from_feedback(
            "IMG-001", "hash1",
            {"type": "oil_leak"}, {"type": "water"},
        )
        stats = mgr.stats()
        assert stats["total_active"] == 1
        assert "oil_leak" in stats["by_false_type"]

    def test_add_batch(self, temp_dir):
        """测试批量添加"""
        mgr = NegativeSampleManager(storage_dir=temp_dir)
        feedbacks = [
            {"image_id": "I1", "image_hash": "H1", "false_prediction": {"type": "A"}, "correct_label": {"type": "X"}},
            {"image_id": "I2", "image_hash": "H2", "false_prediction": {"type": "B"}, "correct_label": {"type": "Y"}},
        ]
        new_count = mgr.add_batch(feedbacks)
        assert new_count == 2


# =========================
# 3. ModelRegistry 测试
# =========================


class TestModelRegistry:
    """模型注册表测试"""

    @pytest.fixture
    def registry(self, temp_dir):
        """创建测试用注册表。"""
        return ModelRegistry(storage_dir=temp_dir)

    def test_register_and_activate(self, registry):
        """测试注册并激活版本"""
        registry.register(
            "v2.0.0",
            metrics={"f1": 0.88, "precision": 0.86, "recall": 0.90},
        )
        assert registry.get_version("v2.0.0") is not None

        result = registry.activate("v2.0.0")
        assert result["status"] == "success"
        assert result["to_version"] == "v2.0.0"

        active = registry.get_active()
        assert active is not None
        assert active.version == "v2.0.0"
        assert active.status == ModelStatus.ACTIVE

    def test_activate_invalid_version(self, registry):
        """测试激活不存在的版本"""
        with pytest.raises(ValueError, match="模型版本不存在"):
            registry.activate("v99.0.0")

    def test_rollback(self, registry):
        """测试回滚"""
        registry.register("v1.0.0", metrics={"f1": 0.80})
        registry.register("v2.0.0", metrics={"f1": 0.85})

        registry.activate("v1.0.0")
        registry.activate("v2.0.0")

        result = registry.rollback()
        assert result["status"] == "success"
        assert result["to_version"] == "v1.0.0"

    def test_rollback_no_history(self, registry):
        """测试无历史时回滚"""
        result = registry.rollback()
        assert result["status"] == "skipped"

    def test_list_versions(self, registry):
        """测试列出版本"""
        registry.register("v1.0.0")
        registry.register("v2.0.0")
        registry.register("v3.0.0")

        all_versions = registry.list_versions()
        assert len(all_versions) == 3

    def test_deployment_history(self, registry):
        """测试部署历史"""
        registry.register("v1.0.0")
        registry.register("v2.0.0")

        registry.activate("v1.0.0")
        registry.activate("v2.0.0")

        history = registry.get_deployment_history()
        assert len(history) == 2
        assert history[0]["to_version"] == "v1.0.0"
        assert history[1]["to_version"] == "v2.0.0"


# =========================
# 4. EvolutionManager 测试
# =========================


class TestEvolutionManager:
    """进化管理器端到端测试"""

    @pytest.fixture
    def mgr(self, temp_dir):
        """创建测试用管理器。"""
        mgr = EvolutionManager.__new__(EvolutionManager)
        mgr.positive = PositiveFeedbackCollector(storage_dir=temp_dir)
        mgr.negative = NegativeSampleManager(storage_dir=temp_dir)
        mgr.registry = ModelRegistry(storage_dir=temp_dir)
        mgr.registry.register("v1.0.0", metrics={"f1": 0.82}, model_name="SafeGuard-Model")
        mgr.registry.activate("v1.0.0")
        return mgr

    def test_record_approval(self, mgr):
        """测试记录赞同"""
        sid = mgr.record_approval(
            user_id="EMP_001",
            input_context={"alert_id": "A1"},
            ai_response={"action": "create_ticket"},
        )
        assert sid.startswith("POS-")
        assert mgr.positive.stats()["total_samples"] == 1

    def test_record_false_positive(self, mgr):
        """测试记录误报→负样本"""
        eid = mgr.record_false_positive(
            image_id="IMG-001",
            image_hash="0x1234",
            false_prediction={"type": "oil_leak", "confidence": 0.91},
            correct_label={"type": "water"},
        )
        assert eid.startswith("NEG-")
        assert mgr.negative.stats()["total_active"] == 1

    def test_check_finetune_readiness_not_ready(self, mgr):
        """测试数据不足时不就绪"""
        readiness = mgr.check_finetune_readiness()
        assert readiness["is_ready"] is False

    def test_check_finetune_readiness_ready(self, mgr):
        """测试数据充足时就绪"""
        # 添加足够正样本
        for i in range(20):
            mgr.record_approval(
                f"EMP_{i:03d}",
                {"id": f"A{i}"}, {"result": f"R{i}"},
            )

        readiness = mgr.check_finetune_readiness()
        assert readiness["is_ready"] is True

    def test_trigger_finetune(self, mgr):
        """测试触发微调"""
        # 添加一些数据
        for i in range(5):
            mgr.record_approval(f"EMP_{i:03d}", {"id": f"A{i}"}, {"result": f"R{i}"})

        result = mgr.trigger_finetune(new_version="v2.0.0")
        assert result["status"] == "success"
        assert result["to_version"] == "v2.0.0"
        assert "new_metrics" in result

    def test_evolution_report(self, mgr):
        """测试综合报告"""
        mgr.record_approval("EMP_001", {}, {})
        mgr.record_false_positive("IMG-001", "hash", {"type": "A"}, {"type": "X"})

        report = mgr.get_evolution_report()
        assert isinstance(report, EvolutionReport)
        assert report.positive_samples["total_samples"] == 1
        assert report.negative_samples["total_active"] == 1
        assert len(report.recommendations) >= 1


# =========================
# 5. 数据模型测试
# =========================


class TestModels:
    """数据模型测试"""

    def test_positive_sample(self):
        s = PositiveSample(
            sample_id="POS-001",
            feedback_type="adopted",
            user_id="EMP_001",
        )
        assert s.sample_id == "POS-001"
        assert s.usage_count == 0

    def test_negative_sample_entry(self):
        e = NegativeSampleEntry(
            entry_id="NEG-001",
            image_id="IMG-001",
            image_hash="0xABCD",
        )
        assert e.entry_id == "NEG-001"
        assert e.status == "active"

    def test_model_version(self):
        v = ModelVersion(
            version="v2.0.0",
            model_name="TestModel",
            metrics={"f1": 0.9},
        )
        assert v.version == "v2.0.0"
        assert v.status == ModelStatus.STANDBY

    def test_evolution_report(self):
        r = EvolutionReport(
            positive_samples={"total": 10},
            negative_samples={"total": 5},
            is_ready_for_finetune=True,
        )
        assert r.is_ready_for_finetune is True
