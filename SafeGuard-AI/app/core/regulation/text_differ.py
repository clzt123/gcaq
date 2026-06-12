"""
法规文本差异对比器

实现技术方案功能 5 — 对比新旧法规文本，识别变更条款。

对比算法:
    1. 段落级别差异检测（使用 difflib.SequenceMatcher）
    2. 关键词变更提取
    3. 变更类型分类（新增/修订/删除）

设计模式: 支持真实文本对比和预置 Mock 法规变更数据。
"""
import difflib
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.utils import get_mock_path

logger = logging.getLogger(__name__)


# =========================
# 数据模型
# =========================


class ChangeType(str, Enum):
    """变更类型"""
    AMENDED = "amended"       # 修订（内容修改）
    ADDED = "added"           # 新增
    DELETED = "deleted"       # 删除
    UNCHANGED = "unchanged"   # 未变更


@dataclass
class ClauseChange:
    """
    单条法规变更。

    Attributes:
        section_id: 条款编号
        title: 条款标题
        old_text: 旧版本内容
        new_text: 新版本内容
        change_type: 变更类型
        diff_html: HTML 格式的差异对比（可选）
        keywords: 关键词列表
        similarity: 文本相似度 0.0-1.0
    """

    section_id: str
    title: str
    old_text: str = ""
    new_text: str = ""
    change_type: ChangeType = ChangeType.UNCHANGED
    diff_html: str = ""
    keywords: List[str] = field(default_factory=list)
    similarity: float = 1.0


@dataclass
class DiffResult:
    """
    法规差异对比结果。

    Attributes:
        regulation_name: 法规名称
        total_sections: 总条款数
        changed_sections: 变更的条款数
        changes: 变更详情列表
        summary: 变更摘要
    """

    regulation_name: str = ""
    total_sections: int = 0
    changed_sections: int = 0
    changes: List[ClauseChange] = field(default_factory=list)
    summary: str = ""


# =========================
# 文本差异对比器
# =========================


class TextDiffer:
    """
    法规文本差异对比器。

    支持:
        1. 逐条款新旧文本对比（基于 difflib）
        2. 文本相似度计算
        3. 关键词差异提取
        4. HTML 差异报告生成

    使用方式:
        differ = TextDiffer()
        result = differ.compare_regulation(old_text, new_text, section_id="§5.2")
    """

    def __init__(self):
        """初始化对比器。"""
        self._mock_changes: List[Dict[str, Any]] = []
        self._loaded = False

    def _load_mock(self):
        """加载 Mock 法规变更数据。"""
        if self._loaded:
            return

        changes_file = get_mock_path("regulation_changes.json")
        if changes_file.exists():
            with open(changes_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._mock_changes = data.get("changes", [])
            logger.info(f"[TextDiffer] 加载 {len(self._mock_changes)} 组法规变更数据")
        self._loaded = True

    def compare_clause(
        self,
        old_text: str,
        new_text: str,
        section_id: str = "",
        title: str = "",
    ) -> ClauseChange:
        """
        对比单条法规条款的新旧版本。

        Args:
            old_text: 旧版本文本
            new_text: 新版本文本
            section_id: 条款编号
            title: 条款标题

        Returns:
            ClauseChange 变更详情
        """
        if not old_text and not new_text:
            return ClauseChange(section_id=section_id, title=title)

        # 确定变更类型
        if not old_text:
            return ClauseChange(
                section_id=section_id,
                title=title,
                new_text=new_text,
                change_type=ChangeType.ADDED,
                similarity=0.0,
                keywords=self._extract_keywords(new_text),
            )
        if not new_text:
            return ClauseChange(
                section_id=section_id,
                title=title,
                old_text=old_text,
                change_type=ChangeType.DELETED,
                similarity=0.0,
                keywords=self._extract_keywords(old_text),
            )

        # 计算文本相似度
        similarity = difflib.SequenceMatcher(
            None, old_text, new_text
        ).ratio()

        is_changed = similarity < 0.95  # 相似度低于 95% 视为有变更

        change_type = ChangeType.AMENDED if is_changed else ChangeType.UNCHANGED

        # 生成 HTML 差异
        diff_html = self._generate_html_diff(old_text, new_text)

        # 提取变更关键词
        keywords = self._extract_changed_keywords(old_text, new_text)

        logger.debug(
            f"[TextDiffer] {section_id}: similarity={similarity:.3f}, "
            f"changed={is_changed}, keywords={keywords}"
        )

        return ClauseChange(
            section_id=section_id,
            title=title,
            old_text=old_text,
            new_text=new_text,
            change_type=change_type,
            diff_html=diff_html,
            keywords=keywords,
            similarity=round(similarity, 4),
        )

    def compare_regulation(
        self,
        regulation_name: str,
        sections: List[Dict[str, Any]],
    ) -> DiffResult:
        """
        批量对比法规的所有条款。

        Args:
            regulation_name: 法规名称
            sections: 条款列表 [{section_id, title, old_text, new_text, keywords}]

        Returns:
            DiffResult 完整对比结果
        """
        changes = []
        changed_count = 0

        for sec in sections:
            change = self.compare_clause(
                old_text=sec.get("old_text", ""),
                new_text=sec.get("new_text", ""),
                section_id=sec.get("section_id", ""),
                title=sec.get("title", ""),
            )
            if sec.get("keywords"):
                change.keywords = sec["keywords"]

            if change.change_type != ChangeType.UNCHANGED:
                changed_count += 1

            changes.append(change)

        # 生成摘要
        summary_parts = [
            f"共审查 {len(sections)} 个条款，"
            f"其中 {changed_count} 个条款发生变更。"
        ]

        amended = sum(1 for c in changes if c.change_type == ChangeType.AMENDED)
        added = sum(1 for c in changes if c.change_type == ChangeType.ADDED)
        deleted = sum(1 for c in changes if c.change_type == ChangeType.DELETED)

        if amended:
            summary_parts.append(f"修订 {amended} 条；")
        if added:
            summary_parts.append(f"新增 {added} 条；")
        if deleted:
            summary_parts.append(f"删除 {deleted} 条。")

        # 提取所有变更关键词
        all_keywords = set()
        for c in changes:
            all_keywords.update(c.keywords)

        if all_keywords:
            summary_parts.append(f"变更涉及关键词: {', '.join(sorted(all_keywords)[:10])}")

        result = DiffResult(
            regulation_name=regulation_name,
            total_sections=len(sections),
            changed_sections=changed_count,
            changes=changes,
            summary="".join(summary_parts),
        )

        logger.info(
            f"[TextDiffer] 法规对比完成: {regulation_name} "
            f"({changed_count}/{len(sections)} 条款变更)"
        )
        return result

    def compare_from_mock(
        self,
        change_id: Optional[str] = None,
    ) -> Optional[DiffResult]:
        """
        从 Mock 数据加载法规变更并执行对比。

        Args:
            change_id: 指定变更 ID，为 None 时返回第一个

        Returns:
            DiffResult 或 None
        """
        self._load_mock()

        if not self._mock_changes:
            logger.warning("[TextDiffer] 无 Mock 法规变更数据")
            return None

        # 选择目标变更
        target = self._mock_changes[0]
        if change_id:
            for ch in self._mock_changes:
                if ch["change_id"] == change_id:
                    target = ch
                    break

        # 构建 sections 列表
        sections = []
        for sec in target.get("sections", []):
            sections.append({
                "section_id": sec["section_id"],
                "title": sec["title"],
                "old_text": sec["old_text"],
                "new_text": sec["new_text"],
                "keywords": sec.get("keywords", []),
            })

        # 处理新增条款
        for sec in target.get("new_sections", []):
            sections.append({
                "section_id": sec["section_id"],
                "title": sec["title"],
                "old_text": "",
                "new_text": sec["new_text"],
                "keywords": sec.get("keywords", []),
            })

        # 处理删除条款
        for sec in target.get("deleted_sections", []):
            sections.append({
                "section_id": sec["section_id"],
                "title": sec["title"],
                "old_text": sec.get("old_text", ""),
                "new_text": "",
                "keywords": sec.get("keywords", []),
            })

        return self.compare_regulation(
            regulation_name=target["regulation_name"],
            sections=sections,
        )

    def list_mock_changes(self) -> List[Dict[str, str]]:
        """列出所有可用的 Mock 法规变更。"""
        self._load_mock()
        return [
            {"change_id": ch["change_id"], "regulation_name": ch["regulation_name"], "change_date": ch["change_date"]}
            for ch in self._mock_changes
        ]

    # ---- 内部方法 ----

    def _generate_html_diff(self, old_text: str, new_text: str) -> str:
        """
        生成 HTML 格式的行内差异。

        使用 difflib.HtmlDiff 生成彩色差异对比。

        Args:
            old_text: 旧版本
            new_text: 新版本

        Returns:
            HTML 字符串
        """
        hd = difflib.HtmlDiff(tabsize=4, wrapcolumn=72)
        # 按句子分割以使 diff 更细粒度
        old_lines = self._split_sentences(old_text)
        new_lines = self._split_sentences(new_text)
        return hd.make_table(old_lines, new_lines, context=True, numlines=2)

    def _split_sentences(self, text: str) -> List[str]:
        """将文本按中文句号分割为句子列表。"""
        sentences = re.split(r"(?<=[。！；])", text)
        return [s.strip() for s in sentences if s.strip()]

    def _extract_keywords(self, text: str) -> List[str]:
        """从文本中提取关键词。"""
        # EHS 相关关键词词典
        ehs_keywords = {
            "安全", "隐患", "风险", "事故", "火灾", "爆炸",
            "泄漏", "坠落", "触电", "中毒", "防护", "检测",
            "检查", "巡检", "维护", "保养", "培训", "演练",
            "许可证", "作业票", "审批", "安全带", "安全帽",
            "灭火器", "消防栓", "漏电保护", "通风", "报警",
            "数字化", "电子", "监控", "上传", "平台",
            "报废", "强制", "禁止", "必须", "严禁", "不得",
        }

        found = set()
        for kw in ehs_keywords:
            if kw in text:
                found.add(kw)
        return sorted(found)

    def _extract_changed_keywords(self, old_text: str, new_text: str) -> List[str]:
        """提取新旧文本间的关键词变更。"""
        old_kw = set(self._extract_keywords(old_text))
        new_kw = set(self._extract_keywords(new_text))

        # 新增或删除的关键词
        added = new_kw - old_kw
        removed = old_kw - new_kw

        changed = sorted(added | removed)
        return changed
