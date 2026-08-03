"""ffmpeg 封装，提供视频音频提取、时长获取、文件校验功能。"""
from __future__ import annotations

import os
import subprocess


def extract_audio(video_path: str, output_path: str) -> str:
    """从 mp4 提取 16kHz 单声道 PCM wav。

    Args:
        video_path: 输入视频文件路径
        output_path: 输出 wav 文件路径

    Returns:
        生成的 wav 文件绝对路径

    Raises:
        RuntimeError: ffmpeg 执行失败时抛出
        FileNotFoundError: 输入文件不存在
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vn",                # 丢弃视频流
        "-ar", "16000",       # 采样率 16kHz
        "-ac", "1",           # 单声道
        "-c:a", "pcm_s16le",  # PCM 16-bit 小端编码
        output_path,
        "-y",                 # 覆盖已存在文件
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)

    if result.returncode != 0:
        raise RuntimeError(f"音频提取失败: {result.stderr.strip()}")

    if not os.path.isfile(output_path):
        raise RuntimeError(f"音频提取完成但未生成输出文件: {output_path}")

    return os.path.abspath(output_path)


def get_video_duration(video_path: str) -> float:
    """用 ffprobe 获取视频时长（秒）。

    Args:
        video_path: 视频文件路径

    Returns:
        视频时长，单位秒

    Raises:
        RuntimeError: ffprobe 执行失败或无法解析时长
        FileNotFoundError: 输入文件不存在
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        video_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)

    if result.returncode != 0:
        raise RuntimeError(f"获取视频时长失败: {result.stderr.strip()}")

    duration_str = result.stdout.strip()
    if not duration_str:
        raise RuntimeError("ffprobe 返回空结果，无法解析视频时长")

    try:
        return float(duration_str)
    except ValueError:
        raise RuntimeError(f"无法解析视频时长: {duration_str}")


def validate_video(video_path: str) -> bool:
    """用 ffprobe 校验是否为有效视频文件。

    Args:
        video_path: 视频文件路径

    Returns:
        True 表示有效视频文件，False 表示校验失败
    """
    if not os.path.isfile(video_path):
        return False

    # 先用 ffprobe 检查文件格式是否可解析
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        video_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)

    if result.returncode != 0:
        return False

    duration_str = result.stdout.strip()
    if not duration_str:
        return False

    try:
        duration = float(duration_str)
        return duration > 0
    except ValueError:
        return False
