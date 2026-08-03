"""yt-dlp 封装，仅支持 B站 + 抖音视频下载。"""
from __future__ import annotations

import os
import re
import subprocess


class VideoDownloadError(Exception):
    """视频下载异常，携带用户可读的错误信息。"""

    def __init__(self, message: str):
        super().__init__(message)


def get_video_title(url: str) -> str:
    """获取视频标题（用于输出文件名）。

    Args:
        url: 视频链接，仅支持 bilibili.com 和 v.douyin.com

    Returns:
        视频标题字符串

    Raises:
        VideoDownloadError: yt-dlp 执行失败时抛出
        ValueError: 不支持的链接域名
    """
    _validate_url(url)

    cookie_env = _build_cookie_args()
    cmd = [
        "yt-dlp",
        "--print", "title",
        "--no-download",
        *cookie_env,
        url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "douyin" in url.lower() or "douyin" in stderr.lower():
            raise VideoDownloadError(
                "抖音视频下载失败。请通过手机端下载视频后，使用 -f 本地文件模式处理。"
            )
        raise VideoDownloadError(f"获取视频标题失败: {stderr}")

    title = result.stdout.strip()
    if not title:
        raise VideoDownloadError("未能从页面获取视频标题，链接可能已失效")

    return title


def download_video(url: str, output_dir: str) -> str:
    """下载视频 mp4，返回本地 mp4 路径。失败时返回友好错误信息。

    Args:
        url: 视频链接，仅支持 bilibili.com 和 v.douyin.com
        output_dir: 下载输出目录，文件固定命名为 video.mp4

    Returns:
        下载后的本地 mp4 文件绝对路径

    Raises:
        VideoDownloadError: 下载失败时抛出，含用户可读提示
        ValueError: 不支持的链接域名
    """
    _validate_url(url)

    out_path = os.path.join(output_dir, "video.mp4")
    cookie_env = _build_cookie_args()
    cmd = [
        "yt-dlp",
        "-f", "bv*+ba/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", out_path,
        "--no-playlist",
        *cookie_env,
        url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "douyin" in url.lower() or "douyin" in stderr.lower():
            raise VideoDownloadError(
                "抖音视频下载失败。抖音平台限制较多，请通过手机端下载视频后，"
                "使用 -f 指定本地 mp4 文件路径处理。"
            )
        raise VideoDownloadError(f"视频下载失败: {stderr}")

    # 校验输出文件是否存在
    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        raise VideoDownloadError(
            "视频下载完成但未生成有效文件，请检查链接是否有效或网络是否正常"
        )

    return os.path.abspath(out_path)


# ---- 内部辅助 ----

_SUPPORTED_DOMAINS = {
    "bilibili.com",
    "www.bilibili.com",
    "v.douyin.com",
}


def _validate_url(url: str) -> None:
    """校验链接域名是否在支持列表中。"""
    # 从 URL 提取域名
    match = re.search(r"https?://([^/]+)", url)
    if not match:
        raise ValueError(f"无效的 URL 格式: {url}")

    domain = match.group(1).lower()
    # 移除可能存在的 www. 前缀进行匹配
    if domain not in _SUPPORTED_DOMAINS and domain.replace("www.", "") not in _SUPPORTED_DOMAINS:
        raise ValueError(
            f"不支持的视频平台 ({domain})。vertoscribe 仅支持:\n"
            f"  - B站 (bilibili.com)\n"
            f"  - 抖音 (v.douyin.com)"
        )


def _build_cookie_args() -> list[str]:
    """从环境变量 BILIBILI_COOKIE 读取 cookie 文件路径（可选）。

    返回 yt-dlp 所需的命令行参数列表，如果环境变量未设置则返回空列表。
    """
    cookie_path = os.getenv("BILIBILI_COOKIE", "").strip()
    if cookie_path:
        return ["--cookies", cookie_path]
    return []
