"""LLM API 博客合成封装。

将转录文本和画面描述发送给 LLM（支持 DeepSeek/OpenAI/Ollama/Qwen），
结合写作规范生成技术博客 Markdown。
"""

from __future__ import annotations

import os
import re
import string
import time
from pathlib import Path

from openai import OpenAI

from src.blog_rules import get_blog_template

# 项目根目录（vertoscribe/）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 预定义 provider 的 base_url 和默认 key 环境变量
_PROVIDERS = {
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),  # Ollama 本地无需 key
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
}


def _resolve_client(provider: str, api_base: str | None) -> tuple[OpenAI, str]:
    """根据 provider/--api-base 解析 API 客户端和实际 base_url。"""
    if api_base:
        base = api_base
        key_env = "LLM_API_KEY"
    elif provider in _PROVIDERS:
        base, key_env = _PROVIDERS[provider]
    else:
        raise RuntimeError(
            f"不支持的 provider: {provider}。支持: {', '.join(_PROVIDERS.keys())}"
        )

    api_key = None
    if key_env:
        api_key = os.getenv(key_env)

    # Ollama 本地模式不需要 key
    if provider == "ollama" and not api_key:
        api_key = "ollama"  # 占位，Ollama 不校验

    if not api_key:
        raise RuntimeError(
            f"环境变量 {key_env or 'LLM_API_KEY'} 未设置，无法调用 LLM API。"
            f"请运行 'vertoscribe config' 或手动设置环境变量。"
        )

    return OpenAI(base_url=base, api_key=api_key), base


def _load_prompt_template() -> string.Template:
    """从 prompts/blog_synthesis.md 加载 Prompt 模板。"""
    prompt_path = _PROJECT_ROOT / "prompts" / "blog_synthesis.md"
    with open(prompt_path, "r", encoding="utf-8") as f:
        content = f.read()
    return string.Template(content)


def _escape_dollar(text: str) -> str:
    """转义文本中的 $ 符号，防止 string.Template 误解析。

    string.Template 将 $identifier 视为变量占位符。
    转录文本中可能包含 $PATH、$HOME 等，需要转义为 $$。
    """
    return text.replace("$", "$$")


def synthesize(
    transcript: str,
    output_dir: str,
    *,
    vision_descriptions: str = "",
    model: str = "deepseek-chat",
    provider: str = "deepseek",
    api_base: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 16384,
) -> str:
    """调用 LLM API，将转录文本合成为技术博客 Markdown。

    Args:
        transcript: 完整的转录文本。
        output_dir: 输出目录（Phase 2 预留给文件写入逻辑，当前未使用）。
        vision_descriptions: 视频画面的文字描述（可选）。
        model: 模型名称，默认 'deepseek-chat'。
        provider: API 提供商（deepseek/openai/ollama/qwen），默认 deepseek。
        api_base: 自定义 API base URL，优先级高于 provider。
        temperature: 生成温度，默认 0.7。
        max_tokens: 最大输出 token 数，默认 16384（长文初稿 8192 会截断）。

    Returns:
        生成的博客 Markdown 字符串。

    Raises:
        RuntimeError: API 调用失败或响应解析异常时抛出。
    """
    # 加载 Prompt 模板，填充变量
    template = _load_prompt_template()
    blog_structure = get_blog_template()

    # 转义转录文本中的 $ 符号，避免被 string.Template 误解析
    safe_transcript = _escape_dollar(transcript)
    safe_vision = _escape_dollar(vision_descriptions) if vision_descriptions else ""

    filled_prompt = template.safe_substitute(
        transcript=safe_transcript,
        vision_descriptions=safe_vision or "（未开启画面分析，仅基于音频转录生成）",
        blog_structure_template=blog_structure,
    )

    # 根据 provider 解析 API 客户端
    client, resolved_base = _resolve_client(provider, api_base)

    if provider == "ollama":
        print(f"  🤖 本地模型: {model} (via {resolved_base})")

    content = _call_with_retry(
        client,
        model=model,
        system_content=filled_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    _print_accuracy_score(content)
    return content


def _transform_pass(
    draft: str,
    prompt_file: str,
    *,
    user_content: str,
    label: str,
    model: str,
    provider: str,
    api_base: str | None,
    temperature: float,
    max_tokens: int,
) -> str:
    """加载 prompts/ 下的转换模板（重写/补全）并执行一次 LLM pass。"""
    prompt_path = _PROJECT_ROOT / "prompts" / prompt_file
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = string.Template(f.read())

    filled = template.safe_substitute(draft=_escape_dollar(draft))
    client, _ = _resolve_client(provider, api_base)

    content = _call_with_retry(
        client,
        model=model,
        system_content=filled,
        user_content=user_content,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    _print_accuracy_score(content, label=label)
    return content


def rewrite_blog(
    draft: str,
    *,
    model: str = "deepseek-chat",
    provider: str = "deepseek",
    api_base: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 16384,
) -> str:
    """调用 LLM 对初稿做"去 AI 味"重写（prompts/blog_rewrite.md）。

    技术事实、代码、图表保留，只重写表达。失败时抛 RuntimeError。
    """
    print("  ✍️  文风重写 pass...")
    return _transform_pass(
        draft,
        "blog_rewrite.md",
        user_content="请按重写原则输出重写后的完整博客。",
        label="重写稿",
        model=model,
        provider=provider,
        api_base=api_base,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _call_with_retry(
    client: OpenAI,
    model: str,
    system_content: str,
    temperature: float,
    max_tokens: int,
    user_content: str = "请根据以上转录文本和写作要求，生成一篇技术博客。",
    max_retries: int = 3,
) -> str:
    """调用 LLM API，含重试逻辑（指数退避）。"""
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=120.0,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < max_retries:
                wait = 2 ** attempt  # 1s → 2s → 4s
                print(f"  API 调用失败 (第 {attempt + 1}/{max_retries + 1} 次)，{wait}s 后重试...")
                time.sleep(wait)
                continue
            break

        if not response.choices:
            raise RuntimeError("DeepSeek API 返回了空的 choices 列表")

        choice = response.choices[0]
        content = choice.message.content or ""
        # 截断的输出会被静默保存成半篇文章（曾出现结尾断句、缺 accuracy_score），
        # 必须当作失败重试而不是原样返回
        if choice.finish_reason == "length":
            last_error = RuntimeError(
                f"输出被 max_tokens={max_tokens} 截断（finish_reason=length）"
            )
            if attempt < max_retries:
                wait = 2 ** attempt
                print(f"  输出被截断 (第 {attempt + 1}/{max_retries + 1} 次)，{wait}s 后重试...")
                time.sleep(wait)
                continue
            raise RuntimeError(
                f"LLM 输出持续被截断（已重试 {max_retries} 次），"
                f"请调大 max_tokens 或精简提示词"
            ) from last_error

        return content

    raise RuntimeError(f"DeepSeek API 调用失败（已重试 {max_retries} 次）: {last_error}") from last_error


def enrich_blog(
    draft: str,
    *,
    model: str = "deepseek-chat",
    provider: str = "deepseek",
    api_base: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 16384,
) -> str:
    """调用 LLM 做定向补全 pass（prompts/blog_enrichment.md）。

    完整度评分低于门槛时使用：只补评估段列出的缺口，其余内容不动。
    失败时抛 RuntimeError。
    """
    print("  🧩 完整度补全 pass...")
    return _transform_pass(
        draft,
        "blog_enrichment.md",
        user_content="请按补全规则输出补全后的完整博客。",
        label="补全稿",
        model=model,
        provider=provider,
        api_base=api_base,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def extract_accuracy_score(content: str) -> float | None:
    """从博客内容中提取 accuracy_score，无则返回 None。"""
    match = re.search(
        r"(?:accuracy_score|准确度[评分]).*?[:：]\s*(\d+(?:\.\d+)?)",
        content,
        re.IGNORECASE,
    )
    return float(match.group(1)) if match else None


def _print_accuracy_score(content: str, label: str = "初稿") -> None:
    """从博客内容中提取并打印 accuracy_score。"""
    score = extract_accuracy_score(content)
    if score is not None:
        print(f"[synthesizer] {label} accuracy_score = {score:g}")
    else:
        print(f"[synthesizer] 未从{label}中提取到 accuracy_score")
