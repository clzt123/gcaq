"""
SafeGuard-AI FastAPI 应用启动入口。

提供健康检查、API 路由注册、日志系统初始化以及应用生命周期管理。
"""
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings, setup_langsmith

# LangSmith 可观测性：必须在 LangChain/LangGraph 导入之前初始化
# （hazard_router 会传递导入 langgraph，因此 setup_langsmith 必须在此调用）
setup_langsmith()

from app.api.v1.hazard import router as hazard_router
from app.api.v1.meeting import router as meeting_router
from app.api.v1.training import router as training_router

# =========================
# 日志系统初始化
# =========================


def _setup_logging() -> None:
    """
    初始化日志系统。

    配置控制台输出（带颜色）和按天轮转的文件日志。
    日志级别从 Settings.log_level 读取，默认为 INFO。

    设计模式参考: Base/Config/logConfig.py 的 ColoredFormatter + TimedRotatingFileHandler 模式。
    """
    from logging.handlers import TimedRotatingFileHandler
    from pathlib import Path

    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    if root_logger.handlers:
        return  # 避免重复配置

    root_logger.setLevel(log_level)

    # 日志格式
    log_format_str = "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
    date_format_str = "%Y-%m-%d %H:%M:%S"

    # --- 控制台处理器 ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    class _ColoredFormatter(logging.Formatter):
        """带 ANSI 颜色的日志格式化器"""

        COLORS = {
            "DEBUG": "\033[36m",
            "INFO": "\033[32m",
            "WARNING": "\033[33m",
            "ERROR": "\033[31m",
            "CRITICAL": "\033[35m",
        }
        RESET = "\033[0m"

        def format(self, record: logging.LogRecord) -> str:
            msg = super().format(record)
            color = self.COLORS.get(record.levelname, "")
            return f"{color}{msg}{self.RESET}" if color else msg

    console_handler.setFormatter(_ColoredFormatter(log_format_str, date_format_str))
    root_logger.addHandler(console_handler)

    # --- 文件处理器（按天轮转） ---
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    file_handler = TimedRotatingFileHandler(
        filename=str(log_dir / "app.log"),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(logging.Formatter(log_format_str, date_format_str))
    file_handler.setLevel(log_level)
    root_logger.addHandler(file_handler)

    # --- 错误日志独立文件 ---
    error_handler = TimedRotatingFileHandler(
        filename=str(log_dir / "app.error.log"),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    error_handler.suffix = "%Y-%m-%d"
    error_handler.setFormatter(logging.Formatter(log_format_str, date_format_str))
    error_handler.setLevel(logging.ERROR)
    root_logger.addHandler(error_handler)

    logging.info(f"日志系统初始化完成，级别: {settings.log_level}")


# =========================
# 应用生命周期
# =========================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 应用生命周期管理。

    启动时: 加载配置、初始化日志。
    关闭时: 清理资源、关闭连接池。
    """
    logger = logging.getLogger(__name__)
    settings = get_settings()

    # --- 启动阶段 ---
    logger.info(f"🚀 {settings.app_name} v{settings.app_version} 正在启动...")
    logger.info(f"   LLM: {settings.llm.base_url} (model: {settings.llm.model_name})")
    logger.info(f"   Neo4j: {settings.neo4j.uri}")
    logger.info(f"   Redis: {settings.redis.url}")
    logger.info(f"   Milvus: {settings.milvus.host}:{settings.milvus.port}")
    langsmith_status = "✅ enabled" if settings.langsmith.api_key else "⚠️  disabled (missing API Key)"
    logger.info(f"   LangSmith: {langsmith_status} — project: {settings.langsmith.project}")

    yield  # 应用运行中

    # --- 关闭阶段 ---
    logger.info(f"👋 {settings.app_name} 正在关闭...")
    # TODO: 后续添加数据库连接池清理、MCP 客户端关闭等逻辑


# =========================
# FastAPI 实例
# =========================

app = FastAPI(
    title="SafeGuard-AI (安卫智脑)",
    description="工业安全智能体 —— 隐患智能研判与闭环处置工作流",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 中间件（允许前端跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(hazard_router)
app.include_router(meeting_router)
app.include_router(training_router)


# =========================
# 健康检查接口
# =========================


@app.get("/health", tags=["系统"])
async def health_check():
    """
    健康检查端点。

    返回服务运行状态和当前时间戳。
    可用于 K8s liveness/readiness probe。

    Returns:
        dict: 包含 status 和 timestamp 的响应
    """
    settings = get_settings()
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "timestamp": datetime.now().isoformat(),
    }


# =========================
# 启动入口
# =========================

if __name__ == "__main__":
    import uvicorn

    _setup_logging()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=get_settings().log_level.lower(),
    )
