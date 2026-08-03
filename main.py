"""vertoscribe 主流程入口。

串联视频下载 → 音频提取 → 语音转录 → [画面分析] → 博客合成 → 后处理检查 → 保存的完整流程。

用法:
    python main.py -u "https://www.bilibili.com/video/xxx" -o ./output/
    python main.py -f ./video.mp4 -o ./output/
    python main.py -f ./video.mp4 -o ./output/ --with-vision

也可通过 pip 安装后使用 console_scripts 入口: vertoscribe
"""

from __future__ import annotations

import asyncio
import atexit
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from src.cli import build_parser, load_dotenv, preflight_check


def run(args) -> str:
    """主流程编排，返回最终博客文件路径。

    流程步骤:
        1. 输入准备：URL 模式下载视频 / 本地模式使用文件路径
        2. validate_video() 校验视频格式
        3. extract_audio() 提取音频
        4. transcribe() 语音转录为文本
        5. [可选] vision 画面分析（提取关键帧 → 去重 → API 分析 → 格式化）
        6. synthesize() 调用 LLM 合成博客
        7. check_blog() 后处理规范检查
        8. save_blog() 保存到输出目录

    Args:
        args: argparse.Namespace，由 build_parser().parse_args() 产生。

    Returns:
        最终保存的博客 .md 文件绝对路径。
    """
    # 延迟导入 src 子模块，避免未安装依赖时模块级 import 失败
    from src.audio import extract_audio, validate_video
    from src.downloader import VideoDownloadError, download_video, get_video_title
    from src.postprocess import check_blog, save_blog
    from src.synthesizer import synthesize
    from src.transcriber import transcribe

    # ====== 创建临时工作目录 ======
    work_dir = tempfile.mkdtemp(prefix="vertoscribe-")

    def cleanup():
        """清理临时工作目录（除非 --keep-temp）。"""
        if not args.keep_temp:
            if os.path.isdir(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)
            if args.verbose:
                print(f"[清理] 已删除临时目录: {work_dir}")

    atexit.register(cleanup)

    if args.verbose:
        print(f"[临时目录] {work_dir}")

    # 动态计算总步骤数（vision 模式比纯音频多 2 步）
    total_steps = 9 if args.with_vision else 7
    step = 0

    # ====== 步骤 1：输入准备 ======
    step += 1
    if args.url:
        print(f"[{step}/{total_steps}] 下载视频...")
        if args.verbose:
            print(f"  链接: {args.url}")
        video_path = download_video(args.url, work_dir)
        # 获取视频标题用于输出文件名
        try:
            video_title = get_video_title(args.url)
        except (VideoDownloadError, ValueError):
            # get_video_title 可能因网络/平台问题失败，降级为标题 fallback
            video_title = "untitled"
    else:
        print(f"[{step}/{total_steps}] 使用本地视频文件...")
        video_path = args.file
        if args.verbose:
            print(f"  文件: {video_path}")
        video_title = Path(video_path).stem

    if args.verbose:
        print(f"  视频路径: {video_path}")
        print(f"  视频标题: {video_title}")

    # ====== 步骤 2：校验视频 ======
    step += 1
    print(f"[{step}/{total_steps}] 校验视频文件...")
    if not validate_video(video_path):
        print("❌ 视频文件校验失败，该文件不是有效的视频文件", file=sys.stderr)
        sys.exit(1)
    if args.verbose:
        print("  校验通过 ✅")

    # ====== 步骤 3：提取音频 ======
    step += 1
    print(f"[{step}/{total_steps}] 提取音频...")
    audio_path = extract_audio(video_path, os.path.join(work_dir, "audio.wav"))
    if args.verbose:
        print(f"  音频路径: {audio_path}")

    # ====== 步骤 4：语音转录 ======
    step += 1
    print(f"[{step}/{total_steps}] 语音转录（faster-whisper）...")
    model_name = os.getenv("WHISPER_MODEL", None)
    segments, full_text = transcribe(audio_path, model_name=model_name)
    if args.verbose:
        print(f"  转录段落数: {len(segments)}")
        print(f"  文本长度: {len(full_text)} 字符")

    # ====== 画面分析（Phase 2：--with-vision 时启用） ======
    vision_descriptions = ""
    vision_was_run = False

    if args.with_vision:
        # 延迟导入 vision 模块
        from src.vision import (
            analyze_all_frames,
            deduplicate_frames,
            extract_keyframes,
            format_vision_descriptions,
        )

        # 步骤 5a：提取关键帧
        print(f"[5a/{total_steps}] 提取关键帧（间隔 {args.frame_interval}s）...")
        frame_paths = extract_keyframes(video_path, work_dir, interval=args.frame_interval)
        if args.verbose:
            print(f"  提取到 {len(frame_paths)} 帧")

        # 步骤 5b：去重关键帧
        print(f"[5b/{total_steps}] 去重关键帧...")
        deduped = deduplicate_frames(frame_paths, threshold=5)
        print(f"  原始 {len(frame_paths)} 帧 → 去重后 {len(deduped)} 帧")

        # 长视频费用预估（去重后 > 100 帧时）
        if len(deduped) > 100:
            cost_plus = len(deduped) * 0.004
            cost_max = len(deduped) * 0.02
            print(f"\n⚠️ 画面分析需处理 {len(deduped)} 帧，预估费用:")
            print(f"  · qwen-vl-plus（当前）: ¥{cost_plus:.2f}")
            if args.vision_model == "qwen-vl-max":
                print(f"  · qwen-vl-max: ¥{cost_max:.2f}")
            answer = input("是否继续？[y/N] ")
            if answer.lower() not in ("y", "yes"):
                print("已取消画面分析，降级为纯音频模式")
                args.with_vision = False

        if args.with_vision:
            # 步骤 5c：调用视觉模型分析画面
            print(f"[5c/{total_steps}] 画面分析（{args.vision_model}）...")
            results = asyncio.run(analyze_all_frames(deduped, model=args.vision_model, concurrency=5))

            # 步骤 5d：格式化画面描述
            print(f"[5d/{total_steps}] 格式化画面描述...")
            vision_descriptions = format_vision_descriptions(results)
            vision_was_run = True

        step = 6  # 后续主步骤从 6 开始（vision 模式）
    else:
        step += 1  # 纯音频模式：下一步是步骤 5

    # ====== 步骤 合成（纯音频模式为步骤 5，vision 模式为步骤 6） ======
    print(f"[{step}/{total_steps}] 博客合成（DeepSeek）...")
    blog_content = synthesize(
        transcript=full_text,
        output_dir=args.output,
        vision_descriptions=vision_descriptions,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    if args.verbose:
        print(f"  博客长度: {len(blog_content)} 字符")

    # ====== 步骤 后处理检查（纯音频模式为步骤 6，vision 模式为步骤 7） ======
    step += 1
    print(f"[{step}/{total_steps}] 后处理检查...")
    result = check_blog(blog_content)
    print(f"  写作规范评分: {result['score']}/10")
    if result["warnings"]:
        for w in result["warnings"]:
            print(f"  ⚠️  {w}")
    if result["score"] < 6:
        print("  ⚠️  博客评分较低，建议人工审查后发布", file=sys.stderr)

    # ====== 步骤 保存博客（纯音频模式为步骤 7，vision 模式为步骤 8） ======
    step += 1
    print(f"[{step}/{total_steps}] 保存博客...")

    # 清理文件名中的特殊字符: /\:*?"<>| 替换为 -
    safe_title = re.sub(r'[/\\:*?"<>|]', "-", video_title)
    # 去除连续短横线和首尾空白
    safe_title = re.sub(r"-{2,}", "-", safe_title).strip()
    output_filename = f"{safe_title}.md"
    output_path = os.path.join(args.output, output_filename)

    blog_path = save_blog(blog_content, output_path)
    print(f"  ✅ 博客已保存: {blog_path}")

    # ====== 准确率对比（vision 模式时输出） ======
    if vision_was_run:
        print()
        print("🎯 纯音频准确率预估: ~7-8/10")
        match = re.search(
            r"(?:accuracy_score|准确度[评分]).*?[:：]\s*(\d+(?:\.\d+)?)",
            blog_content,
            re.IGNORECASE,
        )
        if match:
            print(f"🖼️ 含画面分析准确率: {match.group(1)}/10")
        else:
            print("🖼️ 含画面分析准确率: 未从博客中提取到 accuracy_score")

    # ====== 清理临时文件（主动清理 + 取消 atexit 注册避免重复） ======
    if not args.keep_temp:
        cleanup()
        atexit.unregister(cleanup)

    return blog_path


if __name__ == "__main__":
    # 加载 .env 环境变量
    load_dotenv()

    # 解析命令行参数
    parser = build_parser()
    args = parser.parse_args()

    # 前置检查
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

    # 执行主流程
    try:
        output_path = run(args)
        print(f"\n📄 输出文件: {output_path}")
    except KeyboardInterrupt:
        print("\n⚠️  用户中断", file=sys.stderr)
        sys.exit(130)
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ 执行失败: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
