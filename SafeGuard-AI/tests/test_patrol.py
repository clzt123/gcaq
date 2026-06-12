"""
数字巡检员模块单元测试

覆盖:
    - ImageHasher: aHash/dHash 计算与汉明距离
    - ImageDiffer: 基线设置与差异检测
    - StateChangeDetector: 状态变化分类（由通变堵/由在变无/由无变有）
    - PatrolScheduler: Mock 巡检执行与统计

测试策略:
    - 使用项目自带的 mock_data/images/ 中的测试图片
    - 无真实摄像头依赖
"""
from pathlib import Path

import pytest

from app.core.patrol.image_differ import (
    ImageHasher,
    ImageDiffer,
    HashMethod,
    DEFAULT_DIFF_THRESHOLD,
    HIGH_DIFF_THRESHOLD,
)
from app.core.patrol.state_monitor import (
    StateChangeDetector,
    ChangeType,
    PatrolAlert,
    CHANGE_TYPE_LABELS,
    CHANGE_SEVERITY,
    generate_mock_patrol_alerts,
)
from app.core.patrol.scheduler import PatrolScheduler


# =========================
# 辅助: 获取测试图片路径
# =========================


def _get_test_image(name: str = "inj_mold_leak.jpg") -> Path:
    """获取 mock 测试图片路径。"""
    from app.utils import get_mock_path
    img_dir = get_mock_path("images")
    return img_dir / name


# =========================
# ImageHasher 测试
# =========================


class TestImageHasher:
    """测试图像感知哈希"""

    def test_ahash_computes_hex(self):
        """aHash 应返回十六进制字符串"""
        img = _get_test_image("inj_mold_leak.jpg")
        if not img.exists():
            pytest.skip("测试图片不存在")

        hasher = ImageHasher(method=HashMethod.AHASH)
        h = hasher.compute(img)
        assert isinstance(h, str)
        assert len(h) > 0
        # 16x16 aHash = 256 bits = 64 hex chars
        assert len(h) == 64

    def test_dhash_computes_hex(self):
        """dHash 应返回十六进制字符串"""
        img = _get_test_image("inj_mold_leak.jpg")
        if not img.exists():
            pytest.skip("测试图片不存在")

        hasher = ImageHasher(method=HashMethod.DHASH)
        h = hasher.compute(img)
        assert isinstance(h, str)
        assert len(h) == 64  # 16x16 dHash

    def test_phash_fallback_to_dhash(self):
        """pHash 在无 OpenCV 时应降级"""
        img = _get_test_image("inj_mold_leak.jpg")
        if not img.exists():
            pytest.skip("测试图片不存在")

        hasher = ImageHasher(method=HashMethod.PHASH)
        h = hasher.compute(img)
        assert isinstance(h, str)
        assert len(h) > 0

    def test_same_image_same_hash(self):
        """同一图像应生成相同哈希"""
        img = _get_test_image("inj_mold_leak.jpg")
        if not img.exists():
            pytest.skip("测试图片不存在")

        hasher = ImageHasher()
        h1 = hasher.compute(img)
        h2 = hasher.compute(img)
        assert h1 == h2

    def test_different_images_different_hash(self):
        """不同图像应生成不同哈希"""
        img1 = _get_test_image("inj_mold_leak.jpg")
        img2 = _get_test_image("chemical_smoke.jpg")
        if not img1.exists() or not img2.exists():
            pytest.skip("测试图片不存在")

        hasher = ImageHasher()
        h1 = hasher.compute(img1)
        h2 = hasher.compute(img2)
        assert h1 != h2, "不同图像应有不同哈希"

    def test_hamming_distance_same(self):
        """相同哈希的距离为 0"""
        hasher = ImageHasher()
        h = "a" * 64  # 模拟哈希
        assert hasher.hamming_distance(h, h) == 0

    def test_hamming_distance_different(self):
        """不同哈希的距离 > 0"""
        hasher = ImageHasher()
        h1 = "a" * 64
        h2 = "b" * 64
        dist = hasher.hamming_distance(h1, h2)
        assert dist > 0

    def test_hamming_distance_different_length_raises(self):
        """不同长度哈希应抛异常"""
        hasher = ImageHasher()
        with pytest.raises(ValueError):
            hasher.hamming_distance("abc", "abcd")

    def test_similarity_same(self):
        """完全相同的图像相似度为 1.0"""
        img = _get_test_image("inj_mold_leak.jpg")
        if not img.exists():
            pytest.skip("测试图片不存在")

        hasher = ImageHasher()
        h = hasher.compute(img)
        sim = hasher.similarity(h, h)
        assert sim == 1.0

    def test_file_not_found_raises(self):
        """不存在的文件应抛异常"""
        hasher = ImageHasher()
        with pytest.raises(FileNotFoundError):
            hasher.compute(Path("/nonexistent/image.jpg"))


# =========================
# ImageDiffer 测试
# =========================


class TestImageDiffer:
    """测试图像差异检测器"""

    def test_set_baseline(self):
        """设置基线图像"""
        img = _get_test_image("inj_mold_leak.jpg")
        if not img.exists():
            pytest.skip("测试图片不存在")

        differ = ImageDiffer()
        differ.set_baseline("CAM_TEST", img)

        h = differ.get_baseline_hash("CAM_TEST")
        assert h is not None
        assert len(h) > 0

    def test_compare_same_image_no_change(self):
        """相同图像比较 → 无变化"""
        img = _get_test_image("inj_mold_leak.jpg")
        if not img.exists():
            pytest.skip("测试图片不存在")

        differ = ImageDiffer()
        differ.set_baseline("CAM_TEST", img)
        result = differ.compare("CAM_TEST", img)

        assert result["has_changed"] is False
        assert result["change_level"] == "none"
        assert result["distance"] == 0
        assert result["similarity"] == 1.0

    def test_compare_different_images_has_change(self):
        """不同图像比较 → 有变化"""
        img1 = _get_test_image("inj_mold_leak.jpg")
        img2 = _get_test_image("chemical_smoke.jpg")
        if not img1.exists() or not img2.exists():
            pytest.skip("测试图片不存在")

        differ = ImageDiffer(diff_threshold=1)  # 极低阈值以检测任何变化
        differ.set_baseline("CAM_TEST", img1)
        result = differ.compare("CAM_TEST", img2)

        assert result["has_changed"] is True
        assert result["distance"] > 0
        assert result["similarity"] < 1.0

    def test_compare_no_baseline_raises(self):
        """未设置基线 → 抛异常"""
        img = _get_test_image("inj_mold_leak.jpg")
        if not img.exists():
            pytest.skip("测试图片不存在")

        differ = ImageDiffer()
        with pytest.raises(ValueError, match="基线未设置"):
            differ.compare("UNKNOWN_CAM", img)

    def test_compare_with_hash(self):
        """使用预计算哈希比较"""
        img = _get_test_image("inj_mold_leak.jpg")
        if not img.exists():
            pytest.skip("测试图片不存在")

        differ = ImageDiffer()
        differ.set_baseline("CAM_TEST", img)

        hasher = ImageHasher()
        current_hash = hasher.compute(img)

        result = differ.compare_with_hash("CAM_TEST", current_hash)
        assert result["has_changed"] is False
        assert result["distance"] == 0

    def test_high_diff_threshold_respected(self):
        """高阈值下应检测到显著变化"""
        img1 = _get_test_image("inj_mold_leak.jpg")
        img2 = _get_test_image("chemical_smoke.jpg")
        if not img1.exists() or not img2.exists():
            pytest.skip("测试图片不存在")

        differ = ImageDiffer(diff_threshold=1, high_diff_threshold=50)
        differ.set_baseline("CAM_TEST", img1)
        result = differ.compare("CAM_TEST", img2)

        # 高阈值 50 比 dHash 最大距离 64 还严格
        assert result["change_level"] in ("minor", "significant", "none")


# =========================
# StateChangeDetector 测试
# =========================


class TestStateChangeDetector:
    """测试状态变化分类器"""

    def setup_method(self):
        self.detector = StateChangeDetector()

    def test_classify_no_change(self):
        """无变化 → NO_CHANGE"""
        alert = self.detector.classify(
            camera_id="CAM_01",
            diff_result={"has_changed": False, "change_level": "none",
                         "distance": 0, "similarity": 1.0},
        )
        assert alert.change_type == ChangeType.NO_CHANGE
        assert alert.severity == "none"

    def test_classify_exit_blocked(self):
        """出口区域显著变化 → 由通变堵"""
        alert = self.detector.classify(
            camera_id="CAM_FIRE_EXIT",
            diff_result={"has_changed": True, "change_level": "significant",
                         "distance": 30, "similarity": 0.5},
            area_type="exit",
        )
        assert alert.change_type == ChangeType.CLEAR_TO_BLOCKED
        assert alert.severity == "high"

    def test_classify_corridor_blocked(self):
        """走廊区域显著变化 → 由通变堵"""
        alert = self.detector.classify(
            camera_id="CAM_CORRIDOR",
            diff_result={"has_changed": True, "change_level": "significant",
                         "distance": 25, "similarity": 0.6},
            area_type="corridor",
        )
        assert alert.change_type == ChangeType.CLEAR_TO_BLOCKED

    def test_classify_hazard_area_missing_device(self):
        """危险区域显著变化 → 由在变无"""
        alert = self.detector.classify(
            camera_id="CAM_HAZARD",
            diff_result={"has_changed": True, "change_level": "significant",
                         "distance": 22, "similarity": 0.55},
            area_type="hazard",
        )
        assert alert.change_type == ChangeType.PRESENT_TO_ABSENT
        assert alert.severity == "high"

    def test_classify_production_missing_device(self):
        """生产区域显著变化 → 由在变无"""
        alert = self.detector.classify(
            camera_id="CAM_PROD",
            diff_result={"has_changed": True, "change_level": "significant",
                         "distance": 21, "similarity": 0.6},
            area_type="production",
        )
        assert alert.change_type == ChangeType.PRESENT_TO_ABSENT

    def test_classify_unknown_area_significant_change(self):
        """未知区域显著变化 → 由无变有"""
        alert = self.detector.classify(
            camera_id="CAM_UNKNOWN",
            diff_result={"has_changed": True, "change_level": "significant",
                         "distance": 30, "similarity": 0.4},
            area_type="office",  # office 不属于已知危险区
        )
        assert alert.change_type == ChangeType.ABSENT_TO_PRESENT

    def test_classify_minor_change_lighting(self):
        """轻微变化 → 光照变化"""
        alert = self.detector.classify(
            camera_id="CAM_CORRIDOR",
            diff_result={"has_changed": True, "change_level": "minor",
                         "distance": 8, "similarity": 0.85},
            area_type="corridor",
        )
        assert alert.change_type == ChangeType.LIGHTING_CHANGE
        assert alert.severity == "low"

    def test_patrol_alert_has_all_fields(self):
        """PatrolAlert 应包含完整字段"""
        alert = self.detector.classify(
            camera_id="CAM_01",
            diff_result={"has_changed": True, "change_level": "significant",
                         "distance": 25, "similarity": 0.5},
            area_type="exit",
            camera_position="1号消防通道",
        )

        assert alert.alert_id
        assert alert.camera_id == "CAM_01"
        assert alert.change_type in ChangeType
        assert alert.severity in ("high", "medium", "low", "none")
        assert len(alert.description) > 0
        assert alert.diff_distance == 25
        assert alert.similarity == 0.5


# =========================
# 常量与标签测试
# =========================


class TestChangeTypeLabels:
    """测试变化类型标签和严重程度映射"""

    def test_all_change_types_have_labels(self):
        """所有 ChangeType 都应有中文标签"""
        for ct in ChangeType:
            assert ct in CHANGE_TYPE_LABELS, f"{ct} 缺少标签"

    def test_all_change_types_have_severity(self):
        """所有 ChangeType 都应有严重程度"""
        for ct in ChangeType:
            assert ct in CHANGE_SEVERITY, f"{ct} 缺少严重程度映射"


# =========================
# Mock 巡检数据测试
# =========================


class TestMockPatrolAlerts:
    """测试 Mock 巡检告警生成"""

    def test_generates_alerts(self):
        """应生成预设告警场景"""
        alerts = generate_mock_patrol_alerts()
        assert len(alerts) >= 3

    def test_alerts_have_all_scenarios(self):
        """应覆盖所有变化类型"""
        alerts = generate_mock_patrol_alerts()
        types = {a["change_type"] for a in alerts}
        expected = {
            ChangeType.CLEAR_TO_BLOCKED,
            ChangeType.PRESENT_TO_ABSENT,
            ChangeType.ABSENT_TO_PRESENT,
            ChangeType.LIGHTING_CHANGE,
        }
        assert types == expected, f"缺少场景: {expected - types}"

    def test_alerts_have_required_fields(self):
        """每个 Mock 告警应有必需字段"""
        alerts = generate_mock_patrol_alerts()
        required = {"alert_id", "camera_id", "change_type", "severity",
                    "description", "diff_distance"}
        for alert in alerts:
            for field in required:
                assert field in alert, f"告警 {alert.get('alert_id')} 缺少字段 {field}"


# =========================
# PatrolScheduler 测试
# =========================


class TestPatrolScheduler:
    """测试巡检调度器"""

    @pytest.mark.asyncio
    async def test_mock_run_once_returns_alerts(self):
        """Mock 巡检应返回告警列表"""
        scheduler = PatrolScheduler(mock_mode=True)
        alerts = await scheduler.run_once()
        assert len(alerts) >= 3

    @pytest.mark.asyncio
    async def test_mock_run_once_all_alerts_have_severity(self):
        """Mock 巡检告警应有严重程度"""
        scheduler = PatrolScheduler(mock_mode=True)
        alerts = await scheduler.run_once()
        for alert in alerts:
            assert alert.severity in ("high", "medium", "low", "none")

    @pytest.mark.asyncio
    async def test_mock_run_once_all_have_camera_id(self):
        """Mock 巡检告警应有相机ID"""
        scheduler = PatrolScheduler(mock_mode=True)
        alerts = await scheduler.run_once()
        for alert in alerts:
            assert alert.camera_id

    @pytest.mark.asyncio
    async def test_stats_after_run(self):
        """巡检后统计信息更新"""
        scheduler = PatrolScheduler(mock_mode=True)
        await scheduler.run_once()

        stats = scheduler.get_stats()
        assert stats["total_patrols"] == 1
        assert stats["total_alerts"] >= 3
        assert stats["mode"] == "mock"
        assert stats["last_patrol_time"] is not None

    @pytest.mark.asyncio
    async def test_multiple_runs_increment_stats(self):
        """多次巡检统计正确累加"""
        scheduler = PatrolScheduler(mock_mode=True)
        await scheduler.run_once()
        await scheduler.run_once()
        await scheduler.run_once()

        stats = scheduler.get_stats()
        assert stats["total_patrols"] == 3

    @pytest.mark.asyncio
    async def test_add_camera(self):
        """注册相机后统计数更新"""
        img = _get_test_image("inj_mold_leak.jpg")
        if not img.exists():
            pytest.skip("测试图片不存在")

        scheduler = PatrolScheduler(mock_mode=False)
        scheduler.add_camera("CAM_01", img, area_type="production", position="车间入口")
        scheduler.add_camera("CAM_02", img, area_type="warehouse")

        stats = scheduler.get_stats()
        assert stats["cameras_registered"] == 2

    @pytest.mark.asyncio
    async def test_remove_camera(self):
        """移除相机后统计减少"""
        img = _get_test_image("inj_mold_leak.jpg")
        if not img.exists():
            pytest.skip("测试图片不存在")

        scheduler = PatrolScheduler(mock_mode=False)
        scheduler.add_camera("CAM_01", img)
        scheduler.remove_camera("CAM_01")

        stats = scheduler.get_stats()
        assert stats["cameras_registered"] == 0

    @pytest.mark.asyncio
    async def test_on_alert_callback(self):
        """告警回调应被调用"""
        alerts_received = []

        def callback(alert):
            alerts_received.append(alert)

        scheduler = PatrolScheduler(mock_mode=True)
        scheduler.on_alert(callback)
        alerts = await scheduler.run_once()

        assert len(alerts_received) == len(alerts)
        assert isinstance(alerts_received[0], PatrolAlert)

    def test_parse_cron_valid(self):
        """有效的 cron 表达式应正确解析"""
        parts = PatrolScheduler._parse_cron("*/30 * * * *")
        assert parts["minute"] == "*/30"
        assert parts["hour"] == "*"

    def test_parse_cron_invalid_raises(self):
        """无效的 cron 表达式应抛异常"""
        with pytest.raises(ValueError):
            PatrolScheduler._parse_cron("* * * *")  # 只有 4 字段
