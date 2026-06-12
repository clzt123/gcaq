"""
数字巡检调度器

基于 APScheduler 实现 7×24 自动化定时巡检：
    1. 按配置的 cron 表达式定时触发巡检
    2. 对每个监控点位：拍照 → 图像哈希 → 与基线对比 → 变化分类 → 告警
    3. 变化超过阈值时触发隐患研判工作流

支持两种运行模式:
    - 真实模式: APScheduler 后台调度 + 真实摄像头/文件
    - Mock 模式: 模拟巡检任务 + 预设告警场景（开发/测试用）

使用方式:
    scheduler = PatrolScheduler()
    scheduler.add_camera("CAM_01", baseline_path, area_type="warehouse")
    await scheduler.run_once()  # 手动执行一次巡检
    scheduler.start_schedule(cron="*/30 * * * *")  # 每30分钟自动巡检
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.core.patrol.image_differ import ImageDiffer, ImageHasher, HashMethod
from app.core.patrol.state_monitor import (
    StateChangeDetector,
    PatrolAlert,
    ChangeType,
    generate_mock_patrol_alerts,
)

logger = logging.getLogger(__name__)

# 默认巡检间隔（cron 表达式）
DEFAULT_PATROL_CRON = "*/30 * * * *"  # 每 30 分钟

# APScheduler 作业 ID
JOB_ID_PATROL = "safeguard_patrol"


@dataclass
class CameraConfig:
    """监控点位配置"""
    camera_id: str
    baseline_path: Path
    area_type: str = ""
    position: str = ""
    current_frame_dir: Optional[Path] = None


class PatrolScheduler:
    """
    数字巡检调度器。

    管理巡检计划、监控点位注册、巡检执行和告警生成。

    使用方式:
        # Mock 模式
        scheduler = PatrolScheduler(mock_mode=True)
        alerts = await scheduler.run_once()

        # 真实模式
        scheduler = PatrolScheduler(mock_mode=False)
        scheduler.add_camera("CAM_01", Path("baseline.jpg"), area_type="production")
        await scheduler.start_schedule()  # 启动定时巡检
    """

    def __init__(
        self,
        mock_mode: bool = True,
        diff_threshold: int = 12,
        high_diff_threshold: int = 20,
    ):
        """
        初始化调度器。

        Args:
            mock_mode: True=使用 Mock 巡检数据，False=真实摄像头/文件
            diff_threshold: 图像差异检测阈值
            high_diff_threshold: 显著差异阈值
        """
        self.mock_mode = mock_mode
        self._cameras: Dict[str, CameraConfig] = {}
        self._differ = ImageDiffer(
            hasher=ImageHasher(method=HashMethod.DHASH),
            diff_threshold=diff_threshold,
            high_diff_threshold=high_diff_threshold,
        )
        self._detector = StateChangeDetector()
        self._scheduler = None  # APScheduler 实例（懒加载）
        self._on_alert_callbacks: List[Callable] = []

        # 巡检统计
        self._last_patrol_time: Optional[datetime] = None
        self._total_patrols: int = 0
        self._total_alerts: int = 0

        logger.info(
            f"[PatrolScheduler] 初始化: mock_mode={mock_mode}, "
            f"thresholds=({diff_threshold}, {high_diff_threshold})"
        )

    # ---- 监控点位管理 ----

    def add_camera(
        self,
        camera_id: str,
        baseline_path: Path,
        area_type: str = "",
        position: str = "",
        current_frame_dir: Optional[Path] = None,
    ):
        """
        注册监控点位。

        Args:
            camera_id: 唯一相机标识
            baseline_path: 基线图像路径
            area_type: 区域类型 (production/rest/hazard/warehouse/corridor/exit)
            position: 相机安装位置描述
            current_frame_dir: 当前帧目录（None 时使用 baseline_path 同目录）
        """
        config = CameraConfig(
            camera_id=camera_id,
            baseline_path=baseline_path,
            area_type=area_type,
            position=position,
            current_frame_dir=current_frame_dir,
        )

        self._cameras[camera_id] = config
        self._differ.set_baseline(camera_id, baseline_path)

        logger.info(
            f"[PatrolScheduler] 注册相机: {camera_id}, "
            f"area={area_type}, position={position}"
        )

    def remove_camera(self, camera_id: str):
        """移除监控点位。"""
        self._cameras.pop(camera_id, None)
        self._differ._baselines.pop(camera_id, None)
        logger.info(f"[PatrolScheduler] 移除相机: {camera_id}")

    def on_alert(self, callback: Callable):
        """注册告警回调（接收 PatrolAlert 对象）。"""
        self._on_alert_callbacks.append(callback)

    # ---- 巡检执行 ----

    async def run_once(self) -> List[PatrolAlert]:
        """
        执行一次完整巡检。

        Mock 模式: 返回预设巡检告警场景
        真实模式: 逐相机拍照→哈希→对比→分类

        Returns:
            巡检告警列表
        """
        if self.mock_mode:
            return await self._run_mock_patrol()

        return await self._run_real_patrol()

    async def _run_mock_patrol(self) -> List[PatrolAlert]:
        """Mock 巡检：返回预设场景。"""
        logger.info("[PatrolScheduler] Mock 巡检开始...")

        mock_data = generate_mock_patrol_alerts()
        alerts: List[PatrolAlert] = []

        for data in mock_data:
            alert = PatrolAlert(
                alert_id=data["alert_id"],
                camera_id=data["camera_id"],
                change_type=data["change_type"],
                severity=data["severity"],
                description=data["description"],
                diff_distance=data["diff_distance"],
                similarity=round(1.0 - data["diff_distance"] / 64.0, 4),
                suggested_action=self._detector._suggest_action(
                    data["change_type"], data.get("area_type", "")
                ),
            )
            alerts.append(alert)
            self._total_alerts += 1

            # 触发告警回调
            for callback in self._on_alert_callbacks:
                try:
                    callback(alert)
                except Exception as e:
                    logger.error(f"[PatrolScheduler] 告警回调失败: {e}")

        self._total_patrols += 1
        self._last_patrol_time = datetime.now()

        logger.info(
            f"[PatrolScheduler] Mock 巡检完成: "
            f"{len(alerts)} 个告警 / {len(mock_data)} 个点位"
        )

        return alerts

    async def _run_real_patrol(self) -> List[PatrolAlert]:
        """真实巡检：逐相机检测。"""
        logger.info(
            f"[PatrolScheduler] 真实巡检开始: {len(self._cameras)} 个点位"
        )

        alerts: List[PatrolAlert] = []

        for camera_id, config in self._cameras.items():
            try:
                # 获取当前帧路径
                current_path = self._get_current_frame(config)

                # 图像差异检测
                diff_result = self._differ.compare(camera_id, current_path)

                if diff_result["has_changed"]:
                    # 状态变化分类
                    alert = self._detector.classify(
                        camera_id=camera_id,
                        diff_result=diff_result,
                        area_type=config.area_type,
                        camera_position=config.position,
                    )

                    if alert.severity != "none":
                        alerts.append(alert)
                        self._total_alerts += 1

                        # 触发告警回调
                        for callback in self._on_alert_callbacks:
                            try:
                                callback(alert)
                            except Exception as e:
                                logger.error(
                                    f"[PatrolScheduler] 告警回调失败: {e}"
                                )

            except Exception as e:
                logger.error(
                    f"[PatrolScheduler] 相机 {camera_id} 巡检失败: {e}",
                    exc_info=True,
                )

        self._total_patrols += 1
        self._last_patrol_time = datetime.now()

        logger.info(
            f"[PatrolScheduler] 真实巡检完成: "
            f"{len(alerts)} 个告警 / {len(self._cameras)} 个点位"
        )

        return alerts

    def _get_current_frame(self, config: CameraConfig) -> Path:
        """
        获取当前帧路径。

        优先使用 current_frame_dir 下的同名文件，
        其次使用 baseline_path 同目录下的 *_current.* 文件，
        最后直接使用 baseline_path 本身（Mock 降级）。

        Args:
            config: 相机配置

        Returns:
            当前帧路径
        """
        # 指定目录下的同名文件
        if config.current_frame_dir and config.current_frame_dir.exists():
            candidate = config.current_frame_dir / config.baseline_path.name
            if candidate.exists():
                return candidate

        # 同目录下的 *_current 文件
        parent = config.baseline_path.parent
        stem = config.baseline_path.stem
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            candidate = parent / f"{stem}_current{ext}"
            if candidate.exists():
                return candidate

        # 降级：使用基线本身（即无变化场景）
        logger.debug(
            f"[PatrolScheduler] 未找到当前帧，使用基线: "
            f"{config.baseline_path}"
        )
        return config.baseline_path

    # ---- 定时调度 ----

    async def start_schedule(self, cron: str = DEFAULT_PATROL_CRON):
        """
        启动定时巡检调度。

        Args:
            cron: Cron 表达式 (默认每30分钟)
        """
        if not self._scheduler:
            try:
                from apscheduler.schedulers.asyncio import AsyncIOScheduler
                self._scheduler = AsyncIOScheduler()
            except ImportError:
                logger.error(
                    "[PatrolScheduler] APScheduler 不可用，"
                    "无法启动定时巡检。请安装: pip install apscheduler"
                )
                return

        # 移除已有作业
        if self._scheduler.get_job(JOB_ID_PATROL):
            self._scheduler.remove_job(JOB_ID_PATROL)

        # 添加巡检作业
        self._scheduler.add_job(
            self.run_once,
            trigger="cron",
            **self._parse_cron(cron),
            id=JOB_ID_PATROL,
            name="SafeGuard-AI 数字巡检",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info(
            f"[PatrolScheduler] 定时巡检已启动: cron='{cron}', "
            f"job_id={JOB_ID_PATROL}"
        )

    def stop_schedule(self):
        """停止定时巡检调度。"""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("[PatrolScheduler] 定时巡检已停止")

    @staticmethod
    def _parse_cron(cron: str) -> Dict[str, str]:
        """
        解析 cron 表达式为 APScheduler 参数。

        支持:
            - 5 字段: minute hour day month day_of_week
            - */N: 每N分钟/小时

        Args:
            cron: 标准 5 字段 cron 表达式

        Returns:
            APScheduler cron trigger 参数字典
        """
        parts = cron.strip().split()
        if len(parts) != 5:
            raise ValueError(
                f"Cron 表达式需为 5 字段格式，当前: {len(parts)} 字段"
            )

        return {
            "minute": parts[0],
            "hour": parts[1],
            "day": parts[2],
            "month": parts[3],
            "day_of_week": parts[4],
        }

    # ---- 巡检统计 ----

    def get_stats(self) -> Dict[str, Any]:
        """获取巡检统计信息。"""
        return {
            "mode": "mock" if self.mock_mode else "real",
            "total_patrols": self._total_patrols,
            "total_alerts": self._total_alerts,
            "cameras_registered": len(self._cameras),
            "last_patrol_time": (
                self._last_patrol_time.isoformat()
                if self._last_patrol_time else None
            ),
            "scheduler_running": (
                self._scheduler.running
                if self._scheduler else False
            ),
        }
