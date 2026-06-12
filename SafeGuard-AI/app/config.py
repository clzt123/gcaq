"""
SafeGuard-AI 配置管理模块

基于 pydantic-settings 统一管理所有环境变量与配置项。
所有外部依赖密钥和连接信息必须通过此类获取，严禁在业务代码中硬编码。

设计模式参考: Base/Config/setting.py 的「子 Settings 类 + 聚合单例」模式。
"""
import logging
import os
from pathlib import Path
from typing import Optional, Any, Dict

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


# =========================
# 辅助函数: 定位项目根目录
# =========================
def _find_project_root() -> Path:
    """
    向上查找项目根目录（包含 .env 或 CLAUDE.md 的目录）。

    Returns:
        项目根目录路径

    Raises:
        FileNotFoundError: 找不到项目根目录时抛出
    """
    current = Path(__file__).resolve().parent.parent  # app/ 的父级即项目根
    if (current / "CLAUDE.md").exists() or (current / ".env").exists():
        return current

    # 如果当前目录不匹配，尝试向上查找
    for parent in current.parents:
        if (parent / "CLAUDE.md").exists():
            return parent

    raise FileNotFoundError("无法定位项目根目录，请确保 CLAUDE.md 或 .env 文件存在。")


# =========================
# 基础 Settings 基类
# =========================
class _BaseEnvSettings(BaseSettings):
    """
    自动加载 .env 文件的配置基类。

    所有子 Settings 类继承此类以获得自动加载 .env 的能力。
    支持 env_prefix 以区分不同模块的环境变量命名空间。

    使用示例:
        class MySettings(_BaseEnvSettings):
            api_key: str
            model_config = SettingsConfigDict(env_prefix="LLM_", extra="ignore")
    """

    def __init__(self, **kwargs: Any) -> None:
        project_root = _find_project_root()
        env_file = project_root / ".env"

        if not env_file.exists():
            example_file = project_root / ".env.example"
            if example_file.exists():
                raise FileNotFoundError(
                    f"缺少 .env 配置文件，请根据 .env.example 创建后启动项目。\n"
                    f"参考模板：{example_file}\n"
                    f"复制命令：cp .env.example .env"
                )
            else:
                raise FileNotFoundError(
                    "缺少 .env 配置文件，请创建 .env 文件后启动项目。"
                )

        super().__init__(_env_file=env_file, **kwargs)

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
    )

    def get(self, key: str, default: Any = None) -> Any:
        """
        安全获取环境变量值。

        Args:
            key: 环境变量名
            default: 默认值

        Returns:
            环境变量值或默认值
        """
        return getattr(self, key, default)


# =========================
# LLM 配置
# =========================
class LLMSettings(_BaseEnvSettings):
    """
    LLM 大模型配置。

    支持 OpenAI 兼容接口（DeepSeek、Qwen 等）。
    """

    api_key: str = Field(..., description="LLM API 密钥")
    base_url: str = Field("https://api.deepseek.com", description="LLM API 基础地址")
    model_name: str = Field("deepseek-chat", description="默认模型名称")
    timeout: float = Field(300.0, description="请求超时时间（秒）")

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        extra="ignore",
    )


# =========================
# Neo4j 图数据库配置
# =========================
class Neo4jSettings(_BaseEnvSettings):
    """
    Neo4j 图数据库连接配置。

    用于 GraphRAG 知识引擎的结构化图谱存储。
    """

    uri: str = Field("bolt://localhost:7687", description="Neo4j Bolt 连接地址")
    user: str = Field("neo4j", description="数据库用户名")
    password: str = Field(..., description="数据库密码")
    database: str = Field("neo4j", description="数据库名称")
    use_mock: bool = Field(True, description="是否使用 Mock 模式（开发环境默认开启，生产环境设为 False）")

    model_config = SettingsConfigDict(
        env_prefix="NEO4J_",
        extra="ignore",
    )


# =========================
# Redis 配置
# =========================
class RedisSettings(_BaseEnvSettings):
    """
    Redis 短期记忆配置。

    用于存储对话历史、会话状态和工作记忆。
    短期记忆使用 Redis List 数据结构实现滑动窗口缓冲。
    """

    url: str = Field("redis://localhost:6379/0", description="Redis 连接 URL")
    max_connections: int = Field(10, description="连接池最大连接数")
    short_term_maxlen: int = Field(100, description="短期记忆最大保存轮数")
    short_term_window: int = Field(5, description="默认返回最近 N 轮对话")

    model_config = SettingsConfigDict(
        env_prefix="REDIS_",
        extra="ignore",
    )


# =========================
# Milvus 向量库配置
# =========================
class MilvusSettings(_BaseEnvSettings):
    """
    Milvus 向量数据库配置。

    用于专家经验记忆的向量存储与相似案例检索。
    支持 BGE-M3 (1024维) / text-embedding-3-large (3072维) 等模型。
    """

    host: str = Field("localhost", description="Milvus 服务地址")
    port: int = Field(19530, description="Milvus gRPC 端口")
    collection_name: str = Field("knowledge_chunks", description="默认 Collection 名称（GraphRAG 知识块）")
    memory_collection_name: str = Field("expert_memory", description="专家经验记忆专用 Collection")
    vector_dim: int = Field(1024, description="向量维度 (BGE-M3: 1024)")
    metric_type: str = Field("IP", description="相似度度量: IP(内积) / L2 / COSINE")
    index_type: str = Field("IVF_FLAT", description="索引类型: IVF_FLAT / IVF_SQ8 / HNSW")
    search_top_k: int = Field(10, description="向量检索默认返回数")

    model_config = SettingsConfigDict(
        env_prefix="MILVUS_",
        extra="ignore",
    )


# =========================
# DashScope 视觉大模型配置
# =========================
class DashScopeSettings(_BaseEnvSettings):
    """
    DashScope 视觉大模型配置（阿里云 Qwen-VL 多模态识别）。

    用于工业安全图片的隐患检测：安全帽、反光衣、吸烟、玩手机等。
    """

    api_key: str = Field("", description="DashScope API 密钥（留空则使用 Mock 降级）")
    vl_model: str = Field("qwen-vl-max-latest", description="视觉模型名称")
    vl_timeout: float = Field(60.0, description="视觉请求超时（秒）")

    model_config = SettingsConfigDict(
        env_prefix="DASHSCOPE_",
        extra="ignore",
    )


# =========================
# 智能会议纪要配置
# =========================
class MeetingSettings(_BaseEnvSettings):
    """
    智能会议纪要配置（功能 14）。

    控制 ASR 转录模式和 NER 提取策略。
    """

    asr_mode: str = Field("mock", description="ASR 转录模式: mock / whisper_api / dashscope_asr")
    asr_model: str = Field("whisper-1", description="Whisper 模型名称")
    asr_api_key: str = Field("", description="ASR API 密钥（留空使用 Mock）")
    extraction_mode: str = Field("llm", description="NER 提取模式: llm / regex")
    max_transcript_chars: int = Field(6000, description="LLM 提取最大字符数")

    model_config = SettingsConfigDict(
        env_prefix="MEETING_",
        extra="ignore",
    )


# =========================
# LangSmith 可观测性配置
# =========================
class LangSmithSettings(_BaseEnvSettings):
    """
    LangSmith 可观测性配置（LangChain/LangGraph 追踪与调试）。

    用于追踪 LangGraph 执行流程、调试 RAG 检索效果并监控 LLM 调用。
    未配置 API Key 时不会启用追踪（不影响正常功能）。

    使用方式:
        1. 在 .env 中设置 LANGSMITH_API_KEY=你的密钥
        2. 启动程序时自动设置 LANGCHAIN_TRACING_V2 环境变量
        3. 在 https://smith.langchain.com 查看追踪数据
    """

    api_key: Optional[str] = Field(None, description="LangSmith API 密钥（留空则不启用追踪）")
    project: str = Field("SafeGuard-AI", description="LangSmith 项目名称")
    endpoint: str = Field("https://api.smith.langchain.com", description="LangSmith API 端点")

    model_config = SettingsConfigDict(
        env_prefix="LANGSMITH_",
        extra="ignore",
    )


# =========================
# 应用程序主配置（聚合器）
# =========================
class Settings(_BaseEnvSettings):
    """
    应用程序主配置类。

    聚合所有模块的子配置实例。
    通过 get_settings() 获取全局单例。
    """

    # 应用基础配置
    app_name: str = Field("SafeGuard-AI", description="应用名称")
    app_version: str = Field("0.1.0", description="应用版本号")
    log_level: str = Field("INFO", description="日志级别")

    # 子模块配置
    llm: LLMSettings = Field(default_factory=LLMSettings, description="LLM 配置")
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings, description="Neo4j 配置")
    redis: RedisSettings = Field(default_factory=RedisSettings, description="Redis 配置")
    milvus: MilvusSettings = Field(default_factory=MilvusSettings, description="Milvus 配置")
    dashscope: DashScopeSettings = Field(default_factory=DashScopeSettings, description="DashScope 配置")
    meeting: MeetingSettings = Field(default_factory=MeetingSettings, description="会议纪要配置")
    langsmith: LangSmithSettings = Field(default_factory=LangSmithSettings, description="LangSmith 配置")

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# =========================
# 全局单例
# =========================
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    获取全局 Settings 单例。

    首次调用时从 .env 文件加载配置，后续调用返回缓存实例。

    Returns:
        Settings 实例
    """
    global _settings
    if _settings is None:
        _settings = Settings()
        logger.info(f"配置加载完成: {_settings.app_name} v{_settings.app_version}")
    return _settings


def setup_langsmith() -> bool:
    """
    初始化 LangSmith 可观测性追踪。

    从配置读取 LangSmith API Key，若已配置则设置 LangChain 官方环境变量
    以启用全链路追踪（LangGraph 执行流、RAG 检索、LLM 调用）。

    必须在任何 LangChain/LangGraph 导入之前调用，否则追踪可能不生效。

    Returns:
        bool: True 表示追踪已启用，False 表示未配置 API Key

    使用示例:
        from app.config import setup_langsmith
        setup_langsmith()  # 在导入 langchain/lagraph 之前调用
    """
    settings = get_settings()
    api_key = settings.langsmith.api_key

    if api_key and api_key.strip():
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = api_key.strip()
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith.project
        os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith.endpoint
        logger.info(f"✅ LangSmith tracing enabled for project: {settings.langsmith.project}")
        return True
    else:
        logger.warning("⚠️  LangSmith API Key missing, tracing disabled. "
                       "请在 .env 中设置 LANGSMITH_API_KEY")
        return False
