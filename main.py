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

from src.cli import build_parser, load_dotenv, preflight_check, resolve_model

# 完整度门槛：最终文章 accuracy_score 低于此值触发定向补全 pass（最多补 N 次）
MIN_ACCURACY_SCORE = 9.0
MAX_ENRICH_ATTEMPTS = 2


def _count_code_blocks(text: str) -> int:
    """统计 Markdown 中的代码块数量（按围栏开栏数除以 2）。"""
    return len(re.findall(r"^\s*```", text, re.MULTILINE)) // 2


def _enrich_to_target(blog_content: str, args) -> tuple[str, float | None]:
    """完整度门槛：accuracy_score < 9 时定向补全，最多 MAX_ENRICH_ATTEMPTS 次。

    run() 主流程与 run_enrich() 存量补全共用。返回 (最终内容, 最终分数)；
    补全失败或结果缩水时返回补全前版本，由调用方决定是否告警。
    """
    from src.postprocess import normalize_blog
    from src.synthesizer import enrich_blog, extract_accuracy_score

    score = extract_accuracy_score(blog_content)
    if score is None:
        print(
            "  ⚠️  未提取到 accuracy_score，完整度门槛未生效（模型未输出评估段）",
            file=sys.stderr,
        )
        return blog_content, None

    for attempt in range(1, MAX_ENRICH_ATTEMPTS + 1):
        if score >= MIN_ACCURACY_SCORE:
            return blog_content, score
        print(
            f"  🧩 完整度 {score:g}/10 < {MIN_ACCURACY_SCORE:g}，"
            f"定向补全 (第 {attempt}/{MAX_ENRICH_ATTEMPTS} 次)..."
        )
        try:
            enriched = normalize_blog(
                enrich_blog(
                    blog_content,
                    model=args.model,
                    provider=args.provider,
                    api_base=args.api_base,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                )
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠️  完整度补全失败（{exc}），保留补全前版本", file=sys.stderr)
            return blog_content, score
        # 防御：补全只许加料不许缩水
        if (
            enriched.startswith("---")
            and len(enriched) > len(blog_content) * 0.7
            and _count_code_blocks(enriched) >= _count_code_blocks(blog_content) * 0.8
        ):
            blog_content = enriched
            score = extract_accuracy_score(blog_content)
        else:
            print("  ⚠️  补全结果异常（内容/代码块缩水），保留补全前版本", file=sys.stderr)
            return blog_content, score
    return blog_content, score


def run_enrich(args) -> list[str]:
    """enrich 子命令：把已有博客 .md 的内容完整度补全到 9+，就地升级。

    存量文章 retrofit 入口（新文章由 run() 内的完整度门槛自动处理）：
    读取 → 定向补全（仅当 accuracy_score < 9）→ 标题提升 → mermaid 清洗
    → 规范检查 → 就地保存（默认备份原稿为 .bak.md）→ 更新同目录报告。

    Args:
        args: argparse.Namespace，files 为待补全 .md 路径列表。

    Returns:
        处理成功的文件路径列表。
    """
    from src.postprocess import (
        check_blog,
        extract_publish_info,
        fix_mermaid_quotes,
        normalize_blog,
        promote_ctr_title,
        save_blog,
    )
    from src.synthesizer import extract_accuracy_score

    processed: list[str] = []
    for path_str in args.files:
        path = Path(path_str)
        if not path.is_file():
            print(f"❌ 文件不存在，跳过: {path}", file=sys.stderr)
            continue

        original = path.read_text(encoding="utf-8")
        blog_content = normalize_blog(original)
        score_before = extract_accuracy_score(blog_content)
        print(f"\n📄 {path.name}: 完整度 {score_before if score_before is not None else '未知'}/10")

        blog_content, score = _enrich_to_target(blog_content, args)

        blog_content = promote_ctr_title(blog_content)
        blog_content = fix_mermaid_quotes(blog_content)
        result = check_blog(blog_content)
        print(f"  写作规范评分: {result['score']}/10")
        for w in result["warnings"]:
            print(f"  ⚠️  {w}")

        if blog_content == original:
            print("  无需修改 ✅")
            processed.append(str(path))
            continue

        # 备份原稿；.bak.md 已存在时保留最早的原稿（重复 enrich 不覆盖）
        backup = path.with_suffix(".bak.md")
        backup_kept = False
        if not getattr(args, "no_backup", False):
            if backup.exists():
                backup_kept = True
            else:
                backup.write_text(original, encoding="utf-8")
        save_blog(blog_content, str(path))
        backup_note = (
            "（原稿备份已存在，保留最早版本）"
            if backup_kept
            else (f"（原稿备份 {backup.name}）" if not getattr(args, "no_backup", False) else "")
        )
        print(
            f"  完整度 {score_before if score_before is not None else '未知'} → "
            f"{score if score is not None else '未知'}，已就地更新{backup_note}"
        )

        # 就近更新评估报告（保留 video_title 等既有字段）
        import json as _json

        report_path = str(path).removesuffix(".md") + "_report.json"
        report: dict = {}
        if os.path.isfile(report_path):
            with open(report_path, encoding="utf-8") as _f:
                report = _json.load(_f)
        report.update(
            {
                "output_file": os.path.abspath(path),
                "model": args.model,
                "quality_score": result["score"],
                "warnings": result["warnings"],
                "accuracy_score": score,
                "publish": extract_publish_info(blog_content),
            }
        )
        with open(report_path, "w", encoding="utf-8") as _f:
            _json.dump(report, _f, ensure_ascii=False, indent=2)
        processed.append(str(path))

    return processed


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
    from src.postprocess import (
        check_blog,
        extract_publish_info,
        fix_mermaid_quotes,
        normalize_blog,
        promote_ctr_title,
        save_blog,
    )
    from src.synthesizer import rewrite_blog, synthesize
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

    from src.cache import load_transcript, save_transcript

    # 尝试从缓存加载
    segments, full_text = None, ""
    if not getattr(args, "no_cache", False):
        cached = load_transcript(video_path)
        if cached:
            segments, full_text = cached
            print(f"[{step}/{total_steps}] 语音转录（缓存命中 ✅，跳过）...")
            if args.verbose:
                print(f"  转录段落数: {len(segments)}")
                print(f"  文本长度: {len(full_text)} 字符")

    if not segments:
        print(f"[{step}/{total_steps}] 语音转录（faster-whisper）...")
        model_name = os.getenv("WHISPER_MODEL", None)
        segments, full_text = transcribe(audio_path, model_name=model_name)
        if args.verbose:
            print(f"  转录段落数: {len(segments)}")
            print(f"  文本长度: {len(full_text)} 字符")
        # 写入缓存
        save_transcript(video_path, segments, full_text)
        if args.verbose:
            print("  已缓存: ~/.cache/vertoscribe/")

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
            results = asyncio.run(
                analyze_all_frames(
                    deduped, model=args.vision_model, concurrency=5,
                    interval=args.frame_interval,
                )
            )

            # 步骤 5d：格式化画面描述
            print(f"[5d/{total_steps}] 格式化画面描述...")
            vision_descriptions = format_vision_descriptions(results)
            vision_was_run = True

        step = 6  # 后续主步骤从 6 开始（vision 模式）
    else:
        step += 1  # 纯音频模式：下一步是步骤 5

    # ====== 步骤 合成（纯音频模式为步骤 5，vision 模式为步骤 6） ======
    print(f"[{step}/{total_steps}] 博客合成（LLM: {args.model}）...")
    blog_content = synthesize(
        transcript=full_text,
        output_dir=args.output,
        vision_descriptions=vision_descriptions,
        model=args.model,
        provider=getattr(args, "provider", "deepseek"),
        api_base=getattr(args, "api_base", None),
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    if args.verbose:
        print(f"  博客长度: {len(blog_content)} 字符")

    # 兜底修正 LLM 常见格式问题（开场白 / frontmatter 被包进代码块）
    blog_content = normalize_blog(blog_content)

    # 文风重写 pass：技术事实保留，只重写表达，去除模板感与 AI 味
    if not getattr(args, "no_rewrite", False):
        try:
            rewritten = rewrite_blog(
                blog_content,
                model=args.model,
                provider=getattr(args, "provider", "deepseek"),
                api_base=getattr(args, "api_base", None),
                temperature=args.temperature,
                max_tokens=args.max_tokens,
            )
            rewritten = normalize_blog(rewritten)

            # 防御：重写丢失 frontmatter、内容过短或代码块明显缩水则回退初稿
            if (
                rewritten.startswith("---")
                and len(rewritten) > len(blog_content) * 0.5
                and _count_code_blocks(rewritten) >= _count_code_blocks(blog_content) * 0.8
            ):
                blog_content = rewritten
                if args.verbose:
                    print(f"  重写后长度: {len(blog_content)} 字符")
            else:
                print("  ⚠️  重写结果异常（内容/代码块缩水），保留初稿", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠️  文风重写失败（{exc}），保留初稿", file=sys.stderr)

    # 完整度门槛：accuracy_score < 9 时做定向补全 pass
    # （视频素材不完整不是借口——缺口用共识知识补齐，文章必须独立完整）
    blog_content, score = _enrich_to_target(blog_content, args)
    if score is not None and score < MIN_ACCURACY_SCORE:
        print(
            f"  ⚠️  补全后完整度仍为 {score:g}/10，建议人工审查补充",
            file=sys.stderr,
        )

    # ====== 步骤 后处理检查（纯音频模式为步骤 6，vision 模式为步骤 7） ======
    # 模型自选标题弱于其候选时，确定性地换成第一条通过 CTR 检查的候选
    blog_content = promote_ctr_title(blog_content)
    # 掘金发布管线会把引号转义为 HTML 实体导致线上图表挂掉，提前去掉可安全去除的引号
    blog_content = fix_mermaid_quotes(blog_content)
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

    # 文件名优先用博客 frontmatter 标题（视频标题可能是整段口述问题，过长），
    # 并统一清理与截断
    base_title = (
        extract_publish_info(blog_content).get("title")
        or re.sub(r"#\S+", "", video_title)
    )
    # \w 在 unicode 模式下已含中文，此处剔除 emoji、话题标签等特殊符号
    clean_title = re.sub(r"[^\w\s.-]", "", base_title)
    clean_title = re.sub(r"\s+", " ", clean_title).strip(" -")
    # 清理文件名中的特殊字符: /\:*?"<>| 替换为 -
    safe_title = re.sub(r'[/\\:*?"<>|]', "-", clean_title or "untitled")
    # 去除连续短横线、首尾空白，并截断到 50 字符
    safe_title = re.sub(r"-{2,}", "-", safe_title).strip()[:50].strip(" -")
    output_filename = f"{safe_title}.md"
    output_path = os.path.join(args.output, output_filename)

    blog_path = save_blog(blog_content, output_path)
    print(f"  ✅ 博客已保存: {blog_path}")

    # ====== 保存准确率评估报告 ======
    report = {
        "output_file": blog_path,
        "video_title": video_title,
        "model": args.model,
        "quality_score": result["score"],
        "warnings": result["warnings"],
        "accuracy_score": score,
        "transcript_chars": len(full_text),
        "blog_chars": len(blog_content),
        "vision_enabled": args.with_vision,
        # 掘金发布表单建议（标题/标签/摘要直接复制使用）
        "publish": extract_publish_info(blog_content),
    }
    report_path = output_path.replace(".md", "_report.json")
    import json as _json
    with open(report_path, "w", encoding="utf-8") as _f:
        _json.dump(report, _f, ensure_ascii=False, indent=2)
    if args.verbose:
        print(f"  📊 评估报告: {report_path}")

    # ====== 掘金推荐流运营提示（详细版在 _report.json 的 publish 字段） ======
    publish_info = report["publish"]
    print(f"  💡 建议发布窗口: {publish_info['publish_window']['首选']}")
    alt_titles = [t for t in publish_info.get("title_candidates", [])[1:] if t]
    if alt_titles:
        print(f"  🎯 备选标题（48h 数据差时可换）: {' / '.join(alt_titles)}")

    # ====== 准确率对比（vision 模式时输出） ======
    if vision_was_run:
        print()
        if score is not None:
            print(f"🖼️ 含画面分析的完整度: {score:g}/10")
        else:
            print("🖼️ 含画面分析完整度: 未从博客中提取到 accuracy_score")
        print("（完整度 = 文章作为独立技术文章的完整程度，缺口已尽量用共识知识补全）")

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
    resolve_model(args)

    # 前置检查
    warnings = preflight_check(args)

    if args.verbose:
        print("🔍 前置检查...", end=" ")
        print("ffmpeg ✅", end=" | ")
        if shutil.which("ffprobe"):
            print("ffprobe ✅", end=" | ")
        if args.url and shutil.which("yt-dlp"):
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
