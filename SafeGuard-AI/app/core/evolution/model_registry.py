"""
模型注册表与热加载

实现技术方案功能 11 — 模型权重热加载/重启机制。

功能:
    1. 模型版本注册: 记录所有已训练/部署的模型版本
    2. 热加载接口: 暴露模型切换 API（不中断服务）
    3. 回滚机制: 支持快速回滚到上一个稳定版本
    4. 状态追踪: 记录部署历史、性能指标

设计原则:
    - 当前为 Mock 模式（模拟热加载流程）
    - 生产环境对接: 需集成模型服务（如 vLLM / TGI / KServe）
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ModelStatus(str, Enum):
    """模型状态"""
    ACTIVE = "active"         # 当前生产模型
    STANDBY = "standby"       # 备用模型（热备份）
    DEPRECATED = "deprecated" # 已弃用
    ARCHIVED = "archived"     # 已归档
    TRAINING = "training"     # 训练中


@dataclass
class ModelVersion:
    """
    模型版本记录。

    Attributes:
        version: 版本号 (e.g., 'v1.2.0')
        model_name: 模型名称
        model_path: 模型文件路径
        status: 当前状态
        deployed_at: 部署时间
        metrics: 性能指标 {f1, precision, recall, latency_ms}
        training_data_size: 训练数据量
        parent_version: 训练来源版本
        changelog: 变更说明
    """

    version: str
    model_name: str = ""
    model_path: str = ""
    status: ModelStatus = ModelStatus.STANDBY
    deployed_at: str = ""
    metrics: Dict[str, float] = field(default_factory=dict)
    training_data_size: int = 0
    parent_version: str = ""
    changelog: str = ""


class ModelRegistry:
    """
    模型注册表。

    管理所有模型版本的生命周期：
        训练 → 待评估 → 热备 → 激活 → 归档

    使用方式:
        registry = ModelRegistry()
        registry.register("v2.0.0", metrics={"f1": 0.87, "precision": 0.85})
        result = registry.activate("v2.0.0")  # 热切换
        registry.rollback()                    # 回滚
    """

    def __init__(self, storage_dir: Optional[str] = None):
        """
        初始化模型注册表。

        Args:
            storage_dir: 存储目录
        """
        if storage_dir:
            self._storage_dir = Path(storage_dir)
        else:
            self._storage_dir = (
                Path(__file__).resolve().parent.parent.parent.parent / "data"
            )
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._registry_file = self._storage_dir / "model_registry.json"

        self._versions: Dict[str, ModelVersion] = {}
        self._active_version: Optional[str] = None
        self._deployment_history: List[Dict[str, Any]] = []
        self._load()

    # ---- 版本管理 ----

    def register(
        self,
        version: str,
        model_name: str = "",
        model_path: str = "",
        metrics: Optional[Dict[str, float]] = None,
        training_data_size: int = 0,
        parent_version: str = "",
        changelog: str = "",
    ) -> ModelVersion:
        """
        注册新模型版本。

        Args:
            version: 版本号
            model_name: 模型名称
            model_path: 模型路径
            metrics: 性能指标
            training_data_size: 训练数据量
            parent_version: 父版本
            changelog: 变更说明

        Returns:
            ModelVersion 实例
        """
        if version in self._versions:
            logger.warning(f"[ModelRegistry] 版本 {version} 已存在，将覆盖")

        mv = ModelVersion(
            version=version,
            model_name=model_name or "SafeGuard-Model",
            model_path=model_path,
            status=ModelStatus.STANDBY,
            metrics=metrics or {},
            training_data_size=training_data_size,
            parent_version=parent_version,
            changelog=changelog,
        )

        self._versions[version] = mv
        self._save()

        logger.info(
            f"[ModelRegistry] 注册版本: {version} | "
            f"metrics={mv.metrics} | data_size={training_data_size}"
        )
        return mv

    def activate(self, version: str) -> Dict[str, Any]:
        """
        激活（热加载）指定版本模型。

        流程:
            1. 验证版本存在且可用
            2. 将当前活跃版本降级为 STANDBY
            3. 将目标版本升级为 ACTIVE
            4. 记录部署历史

        Args:
            version: 目标版本号

        Returns:
            切换结果

        Raises:
            ValueError: 版本不存在或不可激活
        """
        if version not in self._versions:
            raise ValueError(f"模型版本不存在: {version}")

        target = self._versions[version]
        if target.status == ModelStatus.ARCHIVED:
            raise ValueError(f"模型版本已归档，不可激活: {version}")
        if target.status == ModelStatus.TRAINING:
            raise ValueError(f"模型正在训练中，不可激活: {version}")

        # 保存旧活跃版本
        old_version = self._active_version
        if old_version and old_version in self._versions:
            old_mv = self._versions[old_version]
            old_mv.status = ModelStatus.STANDBY
            logger.info(f"[ModelRegistry] 降级旧版本: {old_version} → STANDBY")

        # 激活新版本
        target.status = ModelStatus.ACTIVE
        target.deployed_at = datetime.now().isoformat()
        self._active_version = version

        # 记录部署历史
        deployment = {
            "timestamp": datetime.now().isoformat(),
            "from_version": old_version,
            "to_version": version,
            "reason": "manual_activation",
            "metrics_before": self._versions[old_version].metrics if old_version and old_version in self._versions else {},
            "metrics_after": target.metrics,
        }
        self._deployment_history.append(deployment)
        self._save()

        logger.info(
            f"[ModelRegistry] 🔄 热加载完成: {old_version or 'none'} → {version} "
            f"(f1={target.metrics.get('f1', 'N/A')})"
        )

        return {
            "status": "success",
            "from_version": old_version,
            "to_version": version,
            "deployed_at": target.deployed_at,
            "message": f"模型已热加载至 {version}",
        }

    def rollback(self) -> Dict[str, Any]:
        """
        回滚到上一个稳定版本。

        从部署历史中找到最近的上一个版本并激活。

        Returns:
            回滚结果
        """
        if len(self._deployment_history) < 1:
            return {"status": "skipped", "message": "无部署历史，无法回滚"}

        # 找到上一个版本
        last_deployment = self._deployment_history[-1]
        previous_version = last_deployment.get("from_version", "")

        if not previous_version or previous_version not in self._versions:
            return {"status": "skipped", "message": "上一个版本不可用"}

        return self.activate(previous_version)

    # ---- 查询 ----

    def get_active(self) -> Optional[ModelVersion]:
        """获取当前活跃模型。"""
        if self._active_version and self._active_version in self._versions:
            return self._versions[self._active_version]
        return None

    def get_version(self, version: str) -> Optional[ModelVersion]:
        """获取指定版本。"""
        return self._versions.get(version)

    def list_versions(
        self,
        status: Optional[ModelStatus] = None,
    ) -> List[ModelVersion]:
        """
        列出模型版本。

        Args:
            status: 按状态过滤（None=全部）

        Returns:
            ModelVersion 列表（按版本号降序）
        """
        versions = list(self._versions.values())
        if status:
            versions = [v for v in versions if v.status == status]
        return sorted(versions, key=lambda v: v.version, reverse=True)

    def get_deployment_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取部署历史。"""
        return self._deployment_history[-limit:]

    # ---- 持久化 ----

    def _save(self):
        """持久化注册表。"""
        try:
            data = {
                "versions": {},
                "active_version": self._active_version,
                "deployment_history": self._deployment_history,
            }

            for ver, mv in self._versions.items():
                data["versions"][ver] = {
                    "version": mv.version,
                    "model_name": mv.model_name,
                    "model_path": mv.model_path,
                    "status": mv.status.value,
                    "deployed_at": mv.deployed_at,
                    "metrics": mv.metrics,
                    "training_data_size": mv.training_data_size,
                    "parent_version": mv.parent_version,
                    "changelog": mv.changelog,
                }

            with open(self._registry_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[ModelRegistry] 持久化失败: {e}")

    def _load(self):
        """从 JSON 恢复。"""
        if self._registry_file.exists():
            try:
                with open(self._registry_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                for ver, d in data.get("versions", {}).items():
                    self._versions[ver] = ModelVersion(
                        version=d["version"],
                        model_name=d.get("model_name", ""),
                        model_path=d.get("model_path", ""),
                        status=ModelStatus(d.get("status", "standby")),
                        deployed_at=d.get("deployed_at", ""),
                        metrics=d.get("metrics", {}),
                        training_data_size=d.get("training_data_size", 0),
                        parent_version=d.get("parent_version", ""),
                        changelog=d.get("changelog", ""),
                    )

                self._active_version = data.get("active_version")
                self._deployment_history = data.get("deployment_history", [])

                active = self.get_active()
                logger.info(
                    f"[ModelRegistry] 恢复: {len(self._versions)} 个版本, "
                    f"活跃: {active.version if active else 'none'}"
                )
            except Exception as e:
                logger.warning(f"[ModelRegistry] 恢复失败: {e}")
