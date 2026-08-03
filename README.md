# Vertoscribe

> *vertere*（拉丁语：转化）+ *scribere*（拉丁语：书写）— 将视频转化为文字。

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**一条命令，教学视频变高质量技术博客。**

## 快速开始

```bash
# 安装
pip install -e .

# 设置 API 密钥
export DEEPSEEK_API_KEY="sk-xxx"
export DASHSCOPE_API_KEY="sk-xxx"  # 可选，--with-vision 时需要

# 从 B 站视频生成博客
vertoscribe -u "https://www.bilibili.com/video/BV1xx411c7mD" -o ./output/

# 从本地 mp4 生成
vertoscribe -f ./tutorial.mp4 -o ./output/

# 开启画面分析
vertoscribe -f ./tutorial.mp4 -o ./output/ --with-vision
```

## 功能

- 🎥 支持 B站、抖音视频链接，也可使用本地 mp4 文件
- 🎙️ faster-whisper 本地语音转录，数据不出本机，隐私安全
- 🤖 多 LLM 后端支持：DeepSeek / OpenAI / Ollama / Qwen
- 🖼️ 可选画面关键帧分析（Qwen-VL），图片内容入文
- ✅ 写作规范自动检查（TL;DR / 代码块语言标注 / 禁用词 / YAML frontmatter）
- 📝 内置 5 种技术博客类型模板（教程 / 深度解析 / 架构设计 / 基准对比 / 工具评测）
- 💾 转录缓存：SHA256 哈希，避免重复转录
- 💰 成本透明：纯音频约 ¥0.01/篇，含画面约 ¥0.16/篇
- 🧹 临时文件自动清理，支持 `--keep-temp` 调试模式接口

## 安装

### 系统要求

- Python 3.10+
- ffmpeg（音频提取）

### 安装步骤

```bash
# 安装 ffmpeg（按平台选择）
brew install ffmpeg          # macOS
sudo apt install ffmpeg      # Linux
winget install ffmpeg        # Windows（或从 https://ffmpeg.org 下载）

# 克隆仓库
git clone https://github.com/animacaeli/vertoscribe.git
cd vertoscribe

# 安装 Python 依赖
pip install -e ".[dev]"
```

### 前置检查

运行前确保以下工具可用：

| 工具 | 用途 | 安装方式 |
|------|------|----------|
| ffmpeg | 音频提取 | `brew install ffmpeg` / `apt install ffmpeg` |
| ffprobe | 视频文件校验 | 随 ffmpeg 附带 |
| yt-dlp | 在线视频下载 | `pip install yt-dlp`（仅 URL 模式需要） |
| DEEPSEEK_API_KEY | 博客合成 | [DeepSeek 开放平台](https://platform.deepseek.com/) 获取 |
| DASHSCOPE_API_KEY | 画面分析 | [DashScope](https://dashscope.aliyun.com/) 获取（仅 `--with-vision` 时需要） |

## 使用方法

### 命令行参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `-u, --url` | string | — | 视频在线链接（仅支持抖音/B站），必须用引号包裹 |
| `-f, --file` | string | — | 本地 mp4 文件路径 |
| `-o, --output` | string | `./output/` | 博客输出目录 |
| `-m, --model` | string | `deepseek-chat` | LLM 模型名 |
| `--provider` | string | `deepseek` | LLM 提供商：deepseek/openai/ollama/qwen |
| `--api-base` | string | — | 自定义 LLM API 端点（优先级高于 --provider） |
| `-t, --temperature` | float | `0.7` | LLM 生成温度（0-2） |
| `--max-tokens` | int | `8192` | LLM 输出最大 token 数 |
| `--with-vision` | flag | false | 开启画面关键帧分析（需 DashScope API） |
| `--vision-model` | string | `qwen-vl-plus` | 视觉模型，可升级 `qwen-vl-max` |
| `--frame-interval` | int | `10` | 关键帧提取间隔（秒），仅 `--with-vision` 时生效 |
| `--no-cache` | flag | false | 跳过转录缓存，强制重新转录 |
| `--keep-temp` | flag | false | 保留中间文件（调试用） |
| `-v, --verbose` | flag | false | 打印详细日志 |

> `-u` 和 `-f` 二选一，必须指定其中一个。

### 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `DEEPSEEK_API_KEY` | 是 | DeepSeek API 密钥 |
| `DASHSCOPE_API_KEY` | 否 | 阿里云 DashScope API 密钥（`--with-vision` 时需要） |
| `WHISPER_MODEL` | 否 | Whisper 模型名，默认 `base`。可选 `tiny` / `small` / `medium` / `large-v3` |
| `BILIBILI_COOKIE` | 否 | B站 cookie 文件路径，用于下载高清/大会员视频 |

也可以在项目根目录创建 `.env` 文件：

```bash
DEEPSEEK_API_KEY="sk-xxx"
DASHSCOPE_API_KEY="sk-xxx"
WHISPER_MODEL="small"
```

### 常见用法

```bash
# 最简用法：从 B 站链接生成
vertoscribe -u "https://www.bilibili.com/video/BV1xx411c7mD"

# 从本地文件生成并指定输出目录
vertoscribe -f ./lecture.mp4 -o ./blogs/

# 开启画面分析 + 详细日志
vertoscribe -f ./tutorial.mp4 --with-vision -v

# 使用更大 Whisper 模型提升转写精度
export WHISPER_MODEL="medium"
vertoscribe -u "https://www.bilibili.com/video/BV1xx411c7mD"

# 调整 LLM 温度和输出长度
vertoscribe -f ./video.mp4 -t 0.5 --max-tokens 4096
```

## 工作原理

```
┌─────────────────────────────────────────────────────────────────┐
│                        vertoscribe 流程                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌───────────┐ │
│  │ 1. 输入  │───▶│ 2. 校验  │───▶│ 3. 音频  │───▶│ 4. 转录   │ │
│  │ 下载/本地│    │ ffprobe  │    │ 提取     │    │ faster-   │ │
│  │ mp4      │    │ 格式检查 │    │ ffmpeg   │    │ whisper   │ │
│  └──────────┘    └──────────┘    └──────────┘    └───────────┘ │
│                                                       │         │
│                                                       ▼         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌───────────┐ │
│  │ 7. 保存  │◀───│ 6. 后处理│◀───│ 5. 合成  │◀───│ 转录文本  │ │
│  │ .md 文件 │    │ TL;DR    │    │ DeepSeek │    │ + 画面描述 │ │
│  │          │    │ 禁用词   │    │ API      │    │ (可选)     │ │
│  └──────────┘    └──────────┘    └──────────┘    └───────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

1. **输入准备**：URL 模式用 yt-dlp 下载视频，本地模式直接使用文件路径
2. **视频校验**：ffprobe 检查是否为有效视频文件
3. **音频提取**：ffmpeg 提取 16kHz 单声道 PCM wav
4. **语音转录**：faster-whisper 本地转写为带时间戳的文本段落（Apple Silicon 自动适配 `compute_type`）
5. **博客合成**：转录文本 + 写作规范模板注入 DeepSeek API，生成结构化 Markdown
6. **后处理检查**：TL;DR / YAML frontmatter / 代码块语言标注 / 禁用词检测，评分并输出警告
7. **保存输出**：写入 `.md` 文件，清理临时文件（可通过 `--keep-temp` 保留）

## 输出示例

生成的 `output/` 目录结构：

```
output/
└── 教你用-Python-写一个简易爬虫.md
```

生成的博客包含：

```markdown
---
title: 教你用 Python 写一个简易爬虫
date: 2025-08-03
tags: [python, crawler, tutorial]
---

## TL;DR
通过 requests + BeautifulSoup 构建一个简易爬虫，抓取豆瓣电影 Top 250 ...

## 前置要求
- 本文假设你已熟悉：Python 基础语法、HTTP 基本概念

## Step 1：发送 HTTP 请求
[解释 + 代码 + 输出]

## Step 2：解析 HTML
[解释 + 代码 + 输出]

...

## 进一步阅读
- [Requests 官方文档](https://docs.python-requests.org/)
- [BeautifulSoup 文档](https://www.crummy.com/software/BeautifulSoup/)
```

## 路线图

### ✅ Phase 1：核心流水线（v0.1.0）
- [x] B站/抖音视频下载（yt-dlp）
- [x] 音频提取（ffmpeg PCM 16kHz）+ ffprobe 校验
- [x] faster-whisper 本地转写（三平台自适应 compute_type）
- [x] DeepSeek API 博客合成（string.Template 注入 + API 重试）
- [x] 写作规范后处理检查（TL;DR / 禁用词 / 代码块标注 / frontmatter）
- [x] 内置 5 种技术博客类型模板
- [x] 临时文件自动清理（atexit 兜底）
- [x] CLI 交互式配置（`vertoscribe config`）+ 多级 .env 加载

### ✅ Phase 2：画面分析（v0.2.0）
- [x] 关键帧提取（ffmpeg fps）+ dHash 去重（Hamming < 5）
- [x] Qwen-VL-Plus/Max 并发分析（asyncio Semaphore 5）
- [x] 画面描述与音频文本时间戳对齐
- [x] 长视频费用预估 + 用户确认交互
- [x] 准确率对比报告（纯音频 vs 含画面）

### ✅ Phase 3：体验优化（v0.2.0）
- [x] 转录文本缓存（SHA256 哈希，~/.cache/vertoscribe/，`--no-cache` 跳过）
- [x] `--verbose` 详细日志
- [x] `--keep-temp` 保留中间文件
- [x] 准确率评估 JSON 报告（`*_report.json`）

### ✅ Phase 4：多模型扩展（v0.2.0）
- [x] LLM 后端：DeepSeek / OpenAI / Ollama / Qwen（`--provider` + `--api-base`）
- [x] Ollama 本地零成本模式（无需 API Key）

### 🔜 后续计划
- [ ] 多语言转录支持
- [ ] 自定义 Prompt 模板（`--prompt-file`）
- [ ] pip 包发布到 PyPI
- [ ] Web UI 界面
- [ ] Docker 一键部署

## 贡献

欢迎贡献代码、报告问题或提出功能建议。

```bash
# 开发环境设置
git clone https://github.com/animacaeli/vertoscribe.git
cd vertoscribe
pip install -e ".[dev]"

# 运行测试
pytest -v

# 代码格式化
black src/ main.py tests/
ruff check src/ main.py tests/
```

提交 PR 前请确保：

- 代码通过 `black` 和 `ruff` 检查
- 所有测试通过 `pytest -v`
- 新功能附带测试用例

## License

MIT License. 详见 [LICENSE](LICENSE) 文件。
