"""
Qwen-VL 视觉分析器

提供异步隐患图像识别能力，基于阿里云 DashScope Qwen-VL 模型。
支持三种图片输入格式：URL、Base64 data URI、本地文件路径。

设计原则:
    - async/await 优先
    - 使用 logging（禁止 print）
    - 优雅降级：API 调用失败返回标准 error 结构
    - 中文 Docstring
"""
import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# =========================
# 安全检测 Prompt 模板
# =========================

DEFAULT_SAFETY_PROMPT = """你是一个工业安全巡检员。请仔细分析这张图片，识别所有安全隐患。

请检查以下类别：
- no_hardhat: 未佩戴安全帽
- no_safety_vest: 未穿反光衣/安全背心
- smoking: 吸烟或使用明火
- using_phone: 工作中玩手机
- unauthorized_entry: 违规闯入危险区域
- oil_leak: 油渍/化学品泄漏
- fire_smoke: 烟雾/火情
- blocked_exit: 消防通道堵塞
- unsafe_behavior: 其他不安全行为
- unclear: 图像模糊无法判断

请严格按以下JSON格式返回（不要包含markdown代码块标记```json）：
{
  "risk_level": "high",
  "findings": [
    {
      "type": "类别代码",
      "description": "中文描述（含位置和严重程度）",
      "confidence": 0.92,
      "bbox": [x1, y1, x2, y2]
    }
  ]
}

规则：
1. risk_level: 任一 finding 含 high 风险行为(如烟雾/明火/泄漏/闯入)则 "high"；仅中等违规(安全帽/反光衣/玩手机)则 "medium"；仅轻微或无隐患则 "low"；无任何隐患则 "none"。
2. confidence: 0.0 到 1.0，表示你对判断的确信程度。
3. bbox: 隐患区域的大致边界框 [x1, y1, x2, y2]（绝对像素坐标），若无法确定则用 []。
4. 若无隐患，findings 返回空数组，risk_level 为 "none"。
"""

# =========================
# 响应解析
# =========================


def _parse_qwen_response(raw_text: str) -> Dict[str, Any]:
    """
    解析 Qwen-VL 返回的 JSON 文本，提取标准 detection_result 结构。

    处理常见问题：
        - 模型输出包裹在 ```json ... ``` 中
        - 模型输出含有额外文字说明
        - JSON 中缺少部分字段

    Args:
        raw_text: Qwen-VL 返回的原始文本

    Returns:
        标准 detection_result 字典

    Raises:
        ValueError: JSON 解析失败且无法修复
    """
    text = raw_text.strip()

    # 1. 尝试移除 markdown 代码块标记
    if "```" in text:
        # 提取 ```json ... ``` 中的内容
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    # 2. 尝试找到第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    # 3. 解析 JSON
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 尝试修复：替换单引号为双引号
        try:
            text_fixed = text.replace("'", '"')
            data = json.loads(text_fixed)
        except json.JSONDecodeError as e:
            raise ValueError(f"无法解析 Qwen-VL 响应 JSON: {raw_text[:200]}...") from e

    # 4. 校验与补全字段
    if not isinstance(data, dict):
        raise ValueError(f"Qwen-VL 响应不是 JSON 对象: {type(data)}")

    risk_level = data.get("risk_level", "none")
    if risk_level not in ("high", "medium", "low", "none"):
        risk_level = "low"  # 未知等级默认 low

    findings: List[Dict[str, Any]] = data.get("findings", [])
    if not isinstance(findings, list):
        findings = []

    normalized_findings = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        normalized: Dict[str, Any] = {
            "type": f.get("type", "unknown"),
            "description": f.get("description", str(f)),
            "confidence": float(f.get("confidence", 0.5)),
            "bbox": f.get("bbox", []),
        }
        # 确保 bbox 是列表
        if not isinstance(normalized["bbox"], list):
            normalized["bbox"] = []
        normalized_findings.append(normalized)

    return {
        "risk_level": risk_level,
        "findings": normalized_findings,
        "raw_response": raw_text[:500],
    }


# =========================
# 图片输入处理
# =========================


def _prepare_image_content(image_source: str) -> str:
    """
    处理图片输入，统一为 dashscope SDK 支持的格式。

    自动检测三种格式：
        - http(s):// → 直接返回 URL
        - data:image/... → 直接返回 base64 data URI
        - 其他 → 本地文件路径，读取并转为 base64 data URI

    Args:
        image_source: 图片来源（URL、base64 data URI 或本地路径）

    Returns:
        dashscope SDK 支持的图片字符串

    Raises:
        FileNotFoundError: 本地文件不存在
    """
    # URL 格式：直接返回
    if image_source.startswith("http://") or image_source.startswith("https://"):
        logger.debug(f"[Vision] 使用 URL: {image_source[:60]}...")
        return image_source

    # Base64 data URI：直接返回
    if image_source.startswith("data:"):
        logger.debug("[Vision] 使用 Base64 data URI")
        return image_source

    # 本地文件路径：读取并转为 base64
    filepath = Path(image_source)
    if not filepath.exists():
        raise FileNotFoundError(f"图片文件不存在: {image_source}")

    suffix = filepath.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }
    mime_type = mime_map.get(suffix, "image/jpeg")

    with open(filepath, "rb") as f:
        image_bytes = f.read()

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_uri = f"data:{mime_type};base64,{b64}"
    logger.debug(f"[Vision] 文件转 Base64: {filepath} ({len(image_bytes)} bytes)")
    return data_uri


# =========================
# 核心: Qwen-VL API 调用
# =========================


async def analyze_image_with_qwen(
    image_source: str,
    prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用 Qwen-VL 分析工业安全图片，识别隐患。

    支持三种图片输入：HTTP URL、Base64 data URI、本地文件路径。

    Args:
        image_source: 图片来源（URL / data URI / 本地路径）
        prompt: 自定义分析 Prompt，None 时使用默认安全检测 Prompt

    Returns:
        标准 detection_result 字典:
            {
                "risk_level": "high" | "medium" | "low" | "none",
                "findings": [
                    {
                        "type": "no_hardhat" | "smoking" | ...,
                        "description": "中文描述",
                        "confidence": 0.0-1.0,
                        "bbox": [x1, y1, x2, y2] | []
                    }
                ],
                "raw_response": "原始响应摘要"
            }

    Raises:
        不抛出异常——所有错误统一返回 error 结构
    """
    settings = get_settings()
    api_key = settings.dashscope.api_key
    model = settings.dashscope.vl_model
    timeout = settings.dashscope.vl_timeout

    # 检查 API Key 是否已配置
    if not api_key or api_key.startswith("your-"):
        logger.warning(
            "[Vision] DashScope API Key 未配置，将使用 Mock 降级。"
            "请在 .env 中设置 DASHSCOPE_API_KEY。"
        )
        return _mock_analysis(image_source)

    # 准备图片
    try:
        image_content = _prepare_image_content(image_source)
    except (FileNotFoundError, PermissionError) as e:
        logger.warning(
            f"[Vision] 图片不可用 ({e})，降级为 Mock 关键词匹配"
        )
        return _mock_analysis(image_source)

    # 构建消息
    safety_prompt = prompt or DEFAULT_SAFETY_PROMPT
    messages = [
        {
            "role": "user",
            "content": [
                {"image": image_content},
                {"text": safety_prompt},
            ],
        }
    ]

    logger.info(f"[Vision] 调用 Qwen-VL: model={model}, image={image_source[:60]}...")

    try:
        import dashscope
        from dashscope import AioMultiModalConversation

        dashscope.api_key = api_key

        response = await AioMultiModalConversation.call(
            model=model,
            messages=messages,
            stream=False,
        )

        if response.status_code != 200:
            error_msg = (
                f"DashScope API 返回错误: code={response.code}, "
                f"message={response.message}"
            )
            logger.error(f"[Vision] {error_msg}")
            return {
                "risk_level": "none",
                "findings": [],
                "error": error_msg,
                "raw_response": f"API 错误 [{response.code}]: {response.message}",
            }

        # 提取文本内容
        output = response.output
        if not output or not output.choices:
            logger.warning("[Vision] Qwen-VL 返回空的 choices")
            return {
                "risk_level": "none",
                "findings": [],
                "error": "API 返回空结果",
                "raw_response": "Qwen-VL: 无输出",
            }

        raw_text = output.choices[0].message.content[0]["text"]

        # 记录用量（兼容 dashscope SDK 新旧版本）
        try:
            if output.get("usage"):
                usage = output["usage"]
                logger.info(
                    f"[Vision] 用量: input={usage.get('input_tokens', '?')}, "
                    f"output={usage.get('output_tokens', '?')}"
                )
        except (KeyError, AttributeError, TypeError):
            pass  # 新版 SDK 无 usage 字段时不记录

    except ImportError:
        logger.warning("[Vision] dashscope 未安装，使用 Mock 降级")
        return _mock_analysis(image_source)

    except Exception as e:
        logger.error(f"[Vision] Qwen-VL 调用异常: {e}", exc_info=True)
        return {
            "risk_level": "none",
            "findings": [],
            "error": f"API 调用异常: {str(e)}",
            "raw_response": f"Qwen-VL 调用失败: {e}",
        }

    # 解析响应
    try:
        result = _parse_qwen_response(raw_text)
        logger.info(
            f"[Vision] 分析完成: risk_level={result['risk_level']}, "
            f"findings={len(result['findings'])} 个"
        )
        return result
    except ValueError as e:
        logger.error(f"[Vision] 响应解析失败: {e}")
        return {
            "risk_level": "low",
            "findings": [
                {
                    "type": "unclear",
                    "description": f"模型返回格式异常，原始内容: {raw_text[:200]}",
                    "confidence": 0.3,
                    "bbox": [],
                }
            ],
            "raw_response": raw_text[:500],
        }


# =========================
# Mock 降级（API Key 未配置 / dashscope 未安装时使用）
# =========================


def _mock_analysis(image_source: str) -> Dict[str, Any]:
    """
    Mock 视觉分析——当 DashScope 不可用时降级使用。

    保留原有关键词匹配逻辑作为兜底方案。

    Args:
        image_source: 图片路径/URL

    Returns:
        标准 detection_result 字典
    """
    image_lower = image_source.lower()

    # 关键词 → (risk_level, type, description, confidence)
    keyword_rules = [
        (["leak", "油", "泄漏"], "high", "oil_leak",
         "检测到液压管路下方有明显油渍，未放置防漏托盘", 0.93),
        (["smoke", "chemical", "烟"], "high", "fire_smoke",
         "检测到烟雾浓度异常升高，疑似初期火灾", 0.97),
        (["helmet", "安全帽", "焊接"], "high", "no_hardhat",
         "焊接工位操作人员未佩戴安全帽", 0.88),
        (["blocked", "通道", "堵塞"], "medium", "blocked_exit",
         "消防通道被纸箱和叉车堵塞", 0.91),
        (["vest", "反光衣", "背心"], "medium", "no_safety_vest",
         "作业人员未穿戴反光安全背心", 0.85),
        (["smok", "吸烟", "香烟", "打火机"], "high", "smoking",
         "检测到人员在禁烟区域吸烟", 0.90),
        (["phone", "手机", "玩手机"], "medium", "using_phone",
         "操作员在工作期间使用手机", 0.82),
        (["intrud", "闯入", "禁区", "越界", "非法进入"], "high", "unauthorized_entry",
         "检测到人员违规闯入危险区域", 0.92),
    ]

    for keywords, risk, htype, desc, conf in keyword_rules:
        if any(kw in image_lower for kw in keywords):
            logger.info(f"[Vision Mock] 关键词匹配: {htype}, risk={risk}")
            return {
                "risk_level": risk,
                "findings": [{
                    "type": htype,
                    "description": desc,
                    "confidence": conf,
                    "bbox": [120, 100, 480, 400],
                }],
                "raw_response": f"[Mock] 关键词匹配: {htype} (置信度 {conf})",
            }

    # 无法匹配
    logger.info("[Vision Mock] 未匹配任何已知隐患类型")
    return {
        "risk_level": "low",
        "findings": [{
            "type": "unclear",
            "description": "图像模糊或无法确定隐患类型，建议人工复核",
            "confidence": 0.30,
            "bbox": [],
        }],
        "raw_response": "[Mock] 无法确定隐患类型",
    }
