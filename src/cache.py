"""转录缓存：按视频 hash 缓存转写结果，避免重复转录。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from src.transcriber import Segment

# 缓存目录（~/.cache/vertoscribe/）
_CACHE_ROOT = Path.home() / ".cache" / "vertoscribe"


def _video_hash(video_path: str) -> str:
    """对视频文件的前 64KB 和后 64KB 做 SHA256，返回 hex 摘要。"""
    file_size = os.path.getsize(video_path)
    hasher = hashlib.sha256()
    with open(video_path, "rb") as f:
        # 读开头 64KB
        hasher.update(f.read(64 * 1024))
        # 跳到末尾前 64KB
        if file_size > 128 * 1024:
            f.seek(-64 * 1024, os.SEEK_END)
        hasher.update(f.read(64 * 1024))
    return hasher.hexdigest()[:16]  # 前 16 位足够区分


def _cache_path(video_hash: str) -> Path:
    """返回缓存文件路径。"""
    _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    return _CACHE_ROOT / f"{video_hash}.json"


def load_transcript(video_path: str) -> tuple[list[Segment], str] | None:
    """尝试从缓存加载转录结果。命中返回 (segments, full_text)，未命中返回 None。"""
    vhash = _video_hash(video_path)
    path = _cache_path(vhash)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        segments = [Segment(**s) for s in data["segments"]]
        return segments, data["full_text"]
    except (json.JSONDecodeError, KeyError, TypeError):
        # 缓存损坏，删除后返回 None
        path.unlink(missing_ok=True)
        return None


def save_transcript(
    video_path: str,
    segments: list[Segment],
    full_text: str,
) -> None:
    """将转录结果写入缓存。"""
    vhash = _video_hash(video_path)
    path = _cache_path(vhash)
    data = {
        "full_text": full_text,
        "segments": [{"start": s.start, "end": s.end, "text": s.text} for s in segments],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cache_stats(video_path: str) -> dict:
    """查询缓存信息。返回 {"exists": bool, "path": str}。"""
    vhash = _video_hash(video_path)
    path = _cache_path(vhash)
    return {
        "exists": path.exists(),
        "path": str(path),
    }
