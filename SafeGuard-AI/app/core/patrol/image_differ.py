"""
图像差异检测器

实现数字巡检员的核心能力：对比历史基线图像与当前帧，
使用感知哈希检测差异区域。

支持的哈希算法:
    - aHash (Average Hash): 基于像素平均值，速度快，适合检测全局变化
    - dHash (Difference Hash): 基于像素梯度，对亮度变化鲁棒
    - pHash (Perceptual Hash): 基于 DCT 变换，对缩放/压缩鲁棒（若 OpenCV 可用）

使用方式:
    hasher = ImageHasher(method="dhash")
    baseline_hash = hasher.compute(baseline_image_path)
    current_hash = hasher.compute(current_image_path)
    distance = hasher.hamming_distance(baseline_hash, current_hash)
    if distance > threshold:
        # 检测到显著变化
"""
import logging
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# 默认差异阈值（Hamming 距离）
DEFAULT_DIFF_THRESHOLD = 12  # dHash 256-bit 的推荐阈值
HIGH_DIFF_THRESHOLD = 20     # 显著变化

# 图像哈希大小
HASH_SIZE = 16  # 16×16 输入 → 256-bit 哈希


class HashMethod(str, Enum):
    """哈希算法类型"""
    AHASH = "ahash"    # 平均值哈希
    DHASH = "dhash"    # 梯度差异哈希（默认）
    PHASH = "phas"     # DCT 感知哈希


class ImageHasher:
    """
    图像感知哈希计算器。

    支持三种算法：
        - aHash: 缩放到 hash_size×hash_size，与均值比较
        - dHash: 缩放到 hash_size×(hash_size+1)，比较相邻像素
        - pHash: DCT 变换后取低频系数（需 OpenCV）

    dHash 是默认选择——对亮度变化鲁棒，对内容变化敏感，
    特别适合工业监控场景（光照变化常见，结构变化才是关键）。

    使用方式:
        hasher = ImageHasher()
        h1 = hasher.compute(Path("baseline.jpg"))
        h2 = hasher.compute(Path("current.jpg"))
        dist = hasher.hamming_distance(h1, h2)
    """

    def __init__(self, method: HashMethod = HashMethod.DHASH, hash_size: int = HASH_SIZE):
        self.method = method
        self.hash_size = hash_size

    def compute(self, image_path: Path) -> str:
        """
        计算图像的感知哈希。

        Args:
            image_path: 图像文件路径

        Returns:
            十六进制哈希字符串

        Raises:
            FileNotFoundError: 图像文件不存在
        """
        if not image_path.exists():
            raise FileNotFoundError(f"图像文件不存在: {image_path}")

        if self.method == HashMethod.AHASH:
            return self._ahash(image_path)
        elif self.method == HashMethod.DHASH:
            return self._dhash(image_path)
        elif self.method == HashMethod.PHASH:
            return self._phas(image_path)
        else:
            raise ValueError(f"不支持的哈希算法: {self.method}")

    def _ahash(self, path: Path) -> str:
        """平均值哈希。"""
        pixels = self._load_grayscale(path, self.hash_size, self.hash_size)
        avg = sum(pixels) / len(pixels)
        bits = ['1' if p >= avg else '0' for p in pixels]
        return self._bits_to_hex(bits)

    def _dhash(self, path: Path) -> str:
        """
        梯度差异哈希。

        缩放到 hash_size×(hash_size+1)，比较每行相邻像素。
        生成 hash_size² bit 的哈希。
        """
        pixels = self._load_grayscale(path, self.hash_size + 1, self.hash_size)
        bits = []
        for row in range(self.hash_size):
            for col in range(self.hash_size):
                left = pixels[row * (self.hash_size + 1) + col]
                right = pixels[row * (self.hash_size + 1) + col + 1]
                bits.append('1' if left < right else '0')
        return self._bits_to_hex(bits)

    def _phas(self, path: Path) -> str:
        """
        DCT 感知哈希。

        尝试使用 OpenCV 的 DCT，不可用时降级为 dHash。
        """
        try:
            import cv2
            import numpy as np

            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                raise ValueError(f"无法读取图像: {path}")

            # 缩放到 32×32
            img = cv2.resize(img, (32, 32), interpolation=cv2.INTER_AREA)
            # DCT 变换
            dct = cv2.dct(np.float32(img))
            # 取左上角 8×8 低频系数
            dct_low = dct[:8, :8]
            # 与均值比较
            avg = dct_low.mean()
            bits = ['1' if dct_low[i, j] >= avg else '0'
                    for i in range(8) for j in range(8)]

            return self._bits_to_hex(bits)

        except ImportError:
            logger.info("[ImageHasher] OpenCV 不可用，pHash 降级为 dHash")
            return self._dhash(path)

    def _load_grayscale(self, path: Path, width: int, height: int) -> List[int]:
        """
        加载图像并缩放为灰度像素列表。

        优先使用 OpenCV（快速），降级为 PIL。

        Args:
            path: 图像路径
            width: 目标宽度
            height: 目标高度

        Returns:
            [pixel1, pixel2, ...] 灰度值列表 (0-255)
        """
        try:
            import cv2
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                resized = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)
                return resized.flatten().tolist()
        except ImportError:
            pass

        # PIL 降级
        from PIL import Image
        with Image.open(path) as img:
            img = img.convert("L")  # 灰度
            img = img.resize((width, height), Image.LANCZOS)
            return list(img.getdata())

    @staticmethod
    def _bits_to_hex(bits: List[str]) -> str:
        """将位列表转为十六进制字符串。"""
        hex_str = ""
        for i in range(0, len(bits), 4):
            nibble = bits[i:i+4]
            hex_str += format(int(''.join(nibble), 2), 'x')
        return hex_str

    @staticmethod
    def hamming_distance(hash1: str, hash2: str) -> int:
        """
        计算两个十六进制哈希字符串的汉明距离。

        Args:
            hash1: 第一个哈希
            hash2: 第二个哈希

        Returns:
            不同位的数量（0 表示完全相同）
        """
        if len(hash1) != len(hash2):
            raise ValueError(
                f"哈希长度不匹配: {len(hash1)} vs {len(hash2)}"
            )

        distance = 0
        for c1, c2 in zip(hash1, hash2):
            # 将十六进制字符转为整数，计算异或后的 bit 数
            xor = int(c1, 16) ^ int(c2, 16)
            distance += bin(xor).count('1')
        return distance

    @staticmethod
    def similarity(hash1: str, hash2: str) -> float:
        """
        计算两个哈希的相似度 (0.0-1.0)。

        Args:
            hash1: 第一个哈希
            hash2: 第二个哈希

        Returns:
            相似度（1.0=完全相同，0.0=完全不同）
        """
        distance = ImageHasher.hamming_distance(hash1, hash2)
        max_bits = len(hash1) * 4  # 每个十六进制字符 = 4 bits
        return 1.0 - (distance / max_bits)


class ImageDiffer:
    """
    图像差异检测器。

    维护历史基线图像哈希，对新帧进行差异分析。

    使用方式:
        differ = ImageDiffer()
        differ.set_baseline("camera_01", Path("baseline.jpg"))
        result = differ.compare("camera_01", Path("current.jpg"))
        if result["has_changed"]:
            print(f"检测到变化: 距离={result['distance']}")
    """

    def __init__(
        self,
        hasher: Optional[ImageHasher] = None,
        diff_threshold: int = DEFAULT_DIFF_THRESHOLD,
        high_diff_threshold: int = HIGH_DIFF_THRESHOLD,
    ):
        """
        初始化差异检测器。

        Args:
            hasher: 图像哈希计算器（None 时使用默认 dHash）
            diff_threshold: 变化检测阈值（Hamming 距离）
            high_diff_threshold: 显著变化阈值
        """
        self.hasher = hasher or ImageHasher()
        self.diff_threshold = diff_threshold
        self.high_diff_threshold = high_diff_threshold
        self._baselines: dict = {}   # camera_id → (path, hash)

    def set_baseline(self, camera_id: str, image_path: Path):
        """
        设置相机的基线图像。

        Args:
            camera_id: 相机标识
            image_path: 基线图像路径
        """
        h = self.hasher.compute(image_path)
        self._baselines[camera_id] = (image_path, h)
        logger.info(
            f"[ImageDiffer] 基线已设置: camera={camera_id}, "
            f"hash={h[:16]}..."
        )

    def get_baseline_hash(self, camera_id: str) -> Optional[str]:
        """获取相机基线哈希。"""
        entry = self._baselines.get(camera_id)
        return entry[1] if entry else None

    def compare(
        self, camera_id: str, current_path: Path
    ) -> dict:
        """
        比较当前帧与基线图像。

        Args:
            camera_id: 相机标识
            current_path: 当前帧图像路径

        Returns:
            {
                "camera_id": str,
                "has_changed": bool,
                "change_level": "none" | "minor" | "significant",
                "distance": int,
                "similarity": float,
                "baseline_hash": str,
                "current_hash": str,
            }

        Raises:
            ValueError: 相机基线未设置
        """
        if camera_id not in self._baselines:
            raise ValueError(
                f"相机 {camera_id} 的基线未设置。"
                f"请先调用 set_baseline()。"
            )

        _, baseline_hash = self._baselines[camera_id]
        current_hash = self.hasher.compute(current_path)
        distance = self.hasher.hamming_distance(baseline_hash, current_hash)
        similarity = self.hasher.similarity(baseline_hash, current_hash)

        # 变化等级判定
        if distance >= self.high_diff_threshold:
            change_level = "significant"
            has_changed = True
        elif distance >= self.diff_threshold:
            change_level = "minor"
            has_changed = True
        else:
            change_level = "none"
            has_changed = False

        logger.info(
            f"[ImageDiffer] camera={camera_id}: "
            f"distance={distance}, change={change_level}"
        )

        return {
            "camera_id": camera_id,
            "has_changed": has_changed,
            "change_level": change_level,
            "distance": distance,
            "similarity": round(similarity, 4),
            "baseline_hash": baseline_hash,
            "current_hash": current_hash,
        }

    def compare_with_hash(self, camera_id: str, current_hash: str) -> dict:
        """
        使用预计算的哈希进行比较（不读文件）。

        Args:
            camera_id: 相机标识
            current_hash: 当前帧的预计算哈希

        Returns:
            比较结果字典（不含 current_hash 重复计算）
        """
        if camera_id not in self._baselines:
            raise ValueError(f"相机 {camera_id} 的基线未设置。")

        _, baseline_hash = self._baselines[camera_id]
        distance = self.hasher.hamming_distance(baseline_hash, current_hash)
        similarity = self.hasher.similarity(baseline_hash, current_hash)

        if distance >= self.high_diff_threshold:
            change_level = "significant"
            has_changed = True
        elif distance >= self.diff_threshold:
            change_level = "minor"
            has_changed = True
        else:
            change_level = "none"
            has_changed = False

        return {
            "camera_id": camera_id,
            "has_changed": has_changed,
            "change_level": change_level,
            "distance": distance,
            "similarity": round(similarity, 4),
        }
