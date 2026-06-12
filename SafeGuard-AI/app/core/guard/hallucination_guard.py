"""
零幻觉校验门控

实现技术方案功能 6 的完整三层防线：

    Layer 1 — Pre-LLM Gate（检索置信度门控）:
        检查检索结果置信度是否满足最低阈值，不足则拒答。

    Layer 2 — Prompt Guard（强制引用提示词模板）:
        构建要求每条事实陈述必须附带条款引用的 Prompt，将拒答逻辑
        嵌入到 LLM 的系统指令中。

    Layer 3 — Post-LLM Gate（响应引用校验）:
        验证 LLM 响应中是否包含足够的引用标记，缺失则追加警告。

引用格式标准:
    - 法规引用: 《法规名称》§条款号（如 《企业安全生产标准化基本规范》§5.4.2.3）
    - SOP 引用: [SOP-编号]（如 [SOP-042]）
    - 经验引用: 📎 [引用: 来源描述]
    - 记忆引用: 经验记录 MEM-xxx

设计原则:
    - 所有方法均为同步（无 I/O），不阻塞事件循环
    - 阈值参数化，无硬编码业务规则
    - 中文 Docstring + logging
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# =========================
# 模块级常量
# =========================

# 拒答置信度阈值（PROGRESS.md 功能6 显式定义）
REFUSAL_CONFIDENCE_THRESHOLD = 0.70

# 高置信度引用阈值
HIGH_CITATION_THRESHOLD = 0.80


# =========================
# 引用格式验证器
# =========================


class CitationVerifier:
    """
    验证 LLM 响应中的引用链是否完整、格式是否合规。

    支持的引用格式:
        - 法规引用: 《...》§...  或  依据：《...》
        - SOP 引用:  [SOP-xxx]  或  编号: xxx
        - 条款引用:  条款 x.y.z  或  第x条
        - 通用引用:  📎 [引用: ...]  或  【引用: ...】

    使用方式:
        count = CitationVerifier.count_citations(response)
        citations = CitationVerifier.extract_citations(response)
        is_ok = CitationVerifier.has_minimum_citations(response, min_count=1)
    """

    # 引用模式列表（按优先级排列）
    CITATION_PATTERNS: List[re.Pattern] = [
        # 法规全称引用
        re.compile(r'《[^》]+》\s*§\s*[\d.]+'),
        # 法规简称引用
        re.compile(r'《[^》]+》'),
        # 带标记的引用
        re.compile(r'📎\s*\[引用[：:]\s*([^\]]+)\]'),
        re.compile(r'【引用[：:]\s*([^】]+)】'),
        # 条款号
        re.compile(r'条款\s*[\d.]+'),
        re.compile(r'第\s*[\d零一二三四五六七八九十百千万]+\s*条'),
        # SOP 编号
        re.compile(r'\[SOP\s*[-−—]?\s*\d+\]', re.IGNORECASE),
        # 文档编号
        re.compile(r'编号[：:]\s*\S+'),
        # 依据声明
        re.compile(r'依据[：:]\s*[^。，\n]+'),
    ]

    @classmethod
    def count_citations(cls, text: str) -> int:
        """
        统计文本中不重叠的引用总数。

        Args:
            text: 待检查的文本

        Returns:
            引用数量
        """
        if not text:
            return 0
        count = 0
        for pattern in cls.CITATION_PATTERNS:
            count += len(pattern.findall(text))
        return count

    @classmethod
    def extract_citations(cls, text: str) -> List[str]:
        """
        提取文本中的所有引用字符串。

        Args:
            text: 待检查的文本

        Returns:
            去重后的引用列表
        """
        citations: List[str] = []
        seen: set = set()
        for pattern in cls.CITATION_PATTERNS:
            for match in pattern.finditer(text):
                c = match.group(0).strip()
                if c and c not in seen:
                    seen.add(c)
                    citations.append(c)
        return citations

    @classmethod
    def has_minimum_citations(cls, text: str, min_count: int = 1) -> bool:
        """
        检查是否满足最低引用数量要求。

        Args:
            text: 待检查的文本
            min_count: 最低引用数量

        Returns:
            True 如果引用数量 >= min_count
        """
        return cls.count_citations(text) >= min_count

    @classmethod
    def contains_refusal_markers(cls, text: str) -> bool:
        """
        检查文本是否包含拒答标记。

        拒答关键词:
            - "依据不足"
            - "无法生成"
            - "信息不足"
            - "建议人工核实"
            - "建议人工介入"

        Args:
            text: 待检查的文本

        Returns:
            True 如果包含任一拒答标记
        """
        refusal_keywords = [
            "依据不足", "无法生成", "信息不足",
            "建议人工核实", "建议人工介入", "无法提供",
        ]
        return any(kw in text for kw in refusal_keywords)


# =========================
# 零幻觉校验门控
# =========================


class HallucinationGuard:
    """
    零幻觉校验门控 — 三层防线。

    工作流程:
        1. check_retrieval_gate() → Pre-LLM: 检索置信度门控
        2. build_guarded_prompt() → Prompt: 构建强制引用提示词
        3. verify_response() → Post-LLM: 验证响应引用链
        4. compute_confidence() → 计算综合置信度

    使用示例:
        guard = HallucinationGuard()

        # Layer 1: 检索门控
        can_proceed, reason = guard.check_retrieval_gate(retrieval_results)
        if not can_proceed:
            return {"refusal_reason": reason, "citation_verified": False}

        # Layer 2: 构建 Guarded Prompt
        prompt = guard.build_guarded_prompt(context, query, detection)

        # (调用 LLM...)
        llm_response = await some_llm_call(prompt)

        # Layer 3: 验证响应
        is_valid, issues = guard.verify_response(llm_response, context)
        confidence = guard.compute_confidence(llm_response, retrieval_results)

        if confidence < guard.refusal_threshold:
            llm_response = guard.build_refusal_response(
                f"综合置信度 {confidence:.2f} < {guard.refusal_threshold}"
            )
    """

    def __init__(
        self,
        refusal_threshold: float = REFUSAL_CONFIDENCE_THRESHOLD,
        high_threshold: float = HIGH_CITATION_THRESHOLD,
    ):
        """
        初始化门控。

        Args:
            refusal_threshold: 拒答置信度阈值（默认 0.70）
            high_threshold: 高置信度阈值（默认 0.80）
        """
        self.refusal_threshold = refusal_threshold
        self.high_threshold = high_threshold
        logger.info(
            f"[HallucinationGuard] 初始化: refusal={refusal_threshold}, "
            f"high={high_threshold}"
        )

    # =========================
    # Layer 1: 检索置信度门控 (Pre-LLM)
    # =========================

    def check_retrieval_gate(
        self, retrieval_results: List[Dict[str, Any]]
    ) -> Tuple[bool, str]:
        """
        检索置信度门控（Pre-LLM 第一道防线）。

        规则:
            1. 有 high 置信度结果（score >= 0.80）→ 直接通过
            2. 有 medium 置信度结果且平均分 >= refusal_threshold → 通过（带核实建议）
            3. 仅有 low 或无结果 → 拒答

        Args:
            retrieval_results: GraphRAG 检索结果列表，每项含 score、confidence 字段

        Returns:
            (can_proceed: bool, reason: str)
        """
        if not retrieval_results:
            return False, (
                "检索未返回任何知识依据。"
                "根据零幻觉原则，无法对当前隐患提供有依据的分析。"
            )

        # 分类统计
        high_conf = [r for r in retrieval_results if r.get("confidence") == "high"]
        medium_conf = [r for r in retrieval_results if r.get("confidence") == "medium"]
        low_conf = [r for r in retrieval_results if r.get("confidence") == "low"]

        logger.info(
            f"[Guard:L1] 检索结果分布 — high={len(high_conf)}, "
            f"medium={len(medium_conf)}, low={len(low_conf)}"
        )

        # 规则 1: 有高置信度依据
        if high_conf:
            scores = [r.get("score", 0) for r in high_conf]
            avg = sum(scores) / len(scores)
            return True, (
                f"高置信度依据 {len(high_conf)} 条 (平均分 {avg:.2f})，"
                f"可生成合规分析。"
            )

        # 规则 2: 中置信度依据需满足平均分阈值
        if medium_conf:
            scores = [r.get("score", 0) for r in medium_conf]
            avg_score = sum(scores) / len(scores)
            if avg_score >= self.refusal_threshold:
                return True, (
                    f"中置信度依据 {len(medium_conf)} 条 "
                    f"(平均分 {avg_score:.2f} >= {self.refusal_threshold})，"
                    f"可生成分析但建议人工核实。"
                )
            else:
                return False, (
                    f"中置信度依据平均分 {avg_score:.2f} "
                    f"低于拒答阈值 {self.refusal_threshold}，"
                    f"依据不足，拒绝生成分析。建议人工安全员介入。"
                )

        # 规则 3: 仅有低置信度
        return False, (
            f"仅有 {len(low_conf)} 条低置信度线索，"
            f"依据不足以支撑合规分析。请补充现场信息后重试。"
        )

    # =========================
    # Layer 2: 强制引用 Prompt (Prompt Guard)
    # =========================

    def build_guarded_prompt(
        self,
        context: str,
        query: str,
        detection_result: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        构建强制引用链的 System Prompt（第二道防线）。

        在 Prompt 中嵌入引用规则和拒答逻辑，确保 LLM 在生成层面遵守。

        Args:
            context: GraphRAG 检索到的知识上下文（含置信度标记）
            query: 原始查询文本
            detection_result: 可选的视觉检测结果

        Returns:
            完整的 System Prompt 字符串
        """
        # 构建检测结果摘要（嵌入 Prompt 可减少幻觉）
        detection_text = ""
        if detection_result:
            findings = detection_result.get("findings", [])
            risk_level = detection_result.get("risk_level", "")
            if findings:
                finding_lines = []
                for f in findings:
                    f_type = f.get("type", "未知")
                    f_desc = f.get("description", "")
                    f_conf = f.get("confidence", 0)
                    finding_lines.append(
                        f"  - 类型: {f_type} | 描述: {f_desc} "
                        f"| 视觉置信度: {f_conf:.0%}"
                    )
                detection_text = (
                    f"风险等级: {risk_level}\n"
                    f"检测发现:\n" + "\n".join(finding_lines) + "\n"
                )

        prompt = (
            "你是一个工业安全合规分析引擎（SafeGuard-AI 安卫智脑）。"
            "你的职责是基于检索到的法规/SOP/经验依据，对安全隐患进行合规分析。\n\n"

            "## ⚠️ 强制引用规则（必须严格遵守，违反将导致输出被拒绝）\n\n"

            "### 1. 引用格式要求\n"
            "- 每条事实性陈述**必须**附带引用来源，格式为 `《法规名》§条款号` 或 `[SOP-编号]`\n"
            "- 引用标记示例: `📎 [引用: 《安全生产法》§32.1.2]`\n"
            "- 使用上下文中的 📎 标记来源作为你的引用基础\n\n"

            "### 2. 禁止凭空编造\n"
            "- 只能使用下面「检索依据」中已有的信息\n"
            "- 不得添加未经检索依据支持的建议或法规\n"
            "- 如果依据中缺乏某些信息，必须如实说明\n\n"

            "### 3. 置信度区分使用\n"
            "- ✅ 高置信度依据 → 可直接引用作为主要依据\n"
            "- ⚠️ 中置信度依据 → 可引用但需标注\"建议核实\"\n"
            "- 💡 低置信度依据 → 仅作线索参考，不得作为主要依据\n\n"

            "### 4. 拒答规则\n"
            "- 如果所有「检索依据」仅有 💡 低置信度线索或信息不足，"
            "你的回复必须以\"依据不足，无法生成可靠分析\"开头\n"
            "- 如果关键问题缺乏法规覆盖，需明确说明\n\n"

            f"## 检索依据\n\n{context}\n\n"
            f"## 隐患信息\n\n{detection_text}"
            f"分析任务: {query}\n\n"

            "## 请严格按以下格式输出\n\n"

            "### 1. 法规依据\n"
            "逐条列出适用的法规/标准/规范条款，每条附带 📎 引用标记。\n"
            "若无明确对应的法规条款，请说明。\n\n"

            "### 2. 风险分析\n"
            "基于检索依据分析隐患的严重程度、可能后果和紧急程度。\n"
            "每条判断须标注引用来源。\n\n"

            "### 3. 处置建议\n"
            "基于 SOP/经验给出具体可操作的处置步骤。\n"
            "每条建议须标注对应的 SOP 编号或经验记录。\n\n"

            "### 4. 置信度声明\n"
            "- 整体置信度: [高 / 中 / 低]\n"
            "- 引用来源数量: [N 条]\n"
            "- 是否建议人工复核: [是 / 否]\n"
        )

        return prompt

    # =========================
    # Layer 3: 响应引用校验 (Post-LLM)
    # =========================

    def verify_response(
        self, response: str, context: str
    ) -> Tuple[bool, List[str]]:
        """
        验证 LLM 响应中的引用链完整性（第三道防线）。

        检查项:
            1. 引用数量 >= 1（至少引用一条依据）
            2. 若标记了拒答关键词，视为合法（明确拒绝生成也是一种合规输出）
            3. 孤立引用检测：引用中的核心标识是否在上下文中出现

        Args:
            response: LLM 生成的完整响应文本
            context: 原始检索上下文（用于交叉验证引用来源）

        Returns:
            (is_valid: bool, issues: List[str]) — issues 为空列表表示验证通过
        """
        issues: List[str] = []

        # 检查 1: 是否明确拒答（拒答也是合规输出）
        if CitationVerifier.contains_refusal_markers(response):
            logger.info("[Guard:L3] 响应包含拒答标记，视为合规。")
            return True, []

        # 检查 2: 引用数量
        citation_count = CitationVerifier.count_citations(response)
        if citation_count == 0:
            issues.append(
                "未检测到任何条款引用（需包含至少 1 条 📎 [引用: ...] 标记或条款号）。"
            )
        else:
            logger.info(f"[Guard:L3] 检测到 {citation_count} 条引用。")

        # 检查 3: 置信度声明是否完整
        if "置信度声明" not in response and "整体置信度" not in response:
            issues.append("缺少'置信度声明'段落。")

        # 检查 4: 孤立引用检测（简化：只检查关键法规名）
        citations = CitationVerifier.extract_citations(response)
        orphan_count = 0
        for c in citations:
            # 提取核心标识（去除装饰符）
            core = re.sub(r'[📎【】\[\]]', '', c).strip()
            # 取前 20 个字符作为匹配键
            key = core[:20]
            if key and key not in context and core not in context:
                orphan_count += 1
                if orphan_count <= 3:  # 最多记录 3 条
                    issues.append(f"引用'{c[:50]}'在检索依据中未找到对应来源。")

        is_valid = len(issues) == 0
        if not is_valid:
            logger.warning(
                f"[Guard:L3] 验证未通过: {len(issues)} 个问题 — "
                f"{'; '.join(issues[:2])}"
            )

        return is_valid, issues

    # =========================
    # 综合置信度计算
    # =========================

    def compute_confidence(
        self,
        response: str,
        retrieval_results: List[Dict[str, Any]],
    ) -> float:
        """
        计算 LLM 响应的综合置信度评分。

        综合考虑三个维度:
            - 检索质量 (40%): 检索结果的平均得分
            - 引用密度 (30%): 响应中的引用数量 / 理想引用数
            - 拒答检测 (30%): 是否检测到拒答标记（拒答=0，未拒答=1）

        Args:
            response: LLM 生成的响应
            retrieval_results: 检索结果列表

        Returns:
            综合置信度 0.0-1.0（保留 4 位小数）
        """
        # 维度 1: 检索质量 (0.0-1.0)
        retrieval_scores = [r.get("score", 0) for r in retrieval_results]
        avg_retrieval = (
            sum(retrieval_scores) / len(retrieval_scores)
            if retrieval_scores else 0.0
        )

        # 维度 2: 引用密度 (0.0-1.0)
        # 理想引用数 = 检索结果数，实际引用数 / 理想引用数
        citation_count = CitationVerifier.count_citations(response)
        ideal_count = max(len(retrieval_results), 1)
        citation_density = min(citation_count / ideal_count, 1.0)

        # 维度 3: 拒答检测 (0.0 或 1.0)
        has_refusal = CitationVerifier.contains_refusal_markers(response)
        no_refusal_score = 0.0 if has_refusal else 1.0

        # 加权综合
        confidence = (
            avg_retrieval * 0.4
            + citation_density * 0.3
            + no_refusal_score * 0.3
        )

        logger.info(
            f"[Guard] 综合置信度: {confidence:.4f} "
            f"(检索={avg_retrieval:.2f}×0.4 "
            f"+ 引用密度={citation_density:.2f}×0.3 "
            f"+ 未拒答={no_refusal_score:.0f}×0.3)"
        )

        return round(confidence, 4)

    # =========================
    # 拒答响应构建
    # =========================

    def build_refusal_response(self, reason: str) -> str:
        """
        构建结构化的拒答响应。

        Args:
            reason: 拒答原因

        Returns:
            格式化的拒答响应文本
        """
        return (
            f"## ⚠️ 无法生成合规分析\n\n"
            f"**拒答原因**: {reason}\n\n"
            f"**处理建议**:\n"
            f"1. 请人工安全员到现场核实情况\n"
            f"2. 补充更详细的现场描述或图片后重新提交\n"
            f"3. 查阅最新的法规标准和 SOP 手册\n\n"
            f"---\n"
            f"*此响应由 SafeGuard-AI 零幻觉校验模块自动生成。*\n"
            f"*拒绝生成不准确的合规分析比生成错误建议更安全。*\n"
        )

    def augment_with_warning(self, response: str, issues: List[str]) -> str:
        """
        为验证未通过的响应追加警告信息。

        Args:
            response: 原始 LLM 响应
            issues: 验证发现的问题列表

        Returns:
            追加了警告段的响应文本
        """
        warning_lines = [
            "\n\n---\n",
            "## ⚠️ 零幻觉校验警告\n\n",
            "以下问题在自动校验中被发现，但不影响答复生成：\n\n",
        ]
        for i, issue in enumerate(issues, 1):
            warning_lines.append(f"{i}. {issue}\n")
        warning_lines.append(
            "\n*建议人工复核以上问题后再采纳本分析结果。*\n"
        )
        return response + "".join(warning_lines)


# =========================
# Mock LLM 响应生成（开发/测试阶段）
# =========================


def generate_mock_llm_response(
    context: str,
    query: str,
    detection_result: Optional[Dict[str, Any]] = None,
) -> str:
    """
    生成 Mock LLM 分析响应（用于 API Key 未配置时的降级）。

    根据检索上下文中的置信度标记返回不同的响应模式：
        - 有高/中置信度依据 → 生成带有引用的合规分析
        - 仅有低置信度 → 生成拒答响应

    Args:
        context: 检索上下文
        query: 查询文本
        detection_result: 可选的检测结果

    Returns:
        模拟的 LLM 响应文本
    """
    # 检测上下文中的置信度标记
    has_high = "✅" in context or "高置信度依据" in context
    has_medium = "⚠️" in context or "中置信度参考" in context
    has_only_low = (
        not has_high
        and not has_medium
        and ("💡" in context or "低置信度线索" in context)
    )

    # 提取上下文中的引用用于 Mock 响应
    citations_in_context: List[str] = []
    for line in context.split("\n"):
        if "📎" in line:
            # 提取引用标记内容
            match = re.search(r'📎\s*\[引用[：:]\s*([^\]]+)\]', line)
            if match:
                citations_in_context.append(match.group(0))

    # 若无引用标记，尝试从文本中提取法规名
    if not citations_in_context:
        for match in re.finditer(r'《[^》]+》', context):
            citations_in_context.append(f"📎 [引用: {match.group(0)}]")

    detection_text = ""
    if detection_result:
        findings = detection_result.get("findings", [])
        risk_level = detection_result.get("risk_level", "")
        if findings:
            finding_lines = []
            for f in findings:
                f_type = f.get("type", "未知")
                f_desc = f.get("description", "")
                finding_lines.append(f"  - {f_type}: {f_desc}")
            detection_text = (
                f"风险等级: {risk_level}\n"
                f"检测发现:\n" + "\n".join(finding_lines)
            )

    # 拒答场景：仅有低置信度
    if has_only_low or (not has_high and not has_medium and not citations_in_context):
        return (
            "依据不足，无法生成可靠分析\n\n"
            "### 1. 法规依据\n"
            "当前检索依据中未找到可引用的法规条款或 SOP。\n\n"
            "### 2. 风险分析\n"
            "由于缺乏法规依据，无法进行基于标准的风险评估。"
            f"检测到的隐患: {query[:100]}\n\n"
            "### 3. 处置建议\n"
            "建议人工安全员到现场核实情况。\n\n"
            "### 4. 置信度声明\n"
            "- 整体置信度: 低\n"
            "- 引用来源数量: 0 条\n"
            "- 是否建议人工复核: 是（强烈建议）\n"
        )

    # 正常场景：生成带引用的 Mock 响应
    cite_list = "\n".join(
        f"  - {c}" for c in citations_in_context[:3]
    ) if citations_in_context else "  - (暂无引用标记)"

    return (
        f"### 1. 法规依据\n\n"
        f"根据 GraphRAG 检索结果，以下法规条款适用于当前隐患：\n\n"
        f"{cite_list}\n\n"
        f"**补充说明**: 以上法规条款均来自检索到的知识依据，"
        f"已通过零幻觉校验模块的引用链验证。\n\n"
        f"### 2. 风险分析\n\n"
        f"基于上述法规依据，对'{query[:80]}'进行分析：\n\n"
        f"- 风险评估: 该隐患属于工业生产中常见的安全风险类型。\n"
        f"{'  ' + cite_list.split(chr(10))[0] if citations_in_context else ''}\n"
        f"- 可能后果: 若未及时处置，可能导致安全事故。\n\n"
        f"### 3. 处置建议\n\n"
        f"根据检索到的 SOP 和经验记忆，建议以下处置措施：\n"
        f"1. 立即通知现场安全员进行核实和处理\n"
        f"2. 根据相应 SOP 启动隐患整改流程\n"
        f"3. 处置完成后拍照留档，更新工单状态\n\n"
        f"### 4. 置信度声明\n"
        f"- 整体置信度: {'高' if has_high else '中'}\n"
        f"- 引用来源数量: {len(citations_in_context)} 条\n"
        f"- 是否建议人工复核: {'否（高置信度可采信）' if has_high else '是（中置信度建议核实）'}\n"
        f"- 校验模块: SafeGuard-AI 零幻觉校验 v1.0\n"
    )
