"""argparse CLI 入口 + 启动前置检查。"""

from __future__ import annotations

import argparse
import os
import shutil
import sys


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="vertoscribe",
        description="一条命令，教学视频变高质量技术博客。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # config 子命令
    subparsers = parser.add_subparsers(dest="command", help="子命令")
    subparsers.add_parser("config", help="交互式配置 API 密钥（保存到 ~/.config/vertoscribe/.env）")

    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "-u", "--url",
        type=str,
        help="视频在线链接（仅支持抖音/B站），必须用引号包裹",
    )
    source.add_argument(
        "-f", "--file",
        type=str,
        help="本地 mp4 文件路径",
    )

    parser.add_argument(
        "-o", "--output",
        type=str,
        default="./output/",
        help="博客输出目录，默认 ./output/",
    )
    parser.add_argument(
        "-m", "--model",
        type=str,
        default="deepseek-chat",
        help="DeepSeek 模型名，默认 deepseek-chat",
    )
    parser.add_argument(
        "-t", "--temperature",
        type=float,
        default=0.7,
        help="LLM 温度，默认 0.7",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=8192,
        help="DeepSeek 输出最大 token，默认 8192",
    )
    parser.add_argument(
        "--with-vision",
        action="store_true",
        help="开启画面关键帧分析（需 DashScope API）",
    )
    parser.add_argument(
        "--vision-model",
        type=str,
        default="qwen-vl-plus",
        help="视觉模型，默认 qwen-vl-plus，可升级 qwen-vl-max",
    )
    parser.add_argument(
        "--frame-interval",
        type=int,
        default=10,
        help="关键帧提取间隔（秒），默认 10，仅 --with-vision 时生效",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="保留中间文件（调试用）",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="打印详细日志",
    )

    return parser


def _try_load(path: str) -> bool:
    """尝试加载单个 .env 文件，成功返回 True。"""
    if not os.path.isfile(path):
        return False
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, val = line.partition("=")
            if key and val:
                os.environ.setdefault(
                    key.strip(), val.strip().strip('"').strip("'")
                )
    return True


def load_dotenv(path: str | None = None):
    """按优先级加载 .env：指定路径 > ~/.config/vertoscribe/.env > 当前目录 .env。"""
    if path:
        _try_load(path)
        return

    # 用户级配置（CLI 全局安装后的推荐位置）
    user_config = os.path.join(os.path.expanduser("~"), ".config", "vertoscribe", ".env")
    current_dir = os.path.join(os.getcwd(), ".env")

    loaded = False
    for p in (user_config, current_dir):
        if _try_load(p):
            loaded = True

    if not loaded:
        # 静默，preflight_check 会给出友好提示
        pass


def init_config():
    """交互式创建用户级配置文件 ~/.config/vertoscribe/.env。"""
    config_dir = os.path.join(os.path.expanduser("~"), ".config", "vertoscribe")
    config_path = os.path.join(config_dir, ".env")

    if os.path.isfile(config_path):
        print(f"配置文件已存在: {config_path}")
        print("如需重新配置，请手动编辑该文件。")
        return

    print("首次使用 vertoscribe，需要配置 API 密钥。")
    print(f"配置将保存到: {config_path}\n")

    deepseek_key = input("DeepSeek API Key（必需，回车跳过）: ").strip()
    dashscope_key = input("DashScope API Key（可选，--with-vision 时需要，回车跳过）: ").strip()
    whisper_model = input("Whisper 模型（可选，默认 base，回车跳过）: ").strip()

    os.makedirs(config_dir, exist_ok=True)
    with open(config_path, "w") as f:
        f.write("# Vertoscribe 配置文件\n")
        if deepseek_key:
            f.write(f"DEEPSEEK_API_KEY={deepseek_key}\n")
        if dashscope_key:
            f.write(f"DASHSCOPE_API_KEY={dashscope_key}\n")
        if whisper_model:
            f.write(f"WHISPER_MODEL={whisper_model}\n")

    print(f"\n✅ 配置已保存。现在可以直接使用 vertoscribe 命令了。")
    # 加载刚创建的配置
    _try_load(config_path)


def preflight_check(args: argparse.Namespace) -> list[str]:
    """启动前置检查，返回警告列表。致命错误直接 sys.exit。"""
    warnings = []

    # 1. ffmpeg 可用性（致命）
    if shutil.which("ffmpeg") is None:
        sys.exit(
            "❌ 未检测到 ffmpeg。请安装:\n"
            "  macOS: brew install ffmpeg\n"
            "  Linux: apt install ffmpeg\n"
            "  Windows: winget install ffmpeg  (或从 https://ffmpeg.org 下载)"
        )

    # 2. ffprobe 可用性
    if shutil.which("ffprobe") is None:
        warnings.append("⚠️ ffprobe 未检测到，将跳过输入文件校验")

    # 3. yt-dlp 可用性（仅 URL 模式）
    if args.url and shutil.which("yt-dlp") is None:
        sys.exit("❌ URL 模式需要 yt-dlp。请安装: pip install yt-dlp")

    # 4. API Key
    if not os.getenv("DEEPSEEK_API_KEY"):
        warnings.append("⚠️ DEEPSEEK_API_KEY 未设置，合成步骤将失败")
    if args.with_vision and not os.getenv("DASHSCOPE_API_KEY"):
        warnings.append("⚠️ --with-vision 已开启但 DASHSCOPE_API_KEY 未设置")

    return warnings


def main():
    parser = build_parser()
    args = parser.parse_args()

    # 子命令：交互式配置
    if getattr(args, "command", None) == "config":
        init_config()
        return

    load_dotenv()
    warnings = preflight_check(args)

    if args.verbose:
        print("🔍 前置检查...", end=" ")
        print("ffmpeg ✅", end=" | ")
        if shutil.which("ffprobe"):
            print("ffprobe ✅", end=" | ")
        if args.url:
            print("yt-dlp ✅", end=" | ")
        if os.getenv("DEEPSEEK_API_KEY"):
            print("DEEPSEEK_API_KEY ✅", end="")
        if args.with_vision and os.getenv("DASHSCOPE_API_KEY"):
            print(" | DASHSCOPE_API_KEY ✅", end="")
        print()

    for w in warnings:
        print(w, file=sys.stderr)

    # TODO: Phase 1 - 串联全流程
    print(f"URL: {args.url}, File: {args.file}, Output: {args.output}")
    print(f"Model: {args.model}, WithVision: {args.with_vision}")


if __name__ == "__main__":
    main()
