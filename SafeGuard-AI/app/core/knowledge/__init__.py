"""
知识库管理模块 (Knowledge Base Management)

实现技术方案功能 2 — 结构化知识库：
    1. 文档解析（PDF/Word 法规文档 → 结构化文本块）
    2. 文本分块（中文感知的 RecursiveCharacterTextSplitter）
    3. BGE-M3 向量化入库流水线
    4. Milvus knowledge_chunks Collection 管理

核心类:
    DocumentParser     — 文档解析器（Unstructured + Mock 降级）
    KnowledgeIngestion — 知识入库流水线（解析→分块→向量化→入库）
"""

from app.core.knowledge.document_parser import DocumentParser
from app.core.knowledge.ingestion import KnowledgeIngestion

__all__ = [
    "DocumentParser",
    "KnowledgeIngestion",
]
