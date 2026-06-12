"""
通用工具类

提供项目级别的工具函数（路径解析、日志、数据处理、文件操作等）。
"""
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# =========================
# 项目根路径解析
# =========================

_project_root: Optional[Path] = None


def get_project_root() -> Path:
    """
    获取项目根目录（含 CLAUDE.md 或 .env 的目录），全局缓存。

    从当前文件向上查找，优先匹配 CLAUDE.md，其次 .env。
    首次调用后结果缓存，后续零开销。

    Returns:
        项目根目录路径

    Raises:
        FileNotFoundError: 无法定位项目根目录
    """
    global _project_root
    if _project_root is not None:
        return _project_root

    current = Path(__file__).resolve().parent.parent  # app/utils → app → root
    for marker in ("CLAUDE.md", ".env"):
        if (current / marker).exists():
            _project_root = current
            return _project_root

    # 兜底：向上逐级查找
    for parent in current.parents:
        if (parent / "CLAUDE.md").exists() or (parent / ".env").exists():
            _project_root = parent
            return _project_root

    raise FileNotFoundError(
        "无法定位项目根目录，请确保 CLAUDE.md 或 .env 文件存在。"
    )


def get_mock_path(filename: str) -> Path:
    """
    获取 mock_data 目录下的文件完整路径。

    Args:
        filename: mock_data 目录下的文件名（如 "mock_alerts.json"）

    Returns:
        完整文件路径

    Raises:
        FileNotFoundError: 项目根目录无法定位时抛出
    """
    return get_project_root() / "mock_data" / filename
