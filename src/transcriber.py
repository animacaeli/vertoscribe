"""faster-whisper 语音转文字封装。

将音频文件转写为带时间戳的段落列表和完整文本，供后续博客合成使用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Segment:
    """转录段落：包含起止时间和文本内容。"""

    start: float
    end: float
    text: str


def transcribe(
    audio_path: str,
    model_name: str | None = None,
) -> tuple[list[Segment], str]:
    """使用 faster-whisper 转录音频文件。

    Args:
        audio_path: 音频文件路径。
        model_name: Whisper 模型名称，默认从 WHISPER_MODEL 环境变量读取，
                    fallback 为 'base'。

    Returns:
        (带时间戳的段落列表, 拼接后的完整转录文本)。
    """
    # 确定模型名称
    if model_name is None:
        model_name = os.getenv("WHISPER_MODEL", "base")

    # 全平台统一使用 auto，CTranslate2 自动选择最优 compute_type
    compute = os.getenv("WHISPER_COMPUTE_TYPE", "auto")

    # 延迟导入，避免未安装依赖时模块加载失败
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type=compute)

    segments_result, _info = model.transcribe(audio_path, beam_size=5)

    segments: list[Segment] = []
    texts: list[str] = []
    for seg in segments_result:
        segments.append(Segment(start=seg.start, end=seg.end, text=seg.text.strip()))
        texts.append(seg.text.strip())

    full_text = " ".join(texts)
    return segments, full_text
