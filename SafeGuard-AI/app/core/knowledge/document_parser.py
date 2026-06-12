"""
文档解析器

解析 PDF/Word 法规文档，提取结构化文本块及其元数据。
支持真实解析（Unstructured 库）和 Mock 降级（预结构化 JSON）。

设计原则:
    - 抽象接口 + 多实现（真实/Mock）
    - 中文感知的分块策略（按段落/条款边界切分）
    - 元数据保留（来源文档、条款号、页码）
    - 优雅降级：Unstructured 不可用时自动切换 Mock
"""
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils import get_mock_path

logger = logging.getLogger(__name__)

# =========================
# 数据模型
# =========================


@dataclass
class DocumentChunk:
    """
    文档分块。

    Attributes:
        chunk_id: 唯一分块标识 (e.g. "REG_GB30871_001")
        text: 分块文本内容
        source_doc: 来源文档名称
        doc_type: 文档类型 (regulation/sop/standard/guideline)
        clause: 条款号 (e.g. "§5.4.2.3")
        page: 页码（从 1 开始）
        chunk_index: 分块在文档中的序号
        metadata: 额外的键值对元数据
    """

    chunk_id: str
    text: str
    source_doc: str
    doc_type: str = "regulation"
    clause: str = ""
    page: int = 0
    chunk_index: int = 0
    metadata: Dict[str, str] = field(default_factory=dict)


# =========================
# 抽象文档解析器
# =========================


class BaseDocumentParser(ABC):
    """文档解析器抽象基类。"""

    @abstractmethod
    async def parse(self, file_path: Path) -> List[DocumentChunk]:
        """
        解析文档为结构化分块列表。

        Args:
            file_path: 文档路径（PDF/DOCX/TXT）

        Returns:
            DocumentChunk 列表
        """
        ...

    @abstractmethod
    async def parse_batch(self, file_paths: List[Path]) -> List[DocumentChunk]:
        """
        批量解析多个文档。

        Args:
            file_paths: 文档路径列表

        Returns:
            所有文档的 DocumentChunk 合并列表
        """
        ...


# =========================
# 文本分块工具
# =========================


class ChineseTextSplitter:
    """
    中文感知的文本分块器。

    优先在自然边界处切分：段落 > 条款号 > 句子 > 固定长度。
    避免在中文词汇中间截断。

    使用方式:
        splitter = ChineseTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = splitter.split(text, metadata={"source": "doc.pdf"})
    """

    # 条款号模式：匹配 "第X条"、"§X.Y.Z"、"X.Y.Z " 等
    CLAUSE_PATTERN = re.compile(
        r'(?:^|\n)\s*(?:第\s*[\d零一二三四五六七八九十百千万]+\s*条|'
        r'§\s*[\d.]+|'
        r'\d+\.\d+(?:\.\d+)?\s)',
        re.MULTILINE,
    )

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        """
        初始化分块器。

        Args:
            chunk_size: 每个分块的最大字符数
            chunk_overlap: 相邻分块的重叠字符数
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> List[str]:
        """
        将文本切分为适合向量化的块。

        切分策略:
            1. 先按段落（双换行）切分
            2. 过长的段落按条款号边界切分
            3. 仍过长的按句子切分
            4. 最终兜底：固定长度切分 + 重叠

        Args:
            text: 原始文本
            metadata: 可选的元数据（保留用于后续扩展）

        Returns:
            文本块列表
        """
        if not text or not text.strip():
            return []

        # Step 1: 按段落切分
        paragraphs = self._split_by_paragraph(text)
        logger.debug(f"[TextSplitter] 段落切分: {len(paragraphs)} 段")

        # Step 2: 过长的段落按条款边界再切分
        chunks: List[str] = []
        for para in paragraphs:
            if len(para) <= self.chunk_size:
                if para.strip():
                    chunks.append(para.strip())
            else:
                sub_chunks = self._split_long_paragraph(para)
                chunks.extend(sub_chunks)

        # Step 3: 合并过小的块 + 切分过大的块
        final_chunks = self._merge_and_split(chunks)

        logger.debug(
            f"[TextSplitter] 最终分块: {len(final_chunks)} 块, "
            f"平均长度={sum(len(c) for c in final_chunks) / max(len(final_chunks), 1):.0f}"
        )

        return final_chunks

    def _split_by_paragraph(self, text: str) -> List[str]:
        """按双换行或明显的段落标记切分。"""
        # 统一换行符
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # 按空行切分
        parts = re.split(r'\n\s*\n', text)
        return [p for p in parts if p.strip()]

    def _split_long_paragraph(self, paragraph: str) -> List[str]:
        """切分过长段落：优先在条款号边界切分。"""
        # 查找条款号分割点
        clause_matches = list(self.CLAUSE_PATTERN.finditer(paragraph))

        if clause_matches:
            chunks = []
            for i, match in enumerate(clause_matches):
                start = match.start()
                end = clause_matches[i + 1].start() if i + 1 < len(clause_matches) else len(paragraph)
                chunk_text = paragraph[start:end].strip()
                if len(chunk_text) > self.chunk_size:
                    # 仍过长，按句子再切
                    chunks.extend(self._split_by_sentence(chunk_text))
                else:
                    if chunk_text:
                        chunks.append(chunk_text)
            return chunks

        # 无法按条款切分 → 按句子切分
        return self._split_by_sentence(paragraph)

    def _split_by_sentence(self, text: str) -> List[str]:
        """按中文句号、分号等标点切分句子。"""
        # 中文句子边界
        sentence_breaks = r'[。！？；\n]'
        sentences = re.split(f'({sentence_breaks})', text)

        chunks: List[str] = []
        current = ""
        for part in sentences:
            if len(current) + len(part) <= self.chunk_size:
                current += part
            else:
                if current.strip():
                    chunks.append(current.strip())
                current = part

        if current.strip():
            chunks.append(current.strip())

        # 仍有超长块 → 固定长度强制切分
        final_chunks: List[str] = []
        for chunk in chunks:
            if len(chunk) <= self.chunk_size:
                final_chunks.append(chunk)
            else:
                for i in range(0, len(chunk), self.chunk_size - self.chunk_overlap):
                    sub = chunk[i : i + self.chunk_size]
                    if sub.strip():
                        final_chunks.append(sub.strip())

        return final_chunks

    def _merge_and_split(self, chunks: List[str]) -> List[str]:
        """合并过小的相邻块，确保每个块在合理大小范围内。"""
        if not chunks:
            return []

        min_chunk_size = self.chunk_size // 3  # 最小块大小
        result: List[str] = []
        current = ""

        for chunk in chunks:
            if len(current) + len(chunk) <= self.chunk_size:
                current = (current + "\n" + chunk).strip()
            else:
                if current and len(current) >= min_chunk_size:
                    result.append(current)
                    current = chunk
                elif current:
                    # current 太小，尝试与 chunk 的前半部分合并
                    split_point = self.chunk_size - len(current)
                    current = (current + "\n" + chunk[:split_point]).strip()
                    result.append(current)
                    current = chunk[split_point:]
                else:
                    current = chunk

        if current.strip():
            if result and len(current) < min_chunk_size:
                # 合并到前一个块
                result[-1] = (result[-1] + "\n" + current).strip()
            else:
                result.append(current.strip())

        return result


# =========================
# 真实文档解析器（Unstructured）
# =========================


class UnstructuredParser(BaseDocumentParser):
    """
    基于 Unstructured 库的真实文档解析器。

    支持 PDF、DOCX、TXT 格式。
    自动提取文档结构（标题、段落、列表、表格等）。
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.splitter = ChineseTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    async def parse(self, file_path: Path) -> List[DocumentChunk]:
        """
        使用 Unstructured 解析文档。

        Args:
            file_path: 文档路径

        Returns:
            DocumentChunk 列表

        Raises:
            ImportError: unstructured 未安装
            FileNotFoundError: 文件不存在
        """
        if not file_path.exists():
            raise FileNotFoundError(f"文档不存在: {file_path}")

        try:
            from unstructured.partition.auto import partition

            logger.info(f"[DocParser] Unstructured 解析: {file_path.name}")

            # 解析文档元素
            elements = partition(filename=str(file_path))

            # 提取全文文本
            full_text = "\n\n".join(
                str(el) for el in elements if str(el).strip()
            )

            # 提取文档元数据
            doc_name = file_path.stem
            doc_type = self._infer_doc_type(doc_name)

            # 分块
            text_chunks = self.splitter.split(full_text)

            # 为每个分块提取条款号并构建 DocumentChunk
            chunks: List[DocumentChunk] = []
            for i, text in enumerate(text_chunks):
                clause = self._extract_clause(text)
                chunk_id = f"{doc_name}_{i:04d}"
                chunks.append(DocumentChunk(
                    chunk_id=chunk_id,
                    text=text,
                    source_doc=file_path.name,
                    doc_type=doc_type,
                    clause=clause,
                    page=0,
                    chunk_index=i,
                    metadata={"parser": "unstructured"},
                ))

            logger.info(
                f"[DocParser] 解析完成: {file_path.name} → "
                f"{len(chunks)} 块"
            )
            return chunks

        except ImportError:
            logger.warning(
                "[DocParser] Unstructured 未安装，降级为 Mock 解析。"
                "安装命令: pip install unstructured[pdf,docx]"
            )
            raise

        except Exception as e:
            logger.error(f"[DocParser] 解析失败: {file_path.name}: {e}", exc_info=True)
            raise

    async def parse_batch(self, file_paths: List[Path]) -> List[DocumentChunk]:
        """批量解析。"""
        all_chunks: List[DocumentChunk] = []
        for fp in file_paths:
            chunks = await self.parse(fp)
            all_chunks.extend(chunks)
        return all_chunks

    @staticmethod
    def _infer_doc_type(doc_name: str) -> str:
        """根据文档名推断文档类型。"""
        name_lower = doc_name.lower()
        if "标准" in doc_name or "standard" in name_lower or "gb" in name_lower:
            return "standard"
        if "sop" in name_lower or "规程" in doc_name or "操作" in doc_name:
            return "sop"
        if "指南" in doc_name or "guideline" in name_lower:
            return "guideline"
        return "regulation"

    @staticmethod
    def _extract_clause(text: str) -> str:
        """从文本开头提取条款号。"""
        match = re.search(
            r'(?:第\s*[\d零一二三四五六七八九十百千万]+\s*条|'
            r'§\s*[\d.]+|'
            r'\d+\.\d+(?:\.\d+)?)',
            text[:200],
        )
        return match.group(0).strip() if match else ""


# =========================
# Mock 文档解析器（开发/测试阶段）
# =========================


class MockDocumentParser(BaseDocumentParser):
    """
    Mock 文档解析器 — 从预结构化的 JSON 法规数据中读取。

    用于开发阶段无需安装 Unstructured 的场景。
    Mock 数据格式见 mock_data/mock_regulations.json。

    使用方式:
        parser = MockDocumentParser()
        chunks = await parser.parse(Path("GB30871-2022"))
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.splitter = ChineseTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        self._mock_data: Optional[Dict[str, Any]] = None

    def _load_mock_data(self) -> Dict[str, Any]:
        """加载 Mock 法规数据（全局缓存）。"""
        if self._mock_data is not None:
            return self._mock_data

        mock_file = get_mock_path("mock_regulations.json")
        if not mock_file.exists():
            logger.warning(f"Mock 法规文件不存在: {mock_file}")
            self._mock_data = {}
            return self._mock_data

        with open(mock_file, "r", encoding="utf-8") as f:
            self._mock_data = json.load(f)

        doc_count = len(self._mock_data.get("documents", []))
        logger.info(f"[MockDocParser] 加载 Mock 法规: {doc_count} 份文档")
        return self._mock_data

    async def parse(self, file_path: Path) -> List[DocumentChunk]:
        """
        Mock 解析：从 JSON 预结构化数据中读取。

        file_path 可以是文件名（如 "GB30871-2022"）或完整路径，
        用于匹配 mock_regulations.json 中的文档 ID。

        Args:
            file_path: 文档标识符

        Returns:
            DocumentChunk 列表
        """
        data = self._load_mock_data()
        if not data:
            return []

        # 提取文档 ID（去掉路径和扩展名）
        doc_id = file_path.stem if file_path.suffix else file_path.name

        documents = data.get("documents", [])
        doc = None

        # 精确匹配
        for d in documents:
            d_id = d.get("id", "")
            if d_id == doc_id:
                doc = d
                break

        # 模糊匹配（文件名包含 doc_id）
        if doc is None:
            for d in documents:
                d_id = d.get("id", "")
                if doc_id in d_id or d_id in doc_id:
                    doc = d
                    break

        if doc is None:
            logger.warning(f"[MockDocParser] 未找到 Mock 文档: {doc_id}")
            return []

        return self._doc_to_chunks(doc)

    async def parse_batch(self, file_paths: List[Path]) -> List[DocumentChunk]:
        """批量 Mock 解析。"""
        all_chunks: List[DocumentChunk] = []
        for fp in file_paths:
            chunks = await self.parse(fp)
            all_chunks.extend(chunks)
        return all_chunks

    async def parse_all(self) -> List[DocumentChunk]:
        """
        解析所有 Mock 法规文档。

        Returns:
            所有文档的分块列表
        """
        data = self._load_mock_data()
        if not data:
            return []

        all_chunks: List[DocumentChunk] = []
        for doc in data.get("documents", []):
            chunks = self._doc_to_chunks(doc)
            all_chunks.extend(chunks)

        logger.info(
            f"[MockDocParser] 解析全部文档: "
            f"{len(data.get('documents', []))} 份 → {len(all_chunks)} 块"
        )
        return all_chunks

    def _doc_to_chunks(self, doc: Dict[str, Any]) -> List[DocumentChunk]:
        """
        将 Mock 文档转换为分块列表。

        Mock 文档结构:
            {
                "id": "GB30871-2022",
                "title": "危险化学品企业特殊作业安全规范",
                "type": "standard",
                "sections": [
                    {"clause": "§4.1", "title": "...", "content": "..."},
                    ...
                ]
            }

        Args:
            doc: Mock 文档字典

        Returns:
            DocumentChunk 列表
        """
        doc_id = doc.get("id", "unknown")
        doc_title = doc.get("title", doc_id)
        doc_type = doc.get("type", "regulation")
        sections = doc.get("sections", [])

        chunks: List[DocumentChunk] = []
        chunk_index = 0

        for section in sections:
            clause = section.get("clause", "")
            title = section.get("title", "")
            content = section.get("content", "")

            # 构建完整段落文本
            full_text = f"{clause} {title}\n{content}" if clause else content

            # 分块
            text_chunks = self.splitter.split(full_text)

            for text in text_chunks:
                chunk_id = f"{doc_id}_{chunk_index:04d}"
                chunks.append(DocumentChunk(
                    chunk_id=chunk_id,
                    text=text,
                    source_doc=doc_title,
                    doc_type=doc_type,
                    clause=clause,
                    page=0,
                    chunk_index=chunk_index,
                    metadata={
                        "doc_id": doc_id,
                        "section_title": title,
                    },
                ))
                chunk_index += 1

        logger.debug(
            f"[MockDocParser] {doc_id}: {len(sections)} 节 → {len(chunks)} 块"
        )
        return chunks


# =========================
# 统一解析器工厂
# =========================


class DocumentParser:
    """
    统一文档解析器 — 自动选择最佳实现。

    优先级:
        1. Unstructured 库可用且文件存在 → UnstructuredParser
        2. Mock 法规 JSON 数据可用 → MockDocumentParser
        3. 不可用 → 返回空列表（优雅降级）

    使用方式:
        parser = DocumentParser()
        chunks = await parser.parse("/path/to/GB30871-2022.pdf")
        # 或解析所有 Mock 法规:
        all_chunks = await parser.parse_all_mock()
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self._mock_parser = MockDocumentParser(chunk_size, chunk_overlap)
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    async def parse(self, file_path: Path) -> List[DocumentChunk]:
        """
        解析单个文档，自动选择解析器。

        Args:
            file_path: 文档路径或标识符

        Returns:
            DocumentChunk 列表
        """
        # 尝试真实解析
        if file_path.exists() and file_path.suffix.lower() in (".pdf", ".docx", ".txt"):
            try:
                parser = UnstructuredParser(self._chunk_size, self._chunk_overlap)
                return await parser.parse(file_path)
            except (ImportError, Exception) as e:
                logger.info(f"[DocParser] 真实解析不可用 ({e})，降级 Mock")
                return await self._mock_parser.parse(file_path)

        # Mock 降级
        return await self._mock_parser.parse(file_path)

    async def parse_batch(self, file_paths: List[Path]) -> List[DocumentChunk]:
        """批量解析。"""
        all_chunks: List[DocumentChunk] = []
        for fp in file_paths:
            chunks = await self.parse(fp)
            all_chunks.extend(chunks)
        return all_chunks

    async def parse_all_mock(self) -> List[DocumentChunk]:
        """
        解析所有 Mock 法规文档（便捷方法）。

        Returns:
            所有 Mock 法规的 DocumentChunk 列表
        """
        return await self._mock_parser.parse_all()
