"""DeepSeek API 博客合成封装。

将转录文本和画面描述发送给 DeepSeek，结合写作规范生成技术博客 Markdown。
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
    temperature: float = 0.7,
    max_tokens: int = 8192,
) -> str:
    """调用 DeepSeek API，将转录文本合成为技术博客 Markdown。

    Args:
        transcript: 完整的转录文本。
        output_dir: 输出目录（Phase 2 预留给文件写入逻辑，当前未使用）。
        vision_descriptions: 视频画面的文字描述（可选）。
        model: DeepSeek 模型名称，默认 'deepseek-chat'。
        temperature: 生成温度，默认 0.7。
        max_tokens: 最大输出 token 数，默认 8192。

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

    # 初始化 DeepSeek 客户端（兼容 OpenAI SDK）
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("环境变量 DEEPSEEK_API_KEY 未设置，无法调用 DeepSeek API")

    client = OpenAI(
        base_url="https://api.deepseek.com",
        api_key=api_key,
    )

    return _call_with_retry(
        client,
        model=model,
        system_content=filled_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _call_with_retry(
    client: OpenAI,
    model: str,
    system_content: str,
    temperature: float,
    max_tokens: int,
    max_retries: int = 3,
) -> str:
    """调用 DeepSeek API，含重试逻辑（指数退避）。"""
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": "请根据以上转录文本和写作要求，生成一篇技术博客。"},
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

        content = response.choices[0].message.content or ""

        # 尝试从返回内容中提取 accuracy_score 并打印
        _print_accuracy_score(content)

        return content

    raise RuntimeError(f"DeepSeek API 调用失败（已重试 {max_retries} 次）: {last_error}") from last_error


def _print_accuracy_score(content: str) -> None:
    """从博客内容中提取并打印 accuracy_score。"""
    match = re.search(
        r"(?:accuracy_score|准确度[评分]).*?[:：]\s*(\d+(?:\.\d+)?)",
        content,
        re.IGNORECASE,
    )
    if match:
        print(f"[synthesizer] accuracy_score = {match.group(1)}")
    else:
        print("[synthesizer] 未从返回内容中提取到 accuracy_score")
