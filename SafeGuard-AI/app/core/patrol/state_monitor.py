"""
状态变化检测器

识别工业安全场景中的典型状态变化模式：
    - "由通变堵" (CLEAR_TO_BLOCKED): 通道/出口被物体堵塞
    - "由在变无" (PRESENT_TO_ABSENT): 安全设备/标识消失
    - "由无变有" (ABSENT_TO_PRESENT): 新物体/隐患出现

基于图像差异检测结果，结合区域类型和相机位置，
推断具体的变化类型并生成巡检告警。

使用方式:
    detector = StateChangeDetector()
    change = detector.classify(
        camera_id="CAM_FIRE_EXIT_01",
        diff_result={"has_changed": True, "change_level": "significant"},
        area_type="warehouse",
    )
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ChangeType(str, Enum):
    """状态变化类型"""
    CLEAR_TO_BLOCKED = "clear_to_blocked"        # 由通变堵
    PRESENT_TO_ABSENT = "present_to_absent"       # 由在变无
    ABSENT_TO_PRESENT = "absent_to_present"       # 由无变有
    UNKNOWN_CHANGE = "unknown_change"             # 不明变化
    NO_CHANGE = "no_change"                       # 无变化
    LIGHTING_CHANGE = "lighting_change"           # 仅光照变化（低置信度）


# 变化类型中文标签
CHANGE_TYPE_LABELS: Dict[ChangeType, str] = {
    ChangeType.CLEAR_TO_BLOCKED: "通道堵塞（由通变堵）",
    ChangeType.PRESENT_TO_ABSENT: "安全设施缺失（由在变无）",
    ChangeType.ABSENT_TO_PRESENT: "异物/新隐患出现（由无变有）",
    ChangeType.UNKNOWN_CHANGE: "不明状态变化",
    ChangeType.NO_CHANGE: "无变化",
    ChangeType.LIGHTING_CHANGE: "疑似光照变化",
}

# 变化严重程度
CHANGE_SEVERITY: Dict[ChangeType, str] = {
    ChangeType.CLEAR_TO_BLOCKED: "high",
    ChangeType.PRESENT_TO_ABSENT: "high",
    ChangeType.ABSENT_TO_PRESENT: "medium",
    ChangeType.UNKNOWN_CHANGE: "medium",
    ChangeType.NO_CHANGE: "none",
    ChangeType.LIGHTING_CHANGE: "low",
}


@dataclass
class PatrolAlert:
    """
    巡检告警。

    Attributes:
        alert_id: 告警 ID
        camera_id: 相机标识
        change_type: 变化类型
        severity: 严重程度 (high/medium/low/none)
        description: 告警描述
        diff_distance: 图像差异汉明距离
        similarity: 图像相似度
        suggested_action: 建议处置措施
        metadata: 额外元数据
    """
    alert_id: str
    camera_id: str
    change_type: ChangeType
    severity: str
    description: str
    diff_distance: int = 0
    similarity: float = 1.0
    suggested_action: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class StateChangeDetector:
    """
    状态变化分类器。

    根据区域类型、变化幅度和相机位置推断具体的状态变化类型。

    分类规则:
        - 逃生通道/消防通道 + 显著变化 → 由通变堵
        - 设备区/危化品区 + 显著变化 → 由在变无（设备/设施缺失）
        - 任何区域 + 显著变化 + 无历史事故匹配 → 由无变有（新物体）
        - 轻微变化 + 无特定模式 → 光照变化

    使用方式:
        detector = StateChangeDetector()
        alert = detector.classify(
            camera_id="CAM_FIRE_EXIT_01",
            diff_result={"has_changed": True, "change_level": "significant"},
            area_type="warehouse",
        )
        if alert.severity != "none":
            # 触发隐患研判工作流
            pass
    """

    def classify(
        self,
        camera_id: str,
        diff_result: dict,
        area_type: str = "",
        camera_position: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PatrolAlert:
        """
        对图像差异进行状态变化分类。

        Args:
            camera_id: 相机标识
            diff_result: ImageDiffer.compare() 的返回结果
            area_type: 区域类型 (production/rest/hazard/warehouse/corridor/exit)
            camera_position: 相机位置描述
            metadata: 额外元数据

        Returns:
            PatrolAlert 告警对象
        """
        has_changed = diff_result.get("has_changed", False)
        change_level = diff_result.get("change_level", "none")
        distance = diff_result.get("distance", 0)
        similarity = diff_result.get("similarity", 1.0)

        if not has_changed:
            return PatrolAlert(
                alert_id=f"PATROL_{camera_id}_NOCHANGE",
                camera_id=camera_id,
                change_type=ChangeType.NO_CHANGE,
                severity="none",
                description="巡检正常，未检测到变化。",
                diff_distance=distance,
                similarity=similarity,
                metadata=metadata or {},
            )

        # 根据区域类型和变化等级推断变化类型
        change_type = self._infer_change_type(
            area_type, change_level, distance, camera_position
        )

        # 生成告警描述和建议
        description = self._build_description(
            change_type, camera_id, camera_position, area_type
        )
        suggested_action = self._suggest_action(change_type, area_type)
        severity = CHANGE_SEVERITY.get(change_type, "medium")

        alert = PatrolAlert(
            alert_id=f"PATROL_{camera_id}_{change_type.value}",
            camera_id=camera_id,
            change_type=change_type,
            severity=severity,
            description=description,
            diff_distance=distance,
            similarity=similarity,
            suggested_action=suggested_action,
            metadata=metadata or {},
        )

        logger.info(
            f"[StateMonitor] 巡检告警: camera={camera_id}, "
            f"type={change_type.value}, severity={severity}, "
            f"distance={distance}"
        )

        return alert

    def _infer_change_type(
        self,
        area_type: str,
        change_level: str,
        distance: int,
        camera_position: str,
    ) -> ChangeType:
        """
        推断状态变化类型。

        推理规则（优先级从高到低）:
            1. 出口/通道/走廊 + 显著变化 → 由通变堵
            2. 危险品区/生产区 + 显著变化 → 由在变无（设备缺失）
            3. 显著变化 + 未知区域 → 由无变有
            4. 轻微变化 → 光照变化
        """
        # 规则 1: 通道类区域
        passage_keywords = ["exit", "通道", "出口", "corridor", "走廊", "消防", "fire"]
        is_passage = any(
            kw in (area_type + camera_position).lower()
            for kw in passage_keywords
        )
        if is_passage and change_level == "significant":
            return ChangeType.CLEAR_TO_BLOCKED

        # 规则 2: 危险品/生产/设备区域
        equipment_keywords = ["production", "hazard", "生产", "危险", "设备", "equipment"]
        is_equipment_area = any(
            kw in (area_type + camera_position).lower()
            for kw in equipment_keywords
        )
        if is_equipment_area and change_level == "significant":
            return ChangeType.PRESENT_TO_ABSENT

        # 规则 3: 显著变化但非特定区域 → 新物体出现
        if change_level == "significant":
            return ChangeType.ABSENT_TO_PRESENT

        # 规则 4: 轻微变化 → 光照
        if change_level == "minor":
            return ChangeType.LIGHTING_CHANGE

        return ChangeType.UNKNOWN_CHANGE

    def _build_description(
        self,
        change_type: ChangeType,
        camera_id: str,
        camera_position: str,
        area_type: str,
    ) -> str:
        """生成告警描述。"""
        label = CHANGE_TYPE_LABELS.get(change_type, "不明变化")
        pos = f"({camera_position})" if camera_position else ""
        area = f"【{area_type}】" if area_type else ""

        descriptions = {
            ChangeType.CLEAR_TO_BLOCKED:
                f"数字巡检员检测到{area}通道状态异常{pos}：疑似消防通道/安全出口被堵塞。"
                f"请立即派安全员到 {camera_id} {pos} 核实。",
            ChangeType.PRESENT_TO_ABSENT:
                f"数字巡检员检测到{area}安全设施/设备状态异常{pos}："
                f"疑似安全设备被移除或损坏。请到 {camera_id} {pos} 确认。",
            ChangeType.ABSENT_TO_PRESENT:
                f"数字巡检员检测到{area}出现新的不明物体或隐患{pos}。"
                f"请在 {camera_id} {pos} 进行现场识别。",
            ChangeType.LIGHTING_CHANGE:
                f"数字巡检员检测到{area}轻微变化{pos}，疑似光照条件变化。"
                f"建议人工确认 {camera_id} 是否存在异常。",
            ChangeType.UNKNOWN_CHANGE:
                f"数字巡检员检测到{area}不明状态变化{pos}。"
                f"建议人工巡检 {camera_id}。",
            ChangeType.NO_CHANGE:
                f"{area} {camera_id} {pos} 巡检正常。",
        }

        return descriptions.get(change_type, f"{label}: {camera_id} {pos}")

    def _suggest_action(self, change_type: ChangeType, area_type: str) -> str:
        """生成建议处置措施。"""
        actions = {
            ChangeType.CLEAR_TO_BLOCKED:
                "1. 现场核实堵塞物归属\n"
                "2. 责令责任部门30分钟内清理\n"
                "3. 开具安全隐患整改通知书\n"
                "4. 清理后拍照回传确认",
            ChangeType.PRESENT_TO_ABSENT:
                "1. 核实缺失设备/设施清单\n"
                "2. 检查设备借用/维修记录\n"
                "3. 若属违规移除，启动调查\n"
                "4. 补齐缺失设备并更新台账",
            ChangeType.ABSENT_TO_PRESENT:
                "1. 现场识别新增物体\n"
                "2. 评估是否为安全隐患\n"
                "3. 拍照留档并上报\n"
                "4. 若为隐患，触发 EHS 工单",
            ChangeType.LIGHTING_CHANGE:
                "建议人工复核确认是否存在真实异常。",
            ChangeType.UNKNOWN_CHANGE:
                "建议人工巡检确认情况。",
        }
        return actions.get(change_type, "建议人工巡检。")


# =========================
# Mock 巡检数据生成
# =========================


def generate_mock_patrol_alerts() -> List[Dict[str, Any]]:
    """
    生成 Mock 巡检告警数据用于开发和测试。

    Returns:
        预设的巡检告警场景列表
    """
    mock_alerts = [
        {
            "scenario": "fire_exit_blocked",
            "camera_id": "CAM_FIRE_EXIT_01",
            "area_type": "warehouse",
            "change_type": ChangeType.CLEAR_TO_BLOCKED,
            "description": "消防通道被纸箱和叉车堵塞",
            "severity": "high",
            "diff_distance": 28,
        },
        {
            "scenario": "ppe_rack_empty",
            "camera_id": "CAM_PPE_STATION_03",
            "area_type": "production",
            "change_type": ChangeType.PRESENT_TO_ABSENT,
            "description": "PPE站安全帽数量异常减少",
            "severity": "high",
            "diff_distance": 22,
        },
        {
            "scenario": "unknown_object",
            "camera_id": "CAM_WORKSHOP_07",
            "area_type": "hazard",
            "change_type": ChangeType.ABSENT_TO_PRESENT,
            "description": "检测到危险区域出现新物体",
            "severity": "medium",
            "diff_distance": 18,
        },
        {
            "scenario": "lighting_only",
            "camera_id": "CAM_CORRIDOR_02",
            "area_type": "corridor",
            "change_type": ChangeType.LIGHTING_CHANGE,
            "description": "走廊光照变化（可能因开关灯）",
            "severity": "low",
            "diff_distance": 8,
        },
    ]

    for alert in mock_alerts:
        alert["alert_id"] = f"PATROL_MOCK_{alert['camera_id']}_{alert['scenario']}"

    return mock_alerts
