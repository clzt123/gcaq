"""
Phase 4: SFT 微调训练数据导出脚本
==================================
从 Mock 反馈日志 + 隐患检测结果中提取结构化训练数据，
导出为 JSONL 格式，兼容 OpenAI/LlamaFactory 微调流水线。

数据格式 (JSONL):
    {"messages": [
        {"role": "system", "content": "你是工业安全巡检AI..."},
        {"role": "user",   "content": "图片描述/检测结果..."},
        {"role": "assistant", "content": "正确的隐患研判..."}
    ], "metadata": {"source": "...", "feedback_type": "..."}}

用法:
    python scripts/export_training_data.py                  # 导出全部
    python scripts/export_training_data.py --output sft_v2.jsonl
    python scripts/export_training_data.py --split 80 10 10  # 训练/验证/测试分割
    python scripts/export_training_data.py --stats-only      # 仅查看统计
"""
import argparse
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# Windows GBK 终端兼容
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_OUTPUT = _PROJECT_ROOT / "data" / "sft_training_data.jsonl"

# ── System Prompt ─────────────────────────────────────
SYSTEM_PROMPT = (
    "你是工业安全生产巡检AI（安卫智脑 SafeGuard-AI），"
    "负责对工厂监控画面进行隐患研判。你需要：\n"
    "1. 识别图片中的安全隐患类型（油渍泄漏、消防通道堵塞、未戴安全帽、化学品烟雾等）\n"
    "2. 评估风险等级（high/medium/low/none）\n"
    "3. 生成具体的处置建议，引用相关法规条款\n"
    "4. 标注隐患区域和置信度\n\n"
    "回答格式：JSON {\"risk_level\":\"...\", \"findings\":[{...}], \"recommendation\":\"...\"}"
)

# ── Mock 反馈数据（模拟生产环境积累的驳回案例） ────────
MOCK_FEEDBACK_LOG = [
    # (image_desc, original_prediction, human_correction, feedback_type)
    (
        "注塑机旁地面有反光水渍，实际是冷却水而非油渍",
        {"risk_level": "high", "type": "oil_leak", "confidence": 0.91},
        {"risk_level": "low", "type": "water_spill", "note": "冷却水溅出，非油渍，无需紧急处置"},
        "false_positive",
    ),
    (
        "员工蹲在设备后方检修，被误判为违规闯入",
        {"risk_level": "high", "type": "unauthorized_entry", "confidence": 0.88},
        {"risk_level": "none", "type": "maintenance_work", "note": "检修工正在执行计划维保，已提前报备"},
        "false_positive",
    ),
    (
        "仓库角落堆放空托盘，被误判为消防通道堵塞",
        {"risk_level": "medium", "type": "blocked_exit", "confidence": 0.85},
        {"risk_level": "low", "type": "temporary_storage", "note": "空托盘临时存放，距消防门>3m，不构成堵塞"},
        "false_positive",
    ),
    (
        "新员工安全帽颜色为蓝色（管理人员色），被误判为未戴安全帽",
        {"risk_level": "high", "type": "no_hardhat", "confidence": 0.82},
        {"risk_level": "none", "type": "false_alarm", "note": "蓝色安全帽为管理人员标配，需更新模型颜色识别"},
        "false_positive",
    ),
    (
        "焊接工位烟雾弥漫但实际是正常的焊接烟尘，非火灾",
        {"risk_level": "high", "type": "fire_smoke", "confidence": 0.89},
        {"risk_level": "medium", "type": "welding_fume", "note": "焊接烟尘正常产生，需确认排风系统运行状态"},
        "irrelevant",
    ),
]

# ── 正面样本（正确研判） ─────────────────────────────
MOCK_CORRECT_PREDICTIONS = [
    (
        "注塑机液压管路下方大片油渍，未放置防漏托盘",
        {"risk_level": "high", "type": "oil_leak", "confidence": 0.93},
    ),
    (
        "消防通道被3个纸箱和1台叉车完全堵塞",
        {"risk_level": "high", "type": "blocked_exit", "confidence": 0.91},
    ),
    (
        "焊接工位操作员未佩戴安全帽，周边有明火作业",
        {"risk_level": "high", "type": "no_hardhat", "confidence": 0.88},
    ),
    (
        "化学品仓库检测到烟雾浓度异常升高，疑似初期火灾",
        {"risk_level": "high", "type": "fire_smoke", "confidence": 0.97},
    ),
]


# ── 核心逻辑 ──────────────────────────────────────────

def build_negative_example(
    image_desc: str,
    original: Dict[str, Any],
    correction: Dict[str, Any],
) -> Dict[str, Any]:
    """
    构建负样本（驳回案例）训练数据。

    User 端给出原始误判的描述，Assistant 端给出人工修正的正确答案。
    """
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"【图片描述】{image_desc}\n"
                    f"请分析图片中的安全隐患并给出处置建议。"
                ),
            },
            {
                "role": "assistant",
                "content": json.dumps(correction, ensure_ascii=False),
            },
        ],
        "metadata": {
            "source": "human_correction",
            "original_type": original.get("type"),
            "original_confidence": original.get("confidence"),
            "correction_type": correction.get("type"),
            "is_negative_sample": True,
        },
    }


def build_positive_example(
    image_desc: str,
    prediction: Dict[str, Any],
) -> Dict[str, Any]:
    """
    构建正样本（正确研判）训练数据。
    """
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"【图片描述】{image_desc}\n"
                    f"请分析图片中的安全隐患并给出处置建议。"
                ),
            },
            {
                "role": "assistant",
                "content": json.dumps(prediction, ensure_ascii=False),
            },
        ],
        "metadata": {
            "source": "correct_prediction",
            "prediction_type": prediction.get("type"),
            "confidence": prediction.get("confidence"),
            "is_negative_sample": False,
        },
    }


def generate_dataset() -> List[Dict[str, Any]]:
    """生成完整训练数据集（Mock 模式）。"""
    data = []

    # 负样本（人工修正）—— 高价值
    for image_desc, original, correction, fb_type in MOCK_FEEDBACK_LOG:
        example = build_negative_example(image_desc, original, correction)
        example["metadata"]["feedback_type"] = fb_type
        data.append(example)

    # 正样本（正确研判）
    for image_desc, prediction in MOCK_CORRECT_PREDICTIONS:
        data.append(build_positive_example(image_desc, prediction))

    return data


def split_dataset(
    data: List[Dict[str, Any]],
    train_pct: int, valid_pct: int, test_pct: int,
    seed: int = 42,
) -> Tuple[List, List, List]:
    """随机分割数据集为训练/验证/测试。"""
    random.seed(seed)
    shuffled = data[:]
    random.shuffle(shuffled)

    n = len(shuffled)
    train_end = int(n * train_pct / 100)
    valid_end = train_end + int(n * valid_pct / 100)

    return (
        shuffled[:train_end],
        shuffled[train_end:valid_end],
        shuffled[valid_end:],
    )


def save_jsonl(data: List[Dict[str, Any]], path: Path):
    """保存为 JSONL 格式。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def print_stats(data: List[Dict[str, Any]]):
    """打印数据集统计信息。"""
    total = len(data)
    neg = sum(1 for d in data if d["metadata"].get("is_negative_sample"))
    pos = total - neg

    fb_types = {}
    for d in data:
        ft = d["metadata"].get("feedback_type", "correct")
        fb_types[ft] = fb_types.get(ft, 0) + 1

    print(f"📊 数据集统计:")
    print(f"   总数: {total} 条")
    print(f"   正样本 (正确研判): {pos} 条 ({pos/total*100:.0f}%)")
    print(f"   负样本 (人工修正): {neg} 条 ({neg/total*100:.0f}%)")
    print(f"   反馈类型分布: {json.dumps(fb_types, ensure_ascii=False)}")


# ── CLI ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SafeGuard-AI SFT 训练数据导出")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出文件路径")
    parser.add_argument("--split", nargs=3, type=int, metavar=("TRAIN", "VALID", "TEST"),
                        help="训练/验证/测试分割比例 (如: 80 10 10)")
    parser.add_argument("--stats-only", action="store_true", help="仅打印统计")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    print("=" * 60)
    print("  🏭 SafeGuard-AI SFT 训练数据导出")
    print("=" * 60)
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 生成数据
    data = generate_dataset()
    print_stats(data)

    if args.stats_only:
        return

    out = Path(args.output)

    if args.split:
        train_pct, valid_pct, test_pct = args.split
        if train_pct + valid_pct + test_pct != 100:
            print("❌ 分割比例之和必须为 100")
            sys.exit(1)

        train, valid, test = split_dataset(data, train_pct, valid_pct, test_pct, args.seed)

        base = out.stem
        ext = out.suffix
        parent = out.parent

        train_path = parent / f"{base}_train{ext}"
        valid_path = parent / f"{base}_valid{ext}"
        test_path = parent / f"{base}_test{ext}"

        save_jsonl(train, train_path)
        save_jsonl(valid, valid_path)
        save_jsonl(test, test_path)

        print(f"\n✅ 已导出分割数据集:")
        print(f"   训练集: {train_path} ({len(train)} 条)")
        print(f"   验证集: {valid_path} ({len(valid)} 条)")
        print(f"   测试集: {test_path} ({len(test)} 条)")
    else:
        save_jsonl(data, out)
        print(f"\n✅ 已导出: {out} ({len(data)} 条)")

    print(f"\n📋 微调命令示例 (LlamaFactory):")
    print(f"   llamafactory-cli train \\")
    print(f"     --model_name_or_path Qwen/Qwen2-VL-7B \\")
    print(f"     --dataset {out.name} \\")
    print(f"     --output_dir ./output/safeguard-sft-v1")


if __name__ == "__main__":
    main()
