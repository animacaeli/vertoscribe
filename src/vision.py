"""视频关键帧提取与 Qwen-VL 画面分析模块。

提取关键帧、dHash 去重、并发调用 Qwen-VL 分析画面内容。
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import re
import subprocess
from pathlib import Path

from openai import AsyncOpenAI
from PIL import Image

# 项目根目录（vertoscribe/）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# dHash 默认哈希尺寸
_DHASH_SIZE = 8

# DashScope Qwen-VL API 地址
_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


# ============================================================================
# 关键帧提取
# ============================================================================


def extract_keyframes(
    video_path: str,
    output_dir: str,
    interval: int = 10,
) -> list[str]:
    """用 ffmpeg 从视频中按固定间隔提取关键帧。

    Args:
        video_path: 输入视频文件路径。
        output_dir: 关键帧输出目录（不存在则自动创建）。
        interval: 抽帧间隔（秒），默认每 10 秒抽 1 帧。

    Returns:
        提取出的帧图片路径列表，按文件名自然排序。

    Raises:
        FileNotFoundError: 视频文件不存在。
        RuntimeError: ffmpeg 执行失败。
    """
    video = Path(video_path)
    if not video.exists():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ffmpeg 输出文件名模板：frame_0001.jpg, frame_0002.jpg, ...
    output_pattern = str(out_dir / "frame_%04d.jpg")

    cmd = [
        "ffmpeg",
        "-y",                       # 覆盖已有文件
        "-loglevel", "error",       # 只输出错误信息
        "-i", str(video),
        "-vf", f"fps=1/{interval}", # 每 interval 秒抽 1 帧
        "-qscale:v", "2",           # 高质量 JPEG（2 = 接近无损）
        output_pattern,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 关键帧提取失败: {result.stderr.strip()}")

    # 收集提取的帧文件，按文件名排序
    frame_paths = sorted(
        str(p) for p in out_dir.glob("frame_*.jpg")
    )
    if not frame_paths:
        raise RuntimeError("ffmpeg 执行成功但未生成任何关键帧，请检查视频内容")

    return frame_paths


# ============================================================================
# dHash 去重
# ============================================================================


def _dhash(image: Image.Image, hash_size: int = _DHASH_SIZE) -> int:
    """计算图片的差异哈希（difference hash）。

    将图片转为灰度、缩放到 (hash_size+1) x hash_size，
    然后逐行比较相邻像素的亮度差异，生成 hash_size^2 比特的指纹。

    Args:
        image: PIL Image 对象。
        hash_size: 哈希尺寸，默认 8，产生 64 位哈希。

    Returns:
        整数形式的差异哈希值。
    """
    # 缩放为 (hash_size + 1) × hash_size，使用抗锯齿
    resized = image.convert("L").resize(
        (hash_size + 1, hash_size),
        Image.LANCZOS,
    )
    pixels = list(resized.getdata())

    hash_val = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size + 1) + col]
            right = pixels[row * (hash_size + 1) + col + 1]
            if left < right:
                hash_val |= 1 << (row * hash_size + col)
    return hash_val


def _hamming_distance(h1: int, h2: int) -> int:
    """计算两个哈希值的汉明距离（不同比特位数量）。"""
    return (h1 ^ h2).bit_count()


def _is_duplicate(h1: int, h2: int, threshold: int = 5) -> bool:
    """判断两个哈希是否足够相似，视为重复帧。"""
    return _hamming_distance(h1, h2) < threshold


def deduplicate_frames(
    frame_paths: list[str],
    threshold: int = 5,
) -> list[str]:
    """用 dHash 对连续关键帧去重。

    从第二帧开始，逐一与前一个保留帧比较 dHash。
    汉明距离小于 threshold 的认为是重复帧，予以跳过。

    Args:
        frame_paths: 帧图片路径列表（已排序）。
        threshold: 汉明距离阈值，< threshold 视为重复，默认 5。

    Returns:
        去重后的帧路径列表。
    """
    if not frame_paths:
        return []

    # 第一帧总是保留
    kept = [frame_paths[0]]
    prev_hash = _dhash(Image.open(frame_paths[0]))

    for path in frame_paths[1:]:
        try:
            current_hash = _dhash(Image.open(path))
        except Exception as exc:
            raise RuntimeError(f"无法计算图片哈希: {path}") from exc

        if not _is_duplicate(prev_hash, current_hash, threshold):
            kept.append(path)
            prev_hash = current_hash
        # 否则跳过重复帧，prev_hash 保持不变

    return kept


# ============================================================================
# Qwen-VL 画面分析
# ============================================================================


def _load_vision_prompt() -> str:
    """从 prompts/vision_analysis.md 加载画面分析 Prompt。"""
    prompt_path = _PROJECT_ROOT / "prompts" / "vision_analysis.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Vision Prompt 文件不存在: {prompt_path}")
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _extract_timestamp(frame_path: str, interval: int) -> float:
    """从文件名提取时间戳（秒）。

    文件名格式：frame_0001.jpg → 帧序号 × 间隔 = 时间戳。

    Args:
        frame_path: 帧图片路径。
        interval: 抽帧间隔（秒）。

    Returns:
        该帧对应的时间偏移量（秒）。
    """
    filename = Path(frame_path).stem        # frame_0001
    match = re.search(r"(\d+)", filename)    # 提取数字部分
    if not match:
        raise ValueError(f"无法从文件名提取帧序号: {frame_path}")
    frame_number = int(match.group(1))
    return float(frame_number * interval)


async def analyze_frame(
    image_path: str,
    timestamp: float,
    model: str,
    client: AsyncOpenAI,
) -> dict:
    """用 Qwen-VL 模型分析单帧画面内容。

    Args:
        image_path: 帧图片路径。
        timestamp: 该帧对应的时间偏移量（秒），用于结果标识。
        model: 模型名称（如 qwen-vl-plus、qwen-vl-max）。
        client: OpenAI 兼容的异步客户端。

    Returns:
        {"timestamp": float, "description": str}

    Raises:
        RuntimeError: API 调用失败或响应为空。
    """
    prompt_text = _load_vision_prompt()

    # 读取图片并转为 data URL（JPEG base64）
    img = Image.open(image_path)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    data_url = f"data:image/jpeg;base64,{img_b64}"

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            max_tokens=1024,
            timeout=60,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Qwen-VL API 调用失败 [timestamp={timestamp:.1f}s, model={model}]: {exc}"
        ) from exc

    if not response.choices:
        raise RuntimeError(
            f"Qwen-VL 返回了空的 choices 列表 [timestamp={timestamp:.1f}s]"
        )

    description = response.choices[0].message.content or ""
    return {"timestamp": timestamp, "description": description.strip()}


async def analyze_all_frames(
    frame_paths: list[str],
    model: str = "qwen-vl-plus",
    concurrency: int = 5,
    interval: int = 10,
) -> list[dict]:
    """并发分析所有关键帧，Semaphore 限流。

    Args:
        frame_paths: 去重后的帧图片路径列表。
        model: Qwen-VL 模型，默认 'qwen-vl-plus'（可选 'qwen-vl-max'）。
        concurrency: 最大并发数，默认 5。

    Returns:
        按时间戳升序排列的分析结果列表。
        每项格式：{"timestamp": float, "description": str}

    Raises:
        RuntimeError: API Key 未设置或所有帧分析失败。
    """
    if not frame_paths:
        return []

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("环境变量 DASHSCOPE_API_KEY 未设置，无法调用 DashScope API")

    client = AsyncOpenAI(
        base_url=_DASHSCOPE_BASE_URL,
        api_key=api_key,
    )

    semaphore = asyncio.Semaphore(concurrency)

    async def _analyze_one(frame_path: str) -> dict:
        """带限流的单帧分析任务。"""
        timestamp = _extract_timestamp(frame_path, interval=interval)

        async with semaphore:
            print(f"  [vision] 分析中: {Path(frame_path).name} (t={timestamp:.0f}s)")
            try:
                result = await analyze_frame(
                    image_path=frame_path,
                    timestamp=timestamp,
                    model=model,
                    client=client,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"帧分析失败 [{Path(frame_path).name}]: {exc}"
                ) from exc

        return result

    # 并发执行所有帧分析
    tasks = [_analyze_one(fp) for fp in frame_paths]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 收集成功结果，报告失败
    successful: list[dict] = []
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            print(f"  [vision] 警告：{frame_paths[i]} 分析失败，已跳过: {res}")
        else:
            successful.append(res)

    if not successful:
        raise RuntimeError("所有关键帧分析均失败，无法继续")

    # 按时间戳升序排列
    successful.sort(key=lambda r: r["timestamp"])
    return successful


# ============================================================================
# 格式化输出
# ============================================================================


def _format_timestamp(seconds: float) -> str:
    """将秒数格式化为 MM:SS 字符串。"""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m:02d}:{s:02d}"


def format_vision_descriptions(results: list[dict]) -> str:
    """将 Vision 分析结果格式化为 DeepSeek 合成可用的文本。

    按时间戳排序后，每个帧格式为：

        [MM:SS] 画面描述

    Args:
        results: analyze_all_frames 的输出结果列表。

    Returns:
        拼接后的格式化文本。
    """
    if not results:
        return "（无画面分析数据）"

    # 确保按时间戳排序
    sorted_results = sorted(results, key=lambda r: r["timestamp"])

    lines: list[str] = []
    for item in sorted_results:
        ts = _format_timestamp(item["timestamp"])
        desc = item.get("description", "").strip()
        lines.append(f"[{ts}] {desc}")

    return "\n\n".join(lines)
