#!/usr/bin/env python3
"""
SafeGuard-AI (安卫智脑) Phase 1 发布归档脚本
=============================================
打包当前发布态核心文件为 .tar.gz 归档，并生成 SHA256SUMS.txt 校验文件。

用途: 一键归档 Phase 1 所有核心产物，方便未来回滚或审计。
用法: python RELEASE_ARCHIVE.py
输出: SafeGuard-AI_Phase1_v20260611.tar.gz + SHA256SUMS.txt
"""

import os
import sys
import hashlib
import tarfile
from pathlib import Path
from datetime import datetime

# ──────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent
ARCHIVE_NAME = "SafeGuard-AI_v20260611_RELEASE.tar.gz"
CHECKSUM_FILE = "dist/SHA256SUMS.txt"

# Windows GBK 终端兼容
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 白名单：仅打包以下路径（相对于项目根目录）
WHITELIST = [
    # === 代码 ===
    "app/",
    "scripts/init_neo4j.py",
    "scripts/embed_to_milvus.py",
    "requirements.txt",
    "Dockerfile",
    ".dockerignore",

    # === 文档 ===
    "README.md",
    "RELEASE_NOTES.md",
    "DEPLOYMENT.md",
    "ARCHITECTURE.md",

    # === 配置 ===
    ".env.example",
    "docker-compose.yml",
]

# 排除模式：在扫描目录时排除这些文件/目录
EXCLUDE_PATTERNS = [
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    "*.jpg",
    "*.png",
    "*.mp4",
    "*.avi",
    ".env",
]

# 目录级排除：这些目录即使在白名单中也不会被扫描
EXCLUDE_DIRS = [
    ".git",
    ".vscode",
    ".idea",
    "tests",
    "mock_data",
    "logs",
    "__pycache__",
    "venv",
    ".venv",
]


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

def should_exclude(entry_path: str) -> bool:
    """检查路径是否匹配排除模式或位于排除目录中。"""
    name = os.path.basename(entry_path)

    # 检查文件级排除模式
    for pattern in EXCLUDE_PATTERNS:
        if pattern.startswith("*"):
            if name.endswith(pattern[1:]):
                return True
        elif pattern in entry_path:
            return True

    # 检查目录级排除（路径中任一目录段命中即排除）
    parts = Path(entry_path).parts
    for part in parts:
        if part in EXCLUDE_DIRS:
            return True

    # 排除 .env.local 等本地覆盖文件
    if name.startswith(".env.") and name != ".env.example":
        return True

    return False


def collect_files(root: Path) -> list[Path]:
    """按白名单收集需要打包的文件列表。"""
    files: list[Path] = []
    seen: set[str] = set()

    for entry in WHITELIST:
        full_path = root / entry
        if not full_path.exists():
            print(f"  ⚠️  跳过（不存在）: {entry}")
            continue

        if full_path.is_file():
            if not should_exclude(str(full_path)):
                rel = str(full_path.relative_to(root))
                if rel not in seen:
                    files.append(full_path)
                    seen.add(rel)
            continue

        # 目录：递归收集
        for f in sorted(full_path.rglob("*")):
            if f.is_file():
                rel = str(f.relative_to(root))
                if rel not in seen and not should_exclude(str(f)):
                    files.append(f)
                    seen.add(rel)

    return files


def compute_sha256(filepath: Path) -> str:
    """计算单个文件的 SHA-256 哈希值。"""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def generate_checksums(files: list[Path], root: Path) -> str:
    """生成 SHA256SUMS 格式的校验内容。"""
    lines = [
        f"# SafeGuard-AI Phase 1 Release Archive",
        f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# 归档文件: {ARCHIVE_NAME}",
        f"# 文件总数: {len(files)}",
        f"#",
    ]
    for f in sorted(files, key=lambda x: str(x.relative_to(root))):
        rel = str(f.relative_to(root))
        h = compute_sha256(f)
        lines.append(f"{h}  {rel}")
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  📦 SafeGuard-AI (安卫智脑) Phase 1 发布归档")
    print("=" * 70)
    print(f"  归档日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  项目根目录: {PROJECT_ROOT}")
    print()

    # 1. 收集文件
    print("🔍 扫描白名单文件...")
    files = collect_files(PROJECT_ROOT)
    print(f"  ✅ 收集到 {len(files)} 个文件\n")

    # 2. 打印文件清单
    print("📋 打包清单:")
    print("-" * 70)
    total_size = 0
    for f in sorted(files, key=lambda x: str(x.relative_to(PROJECT_ROOT))):
        rel = str(f.relative_to(PROJECT_ROOT))
        size = f.stat().st_size
        total_size += size
        print(f"  {size:>10,} B  {rel}")
    print("-" * 70)
    print(f"  合计: {len(files)} 文件, {total_size:,} B")
    print()

    # 3. 生成 SHA256SUMS.txt
    print("🔐 计算 SHA-256 校验码...")
    checksums = generate_checksums(files, PROJECT_ROOT)
    checksum_path = PROJECT_ROOT / CHECKSUM_FILE
    with open(checksum_path, "w", encoding="utf-8") as f:
        f.write(checksums)
    print(f"  ✅ 已生成: {CHECKSUM_FILE}\n")

    # 4. 打包 .tar.gz
    print(f"📦 正在打包: {ARCHIVE_NAME} ...")
    archive_path = PROJECT_ROOT / "dist" / ARCHIVE_NAME
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as tar:
        for f in sorted(files, key=lambda x: str(x.relative_to(PROJECT_ROOT))):
            rel = str(f.relative_to(PROJECT_ROOT))
            tar.add(f, arcname=rel)
    archive_size = archive_path.stat().st_size
    print(f"  ✅ 打包完成: {archive_path}")
    print(f"     大小: {archive_size:,} B ({archive_size / 1024:.1f} KB)")
    print()

    # 5. 计算归档文件自身的校验码
    archive_hash = compute_sha256(archive_path)
    print(f"🔐 归档校验码 (SHA-256):")
    print(f"     {archive_hash}")
    print()

    # 6. 追加归档校验码到 SHA256SUMS
    with open(checksum_path, "a", encoding="utf-8") as f:
        f.write(f"\n# === 归档文件自身校验 ===\n")
        f.write(f"{archive_hash}  {ARCHIVE_NAME}\n")
    print(f"  ✅ 归档校验码已追加到 {CHECKSUM_FILE}")
    print()

    # 7. 完结
    print("=" * 70)
    print("  🎉 归档完成！")
    print("=" * 70)
    print(f"  归档文件: {archive_path}")
    print(f"  校验文件: {checksum_path}")
    print()
    print("  📋 快速验证命令:")
    print(f"     # 验证归档完整性")
    print(f"     sha256sum -c {CHECKSUM_FILE}")
    print(f"     # 查看打包内容")
    print(f"     tar -tzf {ARCHIVE_NAME}")
    print(f"     # 解压到指定目录")
    print(f"     tar -xzf {ARCHIVE_NAME} -C /path/to/extract/")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
