# Changelog

## [1.1.0] - 2026-09-11

### Added
- 抖音视频下载：yt-dlp 已失效，改为内置 Web API 解析（a_bogus 签名 + ttwid 游客凭证），无需登录、无需 cookie
- 文风重写 pass（默认开启，`--no-rewrite` 关闭）：初稿生成后额外做一次"去 AI 味"重写，保留技术事实/代码/图表，带异常回退防御
- Mermaid 图表生成：流程/时序/架构/竞态内容自动配图，语法兼容掘金等旧版渲染器（subgraph 引号标题、管道边标签）
- 掘金发布优化：标题 ≤40 字、摘要 ≤100 字、tags 用主流分类名、文末开放性互动问题、轻量点赞引导
- 掘金发布建议包：`*_report.json` 新增 `publish` 字段（标题/标签/摘要，直接复制到发布表单）
- LLM 模型名支持 `.env` 配置（`LLM_MODEL`，优先级低于 `-m` 参数）
- 博客模板扩充至 8 种：新增问答体、踩坑复盘、方案对比
- 抖音离线单元测试（`tests/test_douyin.py`）

### Changed
- 协议从 MIT 改为 **GPL-3.0-or-later**（抖音 a_bogus 签名模块源自 TikTokDownloader 的 GPL v3 实现）
- 博客结构从"必须匹配模板"改为"参考取舍"，小节标题/摘要/收尾形式多样化，降低模板感
- 后处理检查重构：摘要多形式识别与长度检查、收尾段落白名单扩充、代码块围栏配对计数（修复闭合围栏误报）、mermaid 兼容性检查、段落长度与互动问句检查
- 生成文件名清洗：去除话题标签（#xxx）、emoji 及文件系统非法字符
- `normalize_blog` 兜底：自动修正 LLM 输出的开场白、frontmatter 被包进代码块等格式问题
- yt-dlp 前置检查仅对 B站链接要求（抖音不需要）

### Fixed
- 代码块"未标注语言"检查误报（闭合围栏被计入）
- 摘要长度测量把 `---` 分隔线后的开场叙事计入（同步修复 publish 摘要提取）
- 文末互动问句检查要求问号在行尾导致的误报
- `tags` 顿号分隔裸字符串格式提取失败
- 禁用词 `Needless to say` 前导空格导致永不匹配

## [0.2.0] - 2026-08-03

### Added
- Phase 2：画面关键帧分析（Qwen-VL-Plus/Max）——ffmpeg fps 抽帧 + dHash 去重 + 时间戳对齐 + 费用预估确认
- Phase 3：转录缓存（SHA256，`--no-cache` 跳过）、`--verbose`、`--keep-temp`、准确率 JSON 报告
- Phase 4：多 LLM 后端（DeepSeek / OpenAI / Ollama / Qwen，`--provider` + `--api-base`），Ollama 本地零成本模式
- CLI 交互式配置（`vertoscribe config`）+ 多级 .env 加载

## [0.1.0] - 2026-08-03

### Added
- 初始版本，Phase 1 MVP
- B站视频下载（yt-dlp）
- 音频提取（ffmpeg PCM 16kHz）
- 语音转录（faster-whisper，Apple Silicon 自适应）
- 博客合成（DeepSeek API + string.Template 注入）
- 写作规范后处理检查（TL;DR/禁用词/代码块语言标注）
- 临时文件自动清理（atexit）
- 启动前置检查（ffmpeg/ffprobe/yt-dlp/API Key）
- 内置 5 种技术博客类型模板

[1.1.0]: https://github.com/animacaeli/vertoscribe/releases/tag/v1.1.0
[0.2.0]: https://github.com/animacaeli/vertoscribe/releases/tag/v0.2.0
[0.1.0]: https://github.com/animacaeli/vertoscribe/releases/tag/v0.1.0
