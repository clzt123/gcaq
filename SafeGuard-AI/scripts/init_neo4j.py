"""
Neo4j 图谱初始化脚本。

读取 mock_data/init_graph.cypher，连接真实 Neo4j 并执行初始化语句。
用于将预定义的知识图谱（设备→隐患→法规→SOP）导入生产数据库。

使用方式:
    cd SafeGuard-AI
    python scripts/init_neo4j.py              # 交互式确认后执行
    python scripts/init_neo4j.py --yes        # 跳过确认直接执行
    python scripts/init_neo4j.py --dry-run    # 仅解析 Cypher，不实际执行

前置条件:
    1. .env 中 NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD 已配置真实值
    2. .env 中 NEO4J_USE_MOCK=false
    3. Neo4j 数据库已启动（docker compose up -d neo4j）
"""
import argparse
import logging
import sys
from pathlib import Path
from typing import List

# 将项目根目录加入 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import get_settings
from app.utils import get_mock_path

logger = logging.getLogger(__name__)


# =========================
# 日志配置
# =========================

def setup_logging() -> None:
    """配置带颜色的控制台日志。"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)

    class _ColoredFormatter(logging.Formatter):
        COLORS = {
            "DEBUG": "\033[36m",
            "INFO": "\033[32m",
            "WARNING": "\033[33m",
            "ERROR": "\033[31m",
        }
        RESET = "\033[0m"

        def format(self, record: logging.LogRecord) -> str:
            msg = super().format(record)
            color = self.COLORS.get(record.levelname, "")
            return f"{color}{msg}{self.RESET}" if color else msg

    handler.setFormatter(_ColoredFormatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # 抑制 neo4j driver 内部日志
    logging.getLogger("neo4j").setLevel(logging.WARNING)


# =========================
# Cypher 解析
# =========================

def parse_cypher_statements(cypher_text: str) -> List[str]:
    """
    解析 init_graph.cypher，提取所有可执行的 Cypher 语句。

    规则:
        - 跳过空行和纯注释行（以 // 开头）
        - 以分号或 EOF 作为语句结束标记
        - 去除每行首尾空白

    Args:
        cypher_text: 完整的 Cypher 文件内容

    Returns:
        Cypher 语句列表
    """
    statements: List[str] = []
    current_lines: List[str] = []

    for raw_line in cypher_text.split("\n"):
        line = raw_line.strip()

        # 跳过空行和注释行
        if not line or line.startswith("//"):
            continue

        current_lines.append(line)

        # 分号表示语句结束
        if line.rstrip().endswith(";"):
            stmt = " ".join(current_lines)
            # 去除尾部分号（neo4j driver 自动处理）
            stmt = stmt.rstrip().rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            current_lines = []

    # 处理末尾无分号的语句
    if current_lines:
        stmt = " ".join(current_lines).strip()
        if stmt:
            statements.append(stmt)

    return statements


# =========================
# 核心逻辑
# =========================

async def clear_and_init_graph(
    uri: str,
    user: str,
    password: str,
    database: str,
    cypher_file: Path,
) -> None:
    """
    连接 Neo4j、清空现有数据、执行初始化 Cypher 脚本。

    执行顺序:
        1. 连接 Neo4j
        2. 删除所有节点/关系 (DETACH DELETE)
        3. 逐条执行 init_graph.cypher 中的 CREATE 语句
        4. 验证导入结果（各 Label 行数统计）

    Args:
        uri: Neo4j Bolt 连接地址
        user: 用户名
        password: 密码
        database: 数据库名
        cypher_file: init_graph.cypher 文件路径
    """
    from neo4j import AsyncGraphDatabase

    if not cypher_file.exists():
        raise FileNotFoundError(f"Cypher 初始化文件不存在: {cypher_file}")

    cypher_text = cypher_file.read_text(encoding="utf-8")
    statements = parse_cypher_statements(cypher_text)

    logger.info(f"📄 解析到 {len(statements)} 条 Cypher 语句")
    for i, stmt in enumerate(statements):
        logger.debug(f"  [{i+1}] {stmt[:100]}...")

    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    try:
        await driver.verify_connectivity()
        logger.info(f"✅ Neo4j 连接成功: {uri} (database={database})")

        async with driver.session(database=database) as session:

            # ---- Step 1: 清空现有数据 ----
            logger.info("🗑️  清空现有图谱数据...")
            await session.run("MATCH (n) DETACH DELETE n")
            logger.info("   清空完成。")

            # ---- Step 2: 逐条执行 CREATE 语句 ----
            logger.info(f"🔨 执行 {len(statements)} 条初始化语句...")
            success_count = 0
            for i, stmt in enumerate(statements, 1):
                try:
                    result = await session.run(stmt)
                    summary = await result.consume()
                    counters = summary.counters
                    logger.info(
                        f"   [{i}/{len(statements)}] ✅ "
                        f"nodes_created={counters.nodes_created}, "
                        f"relationships_created={counters.relationships_created}"
                    )
                    success_count += 1
                except Exception as e:
                    logger.error(f"   [{i}/{len(statements)}] ❌ 执行失败: {e}")
                    logger.error(f"   语句: {stmt[:200]}")
                    raise

            # ---- Step 3: 验证导入结果 ----
            logger.info("📊 验证导入结果:")
            labels = ["Equipment", "Hazard", "Regulation", "SOP"]
            total_nodes = 0
            for label in labels:
                result = await session.run(
                    f"MATCH (n:{label}) RETURN count(n) AS cnt"
                )
                record = await result.single()
                count = record["cnt"] if record else 0
                total_nodes += count
                logger.info(f"   {label}: {count} 个节点")

            # 关系统计
            result = await session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
            record = await result.single()
            rel_count = record["cnt"] if record else 0
            logger.info(f"   Relationships: {rel_count} 条边")

            logger.info(f"\n{'='*60}")
            logger.info(f"🎉 Neo4j 图谱初始化完成！")
            logger.info(f"   共导入 {total_nodes} 个节点，{rel_count} 条关系")
            logger.info(f"   语句: {success_count}/{len(statements)} 成功")
            logger.info(f"{'='*60}")

    finally:
        await driver.close()


# =========================
# 命令行入口
# =========================

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="SafeGuard-AI Neo4j 图谱初始化",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python scripts/init_neo4j.py              # 交互式确认
    python scripts/init_neo4j.py --yes        # 跳过确认
    python scripts/init_neo4j.py --dry-run    # 仅预览 Cypher
        """,
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="跳过确认，直接执行",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅解析 Cypher 语句并打印预览，不连接数据库",
    )
    args = parser.parse_args()

    setup_logging()

    # ---- 加载配置 ----
    settings = get_settings()
    neo4j_conf = settings.neo4j

    if neo4j_conf.use_mock:
        logger.error("❌ NEO4J_USE_MOCK=true，请先在 .env 中设置 NEO4J_USE_MOCK=false")
        logger.error("   并确保 Neo4j Docker 已启动: docker compose up -d neo4j")
        sys.exit(1)

    # ---- 读取 Cypher 文件 ----
    cypher_file = get_mock_path("init_graph.cypher")
    cypher_text = cypher_file.read_text(encoding="utf-8")
    statements = parse_cypher_statements(cypher_text)

    # ---- Dry-run 模式 ----
    if args.dry_run:
        print(f"\n📄 Cypher 文件: {cypher_file}")
        print(f"📝 共 {len(statements)} 条语句:\n")
        for i, stmt in enumerate(statements, 1):
            print(f"--- 语句 {i} ---")
            print(stmt)
            print()
        logger.info("Dry-run 完成（未连接数据库）。")
        return

    # ---- 打印连接信息 ----
    print(f"\n{'='*60}")
    print(f"  SafeGuard-AI Neo4j 图谱初始化")
    print(f"{'='*60}")
    print(f"  连接地址:   {neo4j_conf.uri}")
    print(f"  用户名:     {neo4j_conf.user}")
    print(f"  数据库:     {neo4j_conf.database}")
    print(f"  Cypher 文件: {cypher_file}")
    print(f"  语句数量:   {len(statements)}")
    print(f"{'='*60}\n")

    # ---- 确认 ----
    if not args.yes:
        print("⚠️  警告: 此操作将清空 Neo4j 中所有现有数据！")
        response = input("确认执行？(yes/no): ").strip().lower()
        if response not in ("yes", "y"):
            logger.info("已取消。")
            return

    # ---- 执行 ----
    await clear_and_init_graph(
        uri=neo4j_conf.uri,
        user=neo4j_conf.user,
        password=neo4j_conf.password,
        database=neo4j_conf.database,
        cypher_file=cypher_file,
    )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
